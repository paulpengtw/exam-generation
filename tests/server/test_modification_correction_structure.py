"""Public manual-correction tests for rejected candidates and version history."""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from collections.abc import AsyncGenerator

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationRecord, User
from server.rate_limit import limiter

SUBJECTS = ("social_studies", "natural_sciences", "math")


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


def _question(subject: str) -> dict:
    if subject == "social_studies":
        from src.social_studies.schemas import (
            ExamQuestion,
            ImageSpec,
            QuestionContext,
            QuestionSetType,
            QuestionType,
            RubricEntry,
            SubQuestion,
        )

        question = ExamQuestion(
            id="ss-manual-structure",
            核心問題="原始核心問題",
            文本="原始文本",
            取材來源=["原始來源"],
            情境=[next(iter(QuestionContext))],
            題型種類=next(iter(QuestionSetType)),
            題型=next(iter(QuestionType)),
            subquestions=[
                SubQuestion(
                    id="ss-sq-1",
                    序號=1,
                    年級=8,
                    題型=next(iter(QuestionType)),
                    題目="第一小題原題目",
                    答案="第一小題原答案",
                    答案解析="第一小題原解析",
                    評分規準=[RubricEntry(code="1", 規準說明="第一小題原規準")],
                ),
                SubQuestion(
                    id="ss-sq-2",
                    序號=2,
                    年級=8,
                    題型=next(iter(QuestionType)),
                    題目="第二小題原題目",
                    答案="第二小題原答案",
                ),
            ],
            chart_spec=ImageSpec(
                title="原始圖表",
                data={"values": [1, 2]},
                labels={"x": "原始標籤"},
            ),
        )
    elif subject == "natural_sciences":
        from src.natural_sciences.schemas import (
            ExamQuestion,
            ImageSpec,
            LearningContentRef,
            SubQuestion,
        )

        question = ExamQuestion(
            id="ns-manual-structure",
            核心問題="原始核心問題",
            文本="原始文本",
            情境=["Local and national"],
            情境子類別="Environmental impact",
            題型種類="題組題",
            題型="Simple multiple-choice",
            科學能力=["能力一：以科學的角度解釋現象"],
            subquestions=[
                SubQuestion(
                    id="ns-sq-1",
                    序號=1,
                    年級=8,
                    科目=["自然科學"],
                    科學能力=["能力一：以科學的角度解釋現象"],
                    學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="原始內容")],
                    學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="原始表現")],
                    題型="Simple multiple-choice",
                    題目="第一小題原題目",
                    答案="第一小題原答案",
                ),
                SubQuestion(
                    id="ns-sq-2",
                    序號=2,
                    年級=8,
                    科目=["自然科學"],
                    學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="原始內容")],
                    學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="原始表現")],
                    題型="Simple multiple-choice",
                    題目="第二小題原題目",
                    答案="第二小題原答案",
                ),
            ],
            chart_spec=ImageSpec(
                title="原始圖表",
                data={"values": [1, 2]},
                labels={"x": "原始標籤"},
            ),
        )
    else:
        from src.schemas import ExamQuestion, ImageSpec, LearningContentItem, SubQuestion

        question = ExamQuestion(
            id="math-manual-structure",
            核心問題="原始核心問題",
            文本="原始文本",
            情境=["個人"],
            題型種類="題組題",
            題型="選擇題",
            數學思考=["運用"],
            學習內容=[LearningContentItem(編碼="N-7-1", 說明="原始內容")],
            題目=["原始數學題幹"],
            正確解題分析=["原始分析"],
            subquestions=[
                SubQuestion(
                    id="math-sq-1",
                    序號=1,
                    年級=8,
                    題型="選擇題",
                    題目="第一小題原題目",
                    答案="第一小題原答案",
                ),
                SubQuestion(
                    id="math-sq-2",
                    序號=2,
                    年級=8,
                    題型="選擇題",
                    題目="第二小題原題目",
                    答案="第二小題原答案",
                ),
            ],
            chart_spec=ImageSpec(title="原始圖表", data={"values": [1, 2]}),
        )

    payload = json.loads(question.model_dump_json(exclude_none=True))
    payload["圖片"] = f"{subject}-existing.png"
    return payload


