"""Structured exhausted-slot evidence survives live delivery and History."""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from server.models import Base, GenerationRecord, User
from server.rate_limit import limiter
from tests.server.generate_test_utils import resolved_generate_params
from tests.server.test_937_service_partial_delivery import (
    _FakeClient,
    _shell,
    _subquestion,
)


@pytest.mark.parametrize(
    ("failure_code", "safe_detail", "fallback_reason"),
    [
        (
            "validation_exhausted",
            "第2題 [1] 級距需要 2 個學生作答實例（目前 1 個）",
            None,
        ),
        (
            "provider_failure",
            "provider call raised RuntimeError",
            None,
        ),
        (
            "unknown",
            None,
            "subquestion generation failed",
        ),
    ],
)
def test_exhausted_slot_evidence_matches_live_terminal_and_history(
    failure_code: str,
    safe_detail: str | None,
    fallback_reason: str | None,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "subquestion-failure-history.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", future=True)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    user_id = uuid.uuid4()

    async def initialize() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(User(id=user_id, email="slot-history@example.com"))
            await session.commit()

    asyncio.run(initialize())
    params = resolved_generate_params({
        "subject": "natural_sciences",
        "seed": 978,
        "count": 1,
        "sub_question_count": 3,
        "skip_verify": True,
    })
    config = ServerConfig(
        api_key="x",
        gemini_api_key="x",
        jwt_secret="history-secret",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    app_state = type(
        "AppState",
        (),
        {
            "renderer_pool": None,
            "curriculum": [],
            "performance": {},
            "intro_text": "",
            "grade_content": {},
            "math_curriculum_context": None,
        },
    )()
    def fake_do_generate(rng_params: Any, _overrides: Any, **kwargs: Any) -> Any:
        question_id = kwargs["question_id"]
        client: _FakeClient = kwargs["client"]
        client.emit({
            "type": "plan",
            "agent": "generator",
            "sub_question_total": 3,
            "slots": [
                {
                    "subquestion_index": index,
                    "id": f"{question_id}-sq{index + 1:03d}",
                    "序號": index + 1,
                }
                for index in range(3)
            ],
        })
        failure_event = {
            "type": "stage",
            "agent": "sub_generator#2",
            "stage": "llm_generate",
            "status": "error",
            "code": "subquestion_exhausted",
            "subquestion_index": 1,
            "failure_code": failure_code,
        }
        if safe_detail is not None:
            failure_event["failure_detail"] = safe_detail
        client.emit(failure_event)
        question = _shell("natural_sciences", question_id, rng_params)
        question.subquestions = [
            _subquestion("natural_sciences", question_id, slot, rng_params)
            for slot in (1, 3)
        ]
        return question

    spec = dataclasses.replace(
        SUBJECTS["natural_sciences"],
        do_generate=fake_do_generate,
    )

    async def run_generation() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in generate_question_stream(
            params,
            config,
            app_state,
            user_id=user_id,
            subjects={"natural_sciences": spec},
            session_factory=session_factory,
            client_factory=_FakeClient,
        ):
            events.append(event)
        return events

    with patch("server.observability.record_generation_outcome"):
        events = asyncio.run(run_generation())

    terminal = next(
        event for event in events if event["event"] == "question_terminal"
    )
    live_missing = terminal["payload"]["missing"]
    expected_missing = {
        "kind": "subquestion",
        "question_id": terminal["context"]["question_id"],
        "subquestion_id": f"{terminal['context']['question_id']}-sq002",
        "subquestion_index": 1,
        "reason": safe_detail or fallback_reason,
        "failure_code": failure_code,
    }
    if safe_detail is not None:
        expected_missing["failure_detail"] = safe_detail
    assert live_missing == [expected_missing]

    async def record_id() -> uuid.UUID:
        async with session_factory() as session:
            result = await session.execute(
                select(GenerationRecord).where(GenerationRecord.user_id == user_id)
            )
            return result.scalar_one().id

    persisted_id = asyncio.run(record_id())

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    token = create_jwt(user_id, "slot-history@example.com", config=config)
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/history/{persisted_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        history_delivery = response.json()["terminal_delivery"]
        assert history_delivery["delivery_status"] == "partial"
        assert history_delivery["termination_reason"] == "normal"
        assert history_delivery["missing"] == live_missing
        if safe_detail is not None:
            assert "\n" not in history_delivery["missing"][0]["failure_detail"]
            assert len(history_delivery["missing"][0]["failure_detail"]) <= 240
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())
