"""HTTP contract tests for 人工審題修正 admission."""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationLog, GenerationRecord, LLMExchange, User
from server.rate_limit import limiter


@pytest.fixture
def app_ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret")
    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    yield app, SessionLocal, config

    limiter.reset()
    asyncio.run(engine.dispose())


def _seed_record(
    SessionLocal,
    *,
    owner_id: uuid.UUID | None = None,
    question_json: dict | None = None,
    parent_record_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = owner_id or uuid.uuid4()
    record_id = uuid.uuid4()
    payload = question_json or {
        "id": "ss-question-1",
        "核心問題": "核心問題",
        "文本": "這是一段文本。",
        "subquestions": [{"題目": "第一小題題目", "答案": "答案"}],
    }

    async def insert() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email=f"{user_id}@example.com"))
            session.add(
                GenerationRecord(
                    id=record_id,
                    user_id=user_id,
                    parent_record_id=parent_record_id,
                    subject="social_studies",
                    question_id=payload["id"],
                    params_json={"subject": "social_studies"},
                    question_json=payload,
                    image_files=[],
                )
            )
            await session.commit()

    asyncio.run(insert())
    return user_id, record_id


def _post_modification(app, config, user_id: uuid.UUID, record_id: uuid.UUID, payload: dict):
    token = create_jwt(user_id, "user@example.com", config=config)
    with TestClient(app) as client:
        return client.post(
            f"/api/generation-records/{record_id}/modifications",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )


def _run_count(SessionLocal) -> int:
    async def count() -> int:
        async with SessionLocal() as session:
            return int((await session.execute(select(func.count(GenerationLog.id)))).scalar_one())

    return asyncio.run(count())