def _seed_record(session_factory, subject: str, payload: dict) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    record_id = uuid.uuid4()

    async def insert() -> None:
        async with session_factory() as session:
            session.add(User(id=user_id, email=f"{user_id}@example.com"))
            session.add(
                GenerationRecord(
                    id=record_id,
                    user_id=user_id,
                    subject=subject,
                    question_id=payload["id"],
                    params_json={"subject": subject},
                    question_json=payload,
                    image_files=[],
                )
            )
            await session.commit()

    asyncio.run(insert())
    return user_id, record_id


class _Provider:
    """Scripted provider at the route's documented client-factory boundary."""

    def __init__(self, corrections: list[dict], verifications: list[dict]) -> None:
        self.corrections = corrections
        self.verifications = verifications
        self.correct_calls = 0
        self.verify_calls = 0
        self.verification_prompts: list[str] = []
        self._observer = None

    def set_observer(self, observer) -> None:
        self._observer = observer

    def generate_json(self, *_args, **_kwargs) -> dict:
        index = min(self.correct_calls, len(self.corrections) - 1)
        self.correct_calls += 1
        return copy.deepcopy(self.corrections[index])

    def generate_with_image(self, *_args, **_kwargs) -> str:
        index = min(self.verify_calls, len(self.verifications) - 1)
        self.verify_calls += 1
        if len(_args) > 1 and isinstance(_args[1], str):
            self.verification_prompts.append(_args[1])
        return json.dumps(self.verifications[index], ensure_ascii=False)


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
            {
                "event": current["event"],
                "data": json.loads(raw_data) if raw_data else "",
            }
        )
    return events


def _annotation(subject: str, payload: dict, *, source: bool = False) -> dict:
    if source and subject == "math":
        field_path = "題目[0]"
        quoted_text = payload["題目"][0]
    elif source:
        field_path = "文本"
        quoted_text = payload["文本"]
    else:
        field_path = "subquestions[0].答案"
        quoted_text = payload["subquestions"][0]["答案"]
    return {
        "annotations": [
            {
                "segments": [
                    {
                        "field_path": field_path,
                        "start": 0,
                        "end": len(quoted_text),
                        "quoted_text": quoted_text,
                    }
                ],
                "修改指示": "請修正第一小題，保留其餘題組結構。",
            }
        ]
    }


def _invalid_candidate(payload: dict) -> dict:
    candidate = copy.deepcopy(payload)
    candidate["subquestions"] = candidate["subquestions"][:-1]
    candidate["subquestions"][0]["答案"] = "不應套用的答案"
    candidate["文本"] = "不應套用的文本"
    candidate["核心問題"] = "不應套用的核心問題"
    return candidate


def _valid_candidate(payload: dict) -> dict:
    candidate = copy.deepcopy(payload)
    candidate["subquestions"][0]["答案"] = "接受後的答案"
    candidate["核心問題"] = "不在 scope 的核心問題"
    candidate["取材來源"] = ["不在 scope 的來源"]
    return candidate


