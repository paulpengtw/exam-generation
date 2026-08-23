"""HTTP contract tests for 人工審題修正 admission."""

from __future__ import annotations

import asyncio
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
from server.models import Base, GenerationLog, GenerationRecord, User
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
