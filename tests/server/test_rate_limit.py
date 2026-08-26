"""Tests for slowapi rate-limiting on magic-link and generate endpoints."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.email import ConsoleEmailSender
from server.auth.routes import _email_sender_dep
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params


def _config() -> ServerConfig:
    return ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        gemini_api_key="x",
        jwt_expire_days=7,
        frontend_url="https://example.com",
        email_backend="console",
    )


@pytest.fixture
def app_ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = _config()
    sender = ConsoleEmailSender(frontend_url="https://example.com")

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    app.dependency_overrides[_email_sender_dep] = lambda: sender

    limiter.reset()
    yield app, SessionLocal, config
    limiter.reset()
    asyncio.run(engine.dispose())


def test_magic_link_rate_limit_returns_429_after_5(app_ctx) -> None:
    app, _, _ = app_ctx
    with TestClient(app) as client:
        for _ in range(5):
            r = client.post("/auth/magic-link", json={"email": "a@example.com"})
            assert r.status_code == 200
        r6 = client.post("/auth/magic-link", json={"email": "a@example.com"})
    assert r6.status_code == 429
    assert "Rate limit exceeded" in r6.json()["detail"]


def test_generate_rate_limit_returns_429_after_10(app_ctx) -> None:
    app, SessionLocal, config = app_ctx
    user_id = uuid.uuid4()

    async def _add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(_add_user())
    token = create_jwt(user_id, "u@example.com", config=config)
    headers = {"Authorization": f"Bearer {token}"}

    # Patch the streamer so requests don't try to call an LLM.
    from server.generate import routes as gen_routes

    async def fake_stream(*_a, **_kw):
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            for _ in range(10):
                r = client.get(
                    "/api/generate",
                    params=complete_math_query_params(),
                    headers=headers,
                )
                assert r.status_code == 200
            r11 = client.get(
                "/api/generate",
                params=complete_math_query_params(),
                headers=headers,
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]

    assert r11.status_code == 429
    assert "Rate limit exceeded" in r11.json()["detail"]