def _run_stream(
    app, config, user_id, record_id, provider, payload
) -> tuple[list[dict], dict, dict, dict]:
    token = create_jwt(user_id, "user@example.com", config=config)
    headers = {"Authorization": f"Bearer {token}"}
    app.state.modification_client_factory = lambda _config: provider
    with TestClient(app) as client:
        admission = client.post(
            f"/api/generation-records/{record_id}/modifications",
            json=payload,
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
        history = client.get(f"/api/history/{record_id}", headers=headers)
        assert history.status_code == 200, history.text
        history_body = history.json()
        child_id = history_body["id"]
        child_history = client.get(f"/api/history/{child_id}", headers=headers)
        assert child_history.status_code == 200, child_history.text
        parent_download = client.get(f"/api/history/{record_id}/download", headers=headers)
        assert parent_download.status_code == 200, parent_download.text
    return events, history_body, parent_download.json(), child_history.json()


@pytest.mark.parametrize("subject", SUBJECTS)
def test_manual_stream_retries_rejected_candidates_then_persists_scoped_acceptance(
    app_ctx, subject: str
) -> None:
    app, session_factory, config = app_ctx
    base = _question(subject)
    user_id, record_id = _seed_record(session_factory, subject, base)
    provider = _Provider(
        [_invalid_candidate(base), _invalid_candidate(base), _valid_candidate(base)],
        [
            {"passed": False, "answer_match": False, "details": "第一次保留驗證"},
            {"passed": False, "answer_match": False, "details": "第二次保留驗證"},
            {"passed": True, "answer_match": True, "details": "修正後通過"},
        ],
    )

    events, history, parent_download, child_history = _run_stream(
        app,
        config,
        user_id,
        record_id,
        provider,
        _annotation(subject, base),
    )

    assert provider.correct_calls == 3
    assert provider.verify_calls == 3
    result = next(event for event in events if event["event"] == "result")["data"]
    assert result["verified"] is True
    assert result["question"]["subquestions"][0]["答案"] == "接受後的答案"
    assert result["question"]["subquestions"][1] == base["subquestions"][1]
    assert result["question"]["核心問題"] == base["核心問題"]
    assert result["question"].get("取材來源", []) == base.get("取材來源", [])
    assert result["question"]["圖片"] == base["圖片"]
    assert result["question"]["chart_spec"] == base["chart_spec"]

    errors = [
        event["data"]
        for event in events
        if event["event"] == "stage" and event["data"].get("status") == "error"
    ]
    assert len(errors) == 2
    assert [error["stage"] for error in errors] == ["modification", "correct"]
    assert all(error["code"] == "correction_rejected" for error in errors)
    assert all(error["reason"]["code"] == "subquestions_count" for error in errors)
    assert all(error["reason"]["path"] == "subquestions" for error in errors)
    assert all(error["reason"]["message"] for error in errors)
    assert all(error["question_id"] == base["id"] for error in errors)
    assert [error["retry"] for error in errors] == [0, 1]
    assert (
        sum(
            event["data"].get("stage") == "correct" and event["data"].get("status") == "end"
            for event in events
            if event["event"] == "stage"
        )
        == 1
    )

    assert history["id"] == result["record_id"]
    assert history["question_json"]["subquestions"][0]["答案"] == "接受後的答案"
    parent_download.pop("params_json")
    assert parent_download == base
    assert child_history["id"] == result["record_id"]
    assert child_history["params_json"]["record_id"] == str(record_id)
    assert child_history["question_json"]["subquestions"][0]["答案"] == "接受後的答案"
    assert child_history["verification_trail"] is None


@pytest.mark.parametrize("subject", SUBJECTS)
def test_manual_stream_rejection_after_acceptance_keeps_last_accepted_snapshot(
    app_ctx, subject: str
) -> None:
    app, session_factory, config = app_ctx
    base = _question(subject)
    accepted = _valid_candidate(base)
    user_id, record_id = _seed_record(session_factory, subject, base)
    provider = _Provider(
        [accepted, _invalid_candidate(accepted), _invalid_candidate(accepted)],
        [
            {"passed": False, "answer_match": False, "details": "仍需檢查"},
            {"passed": False, "answer_match": False, "details": "保留已接受修正"},
            {"passed": True, "answer_match": True, "details": "保留內容通過"},
        ],
    )

    events, history, parent_download, child_history = _run_stream(
        app,
        config,
        user_id,
        record_id,
        provider,
        _annotation(subject, base),
    )

    assert provider.correct_calls == 3
    assert provider.verify_calls == 3
    assert len(provider.verification_prompts) == 3
    assert all("接受後的答案" in prompt for prompt in provider.verification_prompts)
    assert all("不應套用的答案" not in prompt for prompt in provider.verification_prompts)
    result = next(event for event in events if event["event"] == "result")["data"]
    assert result["verified"] is True
    assert result["question"]["subquestions"][0]["答案"] == "接受後的答案"
    assert result["question"]["subquestions"][1] == base["subquestions"][1]

    errors = [
        event["data"]
        for event in events
        if event["event"] == "stage" and event["data"].get("status") == "error"
    ]
    assert len(errors) == 2
    assert [error["retry"] for error in errors] == [1, 2]
    assert all(error["code"] == "correction_rejected" for error in errors)
    assert all(error["reason"]["path"] == "subquestions" for error in errors)
    assert not any(
        event["event"] == "stage"
        and event["data"].get("stage") == "correct"
        and event["data"].get("status") == "end"
        for event in events
    )

    assert history["id"] == result["record_id"]
    assert history["question_json"]["subquestions"][0]["答案"] == "接受後的答案"
    parent_download.pop("params_json")
    assert parent_download == base
    assert child_history["id"] == result["record_id"]
    assert child_history["params_json"]["record_id"] == str(record_id)
    assert child_history["question_json"]["subquestions"][0]["答案"] == "接受後的答案"
    assert child_history["verification_trail"] is None


@pytest.mark.parametrize(
    ("subject", "initial_stale", "final_passed"),
    [pytest.param(subject, False, False, id=subject) for subject in SUBJECTS]
    + [pytest.param("natural_sciences", True, True, id="natural-sciences-preserve-stale-pass")],
)
def test_manual_stream_keeps_retained_payload_after_rejection_exhaustion_and_stale_state(
    app_ctx, subject: str, initial_stale: bool, final_passed: bool
) -> None:
    app, session_factory, config = app_ctx
    config.max_retries = 2
    base = _question(subject)
    if initial_stale:
        base["image_stale"] = True
    user_id, record_id = _seed_record(session_factory, subject, base)
    provider = _Provider(
        [_invalid_candidate(base)] * 3,
        [
            {"passed": False, "answer_match": False, "details": "保留原題"},
            {"passed": False, "answer_match": False, "details": "仍需檢查"},
            {
                "passed": final_passed,
                "answer_match": final_passed,
                "details": "原題驗證通過" if final_passed else "原題仍需修正",
            },
        ],
    )

    events, history, parent_download, child_history = _run_stream(
        app,
        config,
        user_id,
        record_id,
        provider,
        _annotation(subject, base, source=True),
    )

    assert provider.correct_calls == 3
    assert provider.verify_calls == 3
    assert len(provider.verification_prompts) == 3
    assert all("原始文本" in prompt for prompt in provider.verification_prompts)
    assert all("不應套用的文本" not in prompt for prompt in provider.verification_prompts)
    result = next(event for event in events if event["event"] == "result")["data"]
    assert result["verified"] is final_passed
    assert result["failure_details"] == (None if final_passed else "原題仍需修正")
    assert result["question"]["subquestions"] == base["subquestions"]
    assert result["question"].get("image_stale", False) is initial_stale
    assert history["question_json"].get("image_stale", False) is initial_stale
    assert result["question"]["圖片"] == base["圖片"]
    assert result["question"]["chart_spec"] == base["chart_spec"]
    assert (
        len(
            [
                event
                for event in events
                if event["event"] == "stage" and event["data"].get("status") == "error"
            ]
        )
        == 3
    )
    assert not any(
        event["event"] == "stage"
        and event["data"].get("stage") == "correct"
        and event["data"].get("status") == "end"
        for event in events
    )

    parent_download.pop("params_json")
    assert parent_download == base
    assert child_history["id"] == result["record_id"]
    assert child_history["params_json"]["record_id"] == str(record_id)
    assert child_history["question_json"]["subquestions"] == base["subquestions"]
    assert child_history["question_json"].get("image_stale", False) is initial_stale
    assert child_history["verification_trail"] is None
