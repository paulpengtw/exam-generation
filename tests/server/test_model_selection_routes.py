"""Route-level tests for the model_plan / model_execute overrides (#105)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter


def _make_app_and_token(allowed: tuple[str, ...] = ()):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    if not allowed:
        allowed = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5", "claude-sonnet-4-6", "claude-opus-4-6")
    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        llm_models_allowed=allowed,
    )
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
    return app, token, engine, config


def test_generate_route_accepts_allowlisted_models_and_forwards_to_params() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6")
    )

    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math"
                "&model_plan=claude-opus-4-6"
                "&model_execute=claude-haiku-4-6",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["params"].model_plan == "claude-opus-4-6"
    assert captured["params"].model_execute == "claude-haiku-4-6"


def test_generate_route_rejects_unlisted_model_execute_with_422() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-opus-4-6", "claude-sonnet-4-6")
    )

    called = {"count": 0}

    async def fake_stream(params, *_args, **_kwargs):
        called["count"] += 1
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math&model_execute=gpt-4o",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "gpt-4o" in detail
    assert "claude-sonnet-4-6" in detail
    assert called["count"] == 0


def test_generate_route_absent_overrides_defaults_to_none() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token()

    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["params"].model_plan is None
    assert captured["params"].model_execute is None


def test_plan_core_questions_route_rejects_unlisted_model_plan_with_422() -> None:
    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-opus-4-6", "claude-sonnet-4-6")
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "民主政治", "model_plan": "gpt-4o"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    assert "gpt-4o" in response.json()["detail"]


def test_plan_core_questions_route_rejects_unlisted_model_execute_with_422() -> None:
    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-opus-4-6", "claude-sonnet-4-6")
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "民主政治", "model_execute": "gpt-4o"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "gpt-4o" in detail
    assert "model_execute" in detail


def test_generate_route_empty_string_model_execute_treated_as_absent() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token()

    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            # Empty string in query param should not trigger 422
            response = client.get(
                "/api/generate?subject=math&model_execute=",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    # Empty string should be treated as absent (not cause allowlist rejection)
    assert response.status_code == 200
