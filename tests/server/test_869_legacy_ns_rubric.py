"""Integration tests for issue #869: legacy 自然科學 records in 人工審題修正.

Tasks 4.4 (edit path) and 4.5 (read path).

Edit path (4.4)
---------------
A stored 自然科學 record whose Constructed response 小題 has a legacy
2/1/0/0X rubric with empty examples goes through 人工審題修正.
The LLM verifier returns ``passed=True``, but ``_ns_rubric_shape_check_hook``
overrides to ``passed=False`` with ``[評分規準形狀檢核]`` entries.  A
conforming corrector output is accepted on the next round and saved as a
new record linked by ``parent_record_id``.  The original is unchanged.

Read path (4.5)
---------------
A stored record whose rubric has codes 3/2/1/0/0X and empty example lists
loads without error and its levels are returned exactly as stored.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from collections.abc import AsyncGenerator

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationRecord, User
from server.rate_limit import limiter
from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE


# ---------------------------------------------------------------------------
# Shared app fixture (same pattern as test_modification_correction_structure)
# ---------------------------------------------------------------------------


@pytest.fixture
def app_ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(init())
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret", max_retries=2)
    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    yield app, session_factory, config

    limiter.reset()
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Helpers: legacy NS question with 2/1/0/0X rubric, no examples
# ---------------------------------------------------------------------------


def _legacy_ns_question() -> dict:
    """Return a question dict with a Constructed response subquestion
    whose rubric is 2/1/0/0X with empty example lists (pre-#866 shape)."""
    return {
        "id": "ns-legacy-0x-rubric",
        "核心問題": "核心問題",
        "文本": "文本素材。",
        "取材來源": [],
        "情境": ["Local and national"],
        "情境子類別": "Environmental impact",
        "題型種類": "題組題",
        "題型": "Simple multiple-choice",
        "科學能力": ["能力一：以科學的角度解釋現象"],
        "題目": [],
        "正確解題分析": [],
        "subquestions": [
            {
                "id": "ns-sq-1",
                "序號": 1,
                "年級": 8,
                "科目": ["自然科學"],
                "科學能力": ["能力一：以科學的角度解釋現象"],
                "核心素養": [],
                "學習內容": [{"編碼": "Ab-Ⅳ-1", "說明": "學習內容"}],
                "學習表現": [{"編碼": "tr-Ⅳ-1", "說明": "學習表現"}],
                "出題概念": "",
                "題型": "Constructed response",
                "題目": "請說明此現象的原因。",
                "答案": "因為分子運動加快。",
                "答案解析": "原始解析",
                "評分規準": [
                    {"code": "2", "規準說明": "完整說明原因並有證據支持。", "學生作答實例": []},
                    {"code": "1", "規準說明": "部分說明。", "學生作答實例": []},
                    {"code": "0", "規準說明": "未說明。", "學生作答實例": []},
                    {"code": "0X", "規準說明": "未作答。", "學生作答實例": []},
                ],
                "誘答分析": {},
            }
        ],
    }


def _conforming_ns_question(base: dict) -> dict:
    """Return a version of *base* whose rubric is conforming: 2/1/0,
    1/2/1 non-empty examples, and [2] 規準說明 ends with EXTRA_ITEMS_FIXED_SENTENCE."""
    q = copy.deepcopy(base)
    sq = q["subquestions"][0]
    sq["題目"] = "請說明此現象的成因。"  # slightly edited to show modification
    sq["評分規準"] = [
        {
            "code": "2",
            "規準說明": (
                "完整說明溫度升高導致分子運動加快進而體積膨脹，並有證據支持。"
                f"{EXTRA_ITEMS_FIXED_SENTENCE}"
            ),
            "學生作答實例": ["因為溫度升高，分子運動加快，所以體積膨脹。"],
        },
        {
            "code": "1",
            "規準說明": "有提到溫度或分子，但未完整連結推理。",
            "學生作答實例": ["因為溫度升高。", "分子運動加快，所以膨脹。"],
        },
        {
            "code": "0",
            "規準說明": "未進入推理或方向錯誤。",
            "學生作答實例": ["因為加熱。"],
        },
    ]
    return q


def _seed_ns_record(session_factory, payload: dict) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    record_id = uuid.uuid4()

    async def insert() -> None:
        async with session_factory() as session:
            session.add(User(id=user_id, email=f"{user_id}@example.com"))
            session.add(
                GenerationRecord(
                    id=record_id,
                    user_id=user_id,
                    subject="natural_sciences",
                    question_id=payload["id"],
                    params_json={"subject": "natural_sciences"},
                    question_json=payload,
                    image_files=[],
                )
            )
            await session.commit()

    asyncio.run(insert())
    return user_id, record_id


# ---------------------------------------------------------------------------
# Scripted LLM provider for edit-path test
# ---------------------------------------------------------------------------


class _CaptureProvider:
    """Scripted provider that also records what user prompts it receives.

    generate_json  → correction candidates (list indexed by call number)
    generate_with_image → verification responses (list indexed by call number)
    """

    def __init__(
        self,
        corrections: list[dict],
        verifications: list[dict],
    ) -> None:
        self.corrections = corrections
        self.verifications = verifications
        self.correct_calls = 0
        self.verify_calls = 0
        self.correction_user_prompts: list[str] = []
        self._observer = None

    def set_observer(self, observer) -> None:
        self._observer = observer

    def generate_json(self, system: str, user: str, *_args, **_kwargs) -> dict:
        self.correction_user_prompts.append(user)
        index = min(self.correct_calls, len(self.corrections) - 1)
        self.correct_calls += 1
        return copy.deepcopy(self.corrections[index])

    def generate_with_image(self, system: str, user: str, *_args, **_kwargs) -> str:
        index = min(self.verify_calls, len(self.verifications) - 1)
        self.verify_calls += 1
        return json.dumps(self.verifications[index], ensure_ascii=False)


# ---------------------------------------------------------------------------
# Helper: run the modification stream and return results
# ---------------------------------------------------------------------------


def _run_modification_stream(
    app,
    config,
    user_id: uuid.UUID,
    record_id: uuid.UUID,
    provider,
    annotation_payload: dict,
) -> tuple[list[dict], dict, dict, dict]:
    """Admit + stream a modification run; return (events, parent_history, parent_download, child_history)."""
    token = create_jwt(user_id, "user@example.com", config=config)
    headers = {"Authorization": f"Bearer {token}"}
    app.state.modification_client_factory = lambda _config: provider

    with TestClient(app) as client:
        admission = client.post(
            f"/api/generation-records/{record_id}/modifications",
            json=annotation_payload,
            headers=headers,
        )
        assert admission.status_code == 200, admission.text
        run_id = admission.json()["run_id"]

        stream = client.get(
            f"/api/generation-records/{record_id}/modifications/{run_id}/stream",
            headers=headers,
        )
        assert stream.status_code == 200, stream.text
        events = _parse_sse_events(stream.text)

        # History for the parent (original) record
        parent_hist = client.get(f"/api/history/{record_id}", headers=headers)
        assert parent_hist.status_code == 200, parent_hist.text
        parent_hist_body = parent_hist.json()

        # The child record is the latest terminal descendant
        child_id = parent_hist_body["id"]
        child_hist = client.get(f"/api/history/{child_id}", headers=headers)
        assert child_hist.status_code == 200, child_hist.text

        # Download returns the raw original record
        parent_dl = client.get(f"/api/history/{record_id}/download", headers=headers)
        assert parent_dl.status_code == 200, parent_dl.text

    return events, parent_hist_body, parent_dl.json(), child_hist.json()


def _parse_sse_events(body: str) -> list[dict]:
    events: list[dict] = []
    current: dict[str, str] = {}
    for line in body.splitlines():
        if line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current["data"] = line.split(":", 1)[1].strip()
        elif not line and current:
            raw_data = current.get("data", "")
            events.append(
                {
                    "event": current["event"],
                    "data": json.loads(raw_data) if raw_data else "",
                }
            )
            current = {}
    if current:
        raw_data = current.get("data", "")
        events.append(
            {"event": current["event"], "data": json.loads(raw_data) if raw_data else ""}
        )
    return events


# ---------------------------------------------------------------------------
# Task 4.4 — Edit path integration test
# ---------------------------------------------------------------------------


def test_legacy_ns_0x_rubric_fails_shape_check_on_edit_and_corrected_result_is_new_record(
    app_ctx,
) -> None:
    """Task 4.4: a legacy NS record (2/1/0/0X, no examples) goes through
    人工審題修正.

    Verifies three assertions from the acceptance criteria:
    (a) Re-verification fails with [評分規準形狀檢核] shape entries in details.
    (b) The corrected result is saved as a new record linked by parent_record_id.
    (c) The original record's question_json is unchanged.
    """
    app, session_factory, config = app_ctx

    # ------------------------------------------------------------------
    # Seed: legacy question with 2/1/0/0X rubric, empty examples
    # ------------------------------------------------------------------
    base = _legacy_ns_question()
    original_json = copy.deepcopy(base)
    user_id, record_id = _seed_ns_record(session_factory, base)

    # ------------------------------------------------------------------
    # Scripted provider:
    #   - Modification corrector (call 0): returns the same question with
    #     the old rubric still intact — only 題目 text changes slightly.
    #   - Verifier (call 0): LLM says passed=True; hook will override to False
    #     because rubric has 0X, no examples, no fixed sentence.
    #   - Correction corrector (call 1): returns conforming 2/1/0 rubric.
    #   - Verifier (call 1): LLM says passed=True; hook also passes now.
    # ------------------------------------------------------------------
    after_modification = copy.deepcopy(base)
    after_modification["subquestions"][0]["題目"] = "請說明此現象的成因。"
    # Keep old rubric in the modification output so verify hook triggers.

    conforming = _conforming_ns_question(base)

    provider = _CaptureProvider(
        corrections=[after_modification, conforming],
        verifications=[
            {"passed": True, "answer_match": True, "details": "LLM 通過"},
            {"passed": True, "answer_match": True, "details": "修正後通過"},
        ],
    )

    # Annotate subquestions[0].題目 → makes 評分規準 an editable path too.
    sq0_題目 = base["subquestions"][0]["題目"]
    annotation_payload = {
        "annotations": [
            {
                "segments": [
                    {
                        "field_path": "subquestions[0].題目",
                        "start": 0,
                        "end": len(sq0_題目),
                        "quoted_text": sq0_題目,
                    }
                ],
                "修改指示": "請稍微改寫此小題題目。",
            }
        ]
    }

    events, parent_hist, parent_download, child_hist = _run_modification_stream(
        app, config, user_id, record_id, provider, annotation_payload
    )

    # ------------------------------------------------------------------
    # Assertion (a): Re-verification failed with [評分規準形狀檢核] entries.
    #
    # The hook overrides the LLM's passed=True to False, so the service
    # enters a correction round (verify_calls == 2, correct_calls == 2).
    # The second correction prompt must contain the shape-check string
    # because that is the details text from the failed verification.
    # ------------------------------------------------------------------
    assert provider.verify_calls == 2, (
        f"Expected 2 verification calls (one failing due to shape hook, "
        f"one passing after correction), got {provider.verify_calls}"
    )
    assert provider.correct_calls == 2, (
        f"Expected 2 correction calls (one for initial modification, "
        f"one after shape-check failure), got {provider.correct_calls}"
    )

    # The second correction user prompt should contain the shape check marker
    # because it carries the details from the failed verification.
    assert len(provider.correction_user_prompts) >= 2, (
        f"Expected at least 2 correction prompts, got {len(provider.correction_user_prompts)}"
    )
    second_correction_prompt = provider.correction_user_prompts[1]
    assert "[評分規準形狀檢核]" in second_correction_prompt, (
        f"Expected '[評分規準形狀檢核]' in second correction prompt; "
        f"prompt starts with: {second_correction_prompt[:300]!r}"
    )

    # ------------------------------------------------------------------
    # Assertion (b): Corrected result saved as new record linked by parent.
    # The history API resolves parent_record_id → latest descendant, so
    # parent_hist["id"] is now the child record's ID.
    # The child's params_json["record_id"] stores the original record_id.
    # ------------------------------------------------------------------
    result_event = next(
        (event["data"] for event in events if event["event"] == "result"), None
    )
    assert result_event is not None, "No result event in SSE stream"
    assert result_event["verified"] is True

    child_record_id = result_event["record_id"]
    assert child_record_id is not None
    assert child_record_id != str(record_id), (
        "Expected a NEW record, but got the same record_id"
    )

    # The parent history now resolves to the child (latest descendant).
    assert parent_hist["id"] == child_record_id

    # The child params_json["record_id"] stores the original (parent) record_id.
    assert child_hist["params_json"]["record_id"] == str(record_id), (
        "child record's params_json['record_id'] should point to the original record"
    )

    # The child rubric should be conforming (2/1/0, no 0X).
    child_rubric_codes = [
        r["code"]
        for r in child_hist["question_json"]["subquestions"][0]["評分規準"]
    ]
    assert child_rubric_codes == ["2", "1", "0"], (
        f"Expected conforming rubric codes ['2', '1', '0'], got {child_rubric_codes}"
    )

    # ------------------------------------------------------------------
    # Assertion (c): Original record's question_json is unchanged.
    # The download endpoint serves the original record's stored JSON.
    # ------------------------------------------------------------------
    # download returns params_json merged in — strip it for comparison.
    downloaded = dict(parent_download)
    downloaded.pop("params_json", None)
    assert downloaded == original_json, (
        "Original record's question_json was mutated during 人工審題修正"
    )


# ---------------------------------------------------------------------------
# Task 4.5 — Read path backward compatibility test
# ---------------------------------------------------------------------------


def test_legacy_record_with_extra_rubric_codes_and_empty_examples_loads_as_stored(
    app_ctx,
) -> None:
    """Task 4.5: a stored record with codes 3/2/1/0/0X and empty example lists
    loads without error and its rubric levels are returned exactly as stored,
    in stored order.  No schema or persistence change is needed.
    """
    app, session_factory, config = app_ctx

    # Build the legacy question_json directly (bypassing Pydantic) so that
    # we can store any code strings (3, 0X) without enum validation.
    legacy_rubric = [
        {"code": "3", "規準說明": "超出預期的完整說明。", "學生作答實例": []},
        {"code": "2", "規準說明": "完整說明原因並有證據支持。", "學生作答實例": []},
        {"code": "1", "規準說明": "部分說明。", "學生作答實例": []},
        {"code": "0", "規準說明": "未說明。", "學生作答實例": []},
        {"code": "0X", "規準說明": "未作答。", "學生作答實例": []},
    ]
    legacy_question = {
        "id": "ns-legacy-5-codes",
        "核心問題": "核心問題",
        "文本": "文本素材。",
        "取材來源": [],
        "情境": ["Local and national"],
        "情境子類別": "Environmental impact",
        "題型種類": "題組題",
        "題型": "Simple multiple-choice",
        "科學能力": ["能力一：以科學的角度解釋現象"],
        "題目": [],
        "正確解題分析": [],
        "subquestions": [
            {
                "id": "ns-sq-1",
                "序號": 1,
                "年級": 8,
                "科目": ["自然科學"],
                "科學能力": ["能力一：以科學的角度解釋現象"],
                "核心素養": [],
                "學習內容": [{"編碼": "Ab-Ⅳ-1", "說明": "學習內容"}],
                "學習表現": [{"編碼": "tr-Ⅳ-1", "說明": "學習表現"}],
                "出題概念": "",
                "題型": "Constructed response",
                "題目": "請說明。",
                "答案": "答案",
                "答案解析": "解析",
                "評分規準": legacy_rubric,
                "誘答分析": {},
            }
        ],
    }

    user_id = uuid.uuid4()
    record_id = uuid.uuid4()

    async def insert() -> None:
        async with session_factory() as session:
            session.add(User(id=user_id, email=f"{user_id}@example.com"))
            session.add(
                GenerationRecord(
                    id=record_id,
                    user_id=user_id,
                    subject="natural_sciences",
                    question_id=legacy_question["id"],
                    params_json={"subject": "natural_sciences"},
                    question_json=legacy_question,
                    image_files=[],
                )
            )
            await session.commit()

    asyncio.run(insert())

    token = create_jwt(user_id, "user@example.com", config=config)
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        # (1) History list endpoint must load the record without error.
        list_r = client.get("/api/history?limit=10", headers=headers)
        assert list_r.status_code == 200, list_r.text
        items = list_r.json()["items"]
        assert any(item["question_id"] == "ns-legacy-5-codes" for item in items), (
            "Legacy record not found in history list"
        )

        # (2) History detail endpoint must return the rubric exactly as stored.
        detail_r = client.get(f"/api/history/{record_id}", headers=headers)
        assert detail_r.status_code == 200, (
            f"History detail returned {detail_r.status_code}: {detail_r.text}"
        )
        body = detail_r.json()
        returned_rubric = body["question_json"]["subquestions"][0]["評分規準"]
        returned_codes = [entry["code"] for entry in returned_rubric]

        assert returned_codes == ["3", "2", "1", "0", "0X"], (
            f"Expected codes ['3', '2', '1', '0', '0X'] in stored order; "
            f"got {returned_codes}"
        )

        # All example lists must be empty (as stored).
        for entry in returned_rubric:
            assert entry["學生作答實例"] == [], (
                f"Expected empty examples for code {entry['code']!r}, "
                f"got {entry['學生作答實例']!r}"
            )
