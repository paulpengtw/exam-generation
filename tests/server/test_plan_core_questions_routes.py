"""Tests for POST /api/plan-core-questions endpoint."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter


def _make_app_and_token():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    token = create_jwt(user_id, "u@example.com", config=config)
    return app, token, engine


def test_plan_core_questions_math_happy_path(monkeypatch) -> None:
    app, token, engine = _make_app_and_token()

    import src.common.planner as common_planner

    def fake_plan_core_questions(client, topic, **kwargs):
        return ["核心問題一", "核心問題二", "核心問題三"]

    monkeypatch.setattr(
        "src.planner.plan_core_questions",
        fake_plan_core_questions,
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "微積分", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    data = response.json()
    assert data["candidates"] == ["核心問題一", "核心問題二", "核心問題三"]


def test_plan_core_questions_math_malformed_then_retry(monkeypatch) -> None:
    """Planner raises ValueError once (retry appends reminder), succeeds on second call."""
    app, token, engine = _make_app_and_token()

    call_count = 0
    original_plan = None

    import src.llm_client as llm_module

    def fake_plan(self, system, user, *, purpose):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First attempt: bad output that fails parsing
            return "這不是 JSON"
        # Second attempt should have reminder appended to user prompt
        assert "注意：請務必輸出剛好" in user
        return '["核心問題一", "核心問題二", "核心問題三"]'

    monkeypatch.setattr(llm_module.LLMClient, "plan", fake_plan)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "統計", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert response.json()["candidates"] == ["核心問題一", "核心問題二", "核心問題三"]
    assert call_count == 2


def test_plan_core_questions_math_both_attempts_fail_returns_502(monkeypatch) -> None:
    """When both retry attempts return malformed output, endpoint returns 502."""
    app, token, engine = _make_app_and_token()

    import src.llm_client as llm_module

    def fake_plan(self, system, user, *, purpose):
        return "not valid json at all"

    monkeypatch.setattr(llm_module.LLMClient, "plan", fake_plan)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "幾何", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 502
    assert "malformed" in response.json()["detail"].lower()


def test_plan_core_questions_defaults_to_social_studies(monkeypatch) -> None:
    """subject defaults to social_studies when not specified."""
    app, token, engine = _make_app_and_token()

    captured = {}

    def fake_ss_plan(client, topic, **kwargs):
        captured["subject"] = "social_studies"
        captured["topic"] = topic
        return ["問題一", "問題二", "問題三"]

    monkeypatch.setattr(
        "src.social_studies.planner.plan_core_questions",
        fake_ss_plan,
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "民主政治"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured.get("subject") == "social_studies"
    assert captured.get("topic") == "民主政治"