def test_stale_quoted_text_is_rejected_before_creating_a_run(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(SessionLocal)

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {
            "annotations": [
                {
                    "segments": [
                        {
                            "field_path": "文本",
                            "start": 0,
                            "end": 5,
                            "quoted_text": "已經不是原文",
                        }
                    ],
                    "修改指示": "請修正這段文字",
                }
            ]
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "stale_base"
    assert "文本" in body["message"]
    assert _run_count(SessionLocal) == 0


def test_segment_offsets_match_frontend_utf16_indices(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(
        SessionLocal,
        question_json={
            "id": "ss-emoji-question",
            "核心問題": "核心問題",
            "文本": "A😀BC",
            "subquestions": [{"題目": "第一題", "答案": "答案"}],
        },
    )

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {
            "annotations": [
                {
                    "segments": [
                        {
                            "field_path": "文本",
                            "start": 3,
                            "end": 4,
                            "quoted_text": "B",
                        }
                    ],
                    "修改指示": "請修正",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert uuid.UUID(response.json()["run_id"])


def test_frozen_field_is_rejected_with_an_actionable_message(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(SessionLocal)

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {
            "annotations": [
                {
                    "segments": [
                        {
                            "field_path": "核心問題",
                            "start": 0,
                            "end": 4,
                            "quoted_text": "核心問題",
                        }
                    ],
                    "修改指示": "請換一個核心問題",
                }
            ]
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "frozen_field"
    assert "核心問題" in body["message"]
    assert "regenerate" in body["message"] or "request" in body["message"]
    assert _run_count(SessionLocal) == 0


@pytest.mark.parametrize(
    "segments",
    [
        pytest.param([], id="no-segments"),
        pytest.param(
            [
                {
                    "field_path": "文本",
                    "start": 0,
                    "end": 1,
                    "quoted_text": "   ",
                }
            ],
            id="chrome-only-quote",
        ),
    ],
)
def test_empty_or_chrome_only_annotation_is_rejected(app_ctx, segments) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(SessionLocal)

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {
            "annotations": [{"segments": segments, "修改指示": "請修正"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "empty_annotation"
    assert _run_count(SessionLocal) == 0


@pytest.mark.parametrize(
    "instruction",
    [pytest.param(None, id="missing"), pytest.param("   ", id="blank")],
)
def test_annotation_without_modification_instruction_is_rejected(app_ctx, instruction) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(SessionLocal)
    annotation = {
        "segments": [
            {
                "field_path": "文本",
                "start": 0,
                "end": 2,
                "quoted_text": "這是",
            }
        ]
    }
    if instruction is not None:
        annotation["修改指示"] = instruction

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {"annotations": [annotation]},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "missing_instruction"
    assert _run_count(SessionLocal) == 0


def test_record_not_owned_by_caller_is_hidden_as_structured_not_found(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    owner_id, record_id = _seed_record(SessionLocal)
    other_id = uuid.uuid4()

    async def insert_other_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=other_id, email="other@example.com"))
            await session.commit()

    asyncio.run(insert_other_user())

    response = _post_modification(
        app,
        config,
        other_id,
        record_id,
        {
            "annotations": [
                {
                    "segments": [
                        {
                            "field_path": "文本",
                            "start": 0,
                            "end": 2,
                            "quoted_text": "這是",
                        }
                    ],
                    "修改指示": "請修正",
                }
            ]
        },
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "not_found"
    assert body["message"] == "Not found"
    assert owner_id != other_id
    assert _run_count(SessionLocal) == 0


def test_parent_record_with_a_child_is_rejected_as_not_latest(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id, parent_id = _seed_record(SessionLocal)
    child_id = uuid.uuid4()

    async def insert_child() -> None:
        async with SessionLocal() as session:
            session.add(
                GenerationRecord(
                    id=child_id,
                    user_id=user_id,
                    parent_record_id=parent_id,
                    subject="social_studies",
                    question_id="ss-question-2",
                    params_json={"subject": "social_studies"},
                    question_json={"id": "ss-question-2", "文本": "新版文本"},
                    image_files=[],
                )
            )
            await session.commit()

    asyncio.run(insert_child())

    response = _post_modification(
        app,
        config,
        user_id,
        parent_id,
        {
            "annotations": [
                {
                    "segments": [
                        {
                            "field_path": "文本",
                            "start": 0,
                            "end": 2,
                            "quoted_text": "這是",
                        }
                    ],
                    "修改指示": "請修正",
                }
            ]
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "not_latest"
    assert "latest" in body["message"]
    assert _run_count(SessionLocal) == 0


def test_active_run_on_record_is_rejected_as_run_in_progress(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(SessionLocal)
    active_run_id = uuid.uuid4()

    async def insert_active_run() -> None:
        async with SessionLocal() as session:
            session.add(
                GenerationLog(
                    id=active_run_id,
                    user_id=user_id,
                    params_json={
                        "kind": "manual_modification",
                        "record_id": str(record_id),
                    },
                    status="started",
                    question_id=str(record_id),
                )
            )
            await session.commit()

    asyncio.run(insert_active_run())

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {
            "annotations": [
                {
                    "segments": [
                        {
                            "field_path": "文本",
                            "start": 0,
                            "end": 2,
                            "quoted_text": "這是",
                        }
                    ],
                    "修改指示": "請修正",
                }
            ]
        },
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "run_in_progress"
    assert "active" in body["message"]
    assert _run_count(SessionLocal) == 1


def test_valid_batch_returns_and_persists_a_started_run(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(SessionLocal)

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {
            "annotations": [
                {
                    "segments": [
                        {
                            "field_path": "文本",
                            "start": 0,
                            "end": 2,
                            "quoted_text": "這是",
                        },
                        {
                            "field_path": "subquestions[0].題目",
                            "start": 0,
                            "end": 6,
                            "quoted_text": "第一小題題目",
                        },
                    ],
                    "修改指示": "請讓這兩段更清楚。",
                }
            ]
        },
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert uuid.UUID(run_id)

    async def read_run() -> GenerationLog | None:
        async with SessionLocal() as session:
            return (
                await session.execute(
                    select(GenerationLog).where(GenerationLog.id == uuid.UUID(run_id))
                )
            ).scalar_one_or_none()

    run = asyncio.run(read_run())
    assert run is not None
    assert run.status == "started"
    assert run.question_id == str(record_id)
    assert run.params_json["kind"] == "manual_modification"
    assert len(run.params_json["annotations"]) == 1


def test_annotation_accepts_the_domain_圈選_key(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(SessionLocal)

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {
            "annotations": [
                {
                    "圈選": [
                        {
                            "field_path": "文本",
                            "start": 0,
                            "end": 2,
                            "quoted_text": "這是",
                        }
                    ],
                    "修改指示": "請修正",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert uuid.UUID(response.json()["run_id"])


def test_compact_domain_annotation_batch_is_accepted(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(SessionLocal)

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {
            "圈選": [
                {
                    "field_path": "文本",
                    "start": 0,
                    "end": 2,
                    "quoted_text": "這是",
                }
            ],
            "修改指示": "請修正",
        },
    )

    assert response.status_code == 200
    assert uuid.UUID(response.json()["run_id"])


def test_one_invalid_annotation_rejects_the_entire_batch_atomically(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id, record_id = _seed_record(SessionLocal)

    response = _post_modification(
        app,
        config,
        user_id,
        record_id,
        {
            "annotations": [
                {
                    "segments": [
                        {
                            "field_path": "文本",
                            "start": 0,
                            "end": 2,
                            "quoted_text": "這是",
                        }
                    ],
                    "修改指示": "請修正第一段",
                },
                {
                    "segments": [
                        {
                            "field_path": "subquestions[0].題目",
                            "start": 0,
                            "end": 4,
                            "quoted_text": "過期的小題",
                        }
                    ],
                    "修改指示": "請修正第二段",
                },
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "stale_base"
    assert _run_count(SessionLocal) == 0


def _full_social_studies_question() -> dict:
    from src.social_studies.schemas import (
        ExamQuestion,
        ImageSpec,
        QuestionContext,
        QuestionSetType,
        QuestionType,
        ReadingProcess,
        RubricEntry,
        SubQuestion,
        TextForm,
    )

    question = ExamQuestion(
        id="ss-manual-modification",
        核心問題="原始核心問題",
        文本="原始文本",
        取材來源=["原始來源"],
        情境=[next(iter(QuestionContext))],
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        閱讀歷程=[next(iter(ReadingProcess))],
        文本形式=next(iter(TextForm)),
        subquestions=[
            SubQuestion(
                id="sq-1",
                序號=1,
                年級=8,
                題型=next(iter(QuestionType)),
                題目="第一小題原題目",
                答案="第一小題原答案",
                答案解析="第一小題原解析",
                出題概念="第一小題原概念",
                評分規準=[
                    RubricEntry(code="1", 規準說明="第一小題原規準")
                ],
            ),
            SubQuestion(
                id="sq-2",
                序號=2,
                年級=8,
                題型=next(iter(QuestionType)),
                題目="第二小題原題目",
                答案="第二小題原答案",
                答案解析="第二小題原解析",
                出題概念="第二小題原概念",
            ),
        ],
        chart_spec=ImageSpec(
            title="原始圖表標題",
            description="原始圖表說明",
            data={"values": [1, 2]},
            labels={"x": "原始標籤"},
        ),
    )
    return json.loads(question.model_dump_json(exclude_none=True))


class _ScriptedModificationLLM:
    """Route-seam fake that returns one whole-question correction candidate."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = 0
        self.prompts: list[tuple[str, str]] = []
        self._observer = None

    def set_observer(self, observer) -> None:
        self._observer = observer

    def generate_json(self, system: str, user: str, **_kwargs):
        self.calls += 1
        self.prompts.append((system, user))
        if self._observer is not None:
            self._observer(
                {
                    "type": "llm_request",
                    "agent": "corrector",
                    "purpose": "correct",
                    "model": "scripted-fake",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "params": {"max_tokens": 8192},
                }
            )
        response = copy.deepcopy(self.response)
        if self._observer is not None:
            self._observer(
                {
                    "type": "llm_response",
                    "agent": "corrector",
                    "purpose": "correct",
                    "model": "scripted-fake",
                    "content": json.dumps(response, ensure_ascii=False),
                    "reasoning": None,
                    "usage": {"input": 10, "output": 20},
                }
            )
        return response


def _modification_payload() -> dict:
    return {
        "annotations": [
            {
                "segments": [
                    {
                        "field_path": "文本",
                        "start": 0,
                        "end": 4,
                        "quoted_text": "原始文本",
                    }
                ],
                "修改指示": "請將文本改成修正文本",
            },
            {
                "segments": [
                    {
                        "field_path": "chart_spec.description",
                        "start": 0,
                        "end": 6,
                        "quoted_text": "原始圖表說明",
                    }
                ],
                "修改指示": "請更新圖表說明",
            },
        ]
    }


def _scripted_candidate(base: dict) -> dict:
    candidate = copy.deepcopy(base)
    candidate["文本"] = "修正文本"
    # Deliberate out-of-scope mutations: the route must restore these.
    candidate["核心問題"] = "未授權核心問題"
    candidate["取材來源"] = ["未授權來源"]
    candidate["subquestions"][0]["出題概念"] = "未授權概念"
    candidate["subquestions"][1]["題目"] = "未授權第二小題"
    # These are dependent on 文本 and therefore are in scope.
    candidate["subquestions"][0]["答案"] = "修正後第一答案"
    candidate["subquestions"][0]["答案解析"] = "修正後第一解析"
    candidate["subquestions"][0]["評分規準"] = [
        {"code": "1", "規準說明": "修正後第一規準", "學生作答實例": []}
    ]
    candidate["chart_spec"]["description"] = "修正圖表說明"
    return candidate


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


def _execute_scripted_modification(app, config, user_id, record_id, fake) -> tuple[str, list[dict]]:

    token = create_jwt(user_id, "user@example.com", config=config)
    with TestClient(app) as client:
        response = client.post(
            f"/api/generation-records/{record_id}/modifications",
            json=_modification_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        stream = client.get(
            f"/api/generation-records/{record_id}/modifications/{run_id}/stream",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert stream.status_code == 200, stream.text
    assert stream.headers["content-type"].startswith("text/event-stream")
    return run_id, _parse_sse_events(stream.text)


def test_modification_stream_emits_modification_step_and_final_ripple_report(
    app_ctx, monkeypatch
) -> None:
    app, SessionLocal, config = app_ctx
    base = _full_social_studies_question()
    user_id, record_id = _seed_record(SessionLocal, question_json=base)
    fake = _ScriptedModificationLLM(_scripted_candidate(base))

    from server.generate import modification_routes as mod_routes

    monkeypatch.setattr(mod_routes, "LLMClient", lambda _config: fake, raising=False)
    run_id, events = _execute_scripted_modification(
        app, config, user_id, record_id, fake
    )

    assert fake.calls == 1
    assert "圈選 1" in fake.prompts[0][1]
    assert "文本[0:4]" in fake.prompts[0][1]
    assert "請將文本改成修正文本" in fake.prompts[0][1]
    assert any(
        event["event"] == "pipeline"
        and event["data"].get("stage") == "modification"
        for event in events
    )
    final = next(event for event in events if event["event"] == "result")
    assert final["data"]["question"]["文本"] == "修正文本"
    assert "subquestions[0].答案" in final["data"]["ripple_report"]
    assert uuid.UUID(run_id)


def test_modification_stream_restores_out_of_scope_fields_server_side(app_ctx, monkeypatch) -> None:
    app, SessionLocal, config = app_ctx
    base = _full_social_studies_question()
    user_id, record_id = _seed_record(SessionLocal, question_json=base)
    fake = _ScriptedModificationLLM(_scripted_candidate(base))

    from server.generate import modification_routes as mod_routes

    monkeypatch.setattr(mod_routes, "LLMClient", lambda _config: fake, raising=False)
    _run_id, events = _execute_scripted_modification(
        app, config, user_id, record_id, fake
    )
    result = next(event for event in events if event["event"] == "result")["data"]["question"]

    assert result["核心問題"] == base["核心問題"]
    assert result["取材來源"] == base["取材來源"]
    assert result["subquestions"][0]["出題概念"] == base["subquestions"][0]["出題概念"]
    assert result["subquestions"][1]["題目"] == base["subquestions"][1]["題目"]


def test_modification_stream_appends_child_and_leaves_parent_immutable(
    app_ctx, monkeypatch
) -> None:
    app, SessionLocal, config = app_ctx
    base = _full_social_studies_question()
    user_id, record_id = _seed_record(SessionLocal, question_json=base)
    fake = _ScriptedModificationLLM(_scripted_candidate(base))

    from server.generate import modification_routes as mod_routes

    monkeypatch.setattr(mod_routes, "LLMClient", lambda _config: fake, raising=False)
    run_id, _events = _execute_scripted_modification(
        app, config, user_id, record_id, fake
    )

    async def read_records() -> list[GenerationRecord]:
        async with SessionLocal() as session:
            return list(
                (
                    await session.execute(
                        select(GenerationRecord).order_by(GenerationRecord.created_at)
                    )
                ).scalars()
            )

    records = asyncio.run(read_records())
    assert len(records) == 2
    parent, child = records
    assert parent.id == record_id
    assert parent.question_json == base
    assert child.parent_record_id == record_id
    assert child.generation_log_id == uuid.UUID(run_id)
    assert child.annotations_json == _modification_payload()


def test_modification_stream_logs_exchange_under_its_own_generation_log(
    app_ctx, monkeypatch
) -> None:
    app, SessionLocal, config = app_ctx
    base = _full_social_studies_question()
    user_id, record_id = _seed_record(SessionLocal, question_json=base)
    fake = _ScriptedModificationLLM(_scripted_candidate(base))

    from server.generate import modification_routes as mod_routes

    monkeypatch.setattr(mod_routes, "LLMClient", lambda _config: fake, raising=False)
    run_id, _events = _execute_scripted_modification(
        app, config, user_id, record_id, fake
    )

    async def read_exchanges() -> list[LLMExchange]:
        async with SessionLocal() as session:
            return list(
                (
                    await session.execute(
                        select(LLMExchange).where(
                            LLMExchange.generation_log_id == uuid.UUID(run_id)
                        )
                    )
                ).scalars()
            )

    exchanges = asyncio.run(read_exchanges())
    assert len(exchanges) == 1
    assert exchanges[0].agent == "corrector"
    assert exchanges[0].purpose == "correct"
    assert exchanges[0].generation_log_id == uuid.UUID(run_id)


def test_modification_stream_allows_chart_spec_edits(app_ctx, monkeypatch) -> None:
    app, SessionLocal, config = app_ctx
    base = _full_social_studies_question()
    user_id, record_id = _seed_record(SessionLocal, question_json=base)
    fake = _ScriptedModificationLLM(_scripted_candidate(base))

    from server.generate import modification_routes as mod_routes

    monkeypatch.setattr(mod_routes, "LLMClient", lambda _config: fake, raising=False)
    _run_id, events = _execute_scripted_modification(
        app, config, user_id, record_id, fake
    )
    result = next(event for event in events if event["event"] == "result")["data"]["question"]

    assert result["chart_spec"]["description"] == "修正圖表說明"
    assert result["chart_spec"]["title"] == base["chart_spec"]["title"]
