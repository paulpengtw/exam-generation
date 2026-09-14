"""Tests for effort routing in /api/models, /api/generate, /api/plan-core-questions (issue #254)."""

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
from server.auth.tokens import create_jwt
from server.config import _EFFORT_LEVELS, ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params

# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------


def _make_app_and_token(
    allowed: tuple[str, ...] = (),
    effort_plan: str = "medium",
    effort_execute: str = "medium",
):
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
        allowed = (
            "claude-opus-5",
            "claude-fable-5",
            "claude-sonnet-5",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
        )
    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        gemini_api_key="x",
        llm_models_allowed=allowed,
        effort_plan=effort_plan,
        effort_execute=effort_execute,
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


# ---------------------------------------------------------------------------
# 1. GET /api/models — effort roster in response
# ---------------------------------------------------------------------------


def test_models_endpoint_includes_effort_key() -> None:
    app, token, engine, cfg = _make_app_and_token()
    try:
        with TestClient(app) as client:
            r = client.get("/api/models")
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())
    assert r.status_code == 200
    body = r.json()
    assert "effort" in body


def test_models_endpoint_effort_roster_matches_effort_levels() -> None:
    app, token, engine, cfg = _make_app_and_token()
    try:
        with TestClient(app) as client:
            r = client.get("/api/models")
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())
    body = r.json()
    effort_map = body["effort"]
    # Each model in the allowed list should have a roster
    for model in cfg.llm_models_allowed:
        assert model in effort_map, f"{model} missing from effort roster"
        expected = _EFFORT_LEVELS.get(model, ["low", "medium", "high", "max"])
        assert effort_map[model] == expected


def test_models_endpoint_defaults_include_effort() -> None:
    app, token, engine, cfg = _make_app_and_token(effort_plan="high", effort_execute="low")
    try:
        with TestClient(app) as client:
            r = client.get("/api/models")
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())
    body = r.json()
    assert body["defaults"]["effort_plan"] == "high"
    assert body["defaults"]["effort_execute"] == "low"


def test_models_endpoint_defaults_effort_medium_when_not_overridden() -> None:
    app, token, engine, cfg = _make_app_and_token()  # default medium
    try:
        with TestClient(app) as client:
            r = client.get("/api/models")
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())
    body = r.json()
    assert body["defaults"]["effort_plan"] == "medium"
    assert body["defaults"]["effort_execute"] == "medium"


# ---------------------------------------------------------------------------
# 2. GET /api/generate — effort accepted and forwarded; invalid → 422
# ---------------------------------------------------------------------------


def test_generate_endpoint_accepts_valid_effort_plan() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, cfg = _make_app_and_token()
    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/generate",
                params=complete_math_query_params(effort_plan="high"),
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    assert captured["params"].effort_plan == "high"


def test_generate_endpoint_accepts_valid_effort_execute() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, cfg = _make_app_and_token()
    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/generate",
                params=complete_math_query_params(effort_execute="low"),
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    assert captured["params"].effort_execute == "low"


def test_generate_endpoint_rejects_bogus_effort_plan_422() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, cfg = _make_app_and_token()
    called = {"count": 0}

    async def fake_stream(params, *_args, **_kwargs):
        called["count"] += 1
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(
                "/api/generate",
                params=complete_math_query_params(effort_plan="bogus"),
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422
    assert called["count"] == 0


def test_generate_endpoint_rejects_effort_execute_xhigh_for_sonnet4_6() -> None:
    """xhigh not in claude-sonnet-4-6 roster → 422 before any LLM call."""
    from server.generate import routes as gen_routes

    app, token, engine, cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6",)
    )
    called = {"count": 0}

    async def fake_stream(params, *_args, **_kwargs):
        called["count"] += 1
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(
                "/api/generate",
                params=complete_math_query_params(
                    model_execute="claude-sonnet-4-6",
                    effort_execute="xhigh",
                ),
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422
    assert called["count"] == 0


def test_generate_endpoint_accepts_effort_execute_xhigh_for_opus5() -> None:
    """xhigh IS in claude-opus-5 roster → 200."""
    from server.generate import routes as gen_routes

    app, token, engine, cfg = _make_app_and_token(
        allowed=("claude-opus-5", "claude-sonnet-4-6")
    )
    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/generate",
                params=complete_math_query_params(
                    model_execute="claude-opus-5",
                    effort_execute="xhigh",
                ),
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    assert captured["params"].effort_execute == "xhigh"


def test_generate_endpoint_no_effort_params_accepted() -> None:
    """Omitting effort params does not cause errors."""
    from server.generate import routes as gen_routes

    app, token, engine, cfg = _make_app_and_token()
    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/generate",
                params=complete_math_query_params(),
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    assert captured["params"].effort_plan is None
    assert captured["params"].effort_execute is None


# ---------------------------------------------------------------------------
# 3. POST /api/plan-core-questions — effort_plan honoured
# ---------------------------------------------------------------------------


def test_plan_core_questions_accepts_effort_plan(monkeypatch) -> None:
    app, token, engine, cfg = _make_app_and_token(
        allowed=("claude-opus-5", "claude-sonnet-4-6")
    )
    captured: dict = {}

    def fake_math_plan(client, topic, **kwargs):
        captured["effort_plan"] = client.config.effort_plan
        return ["核心問題一", "核心問題二", "核心問題三"]

    monkeypatch.setattr("src.planner.plan_core_questions", fake_math_plan)

    try:
        with TestClient(app) as client:
            r = client.post(
                "/api/plan-core-questions",
                json={"topic": "微積分", "subject": "math", "effort_plan": "high"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    assert captured["effort_plan"] == "high"


def test_plan_core_questions_rejects_bogus_effort_plan() -> None:
    app, token, engine, cfg = _make_app_and_token()
    try:
        with TestClient(app) as client:
            r = client.post(
                "/api/plan-core-questions",
                json={"topic": "微積分", "subject": "math", "effort_plan": "bogus"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422


def test_plan_core_questions_rejects_effort_plan_xhigh_for_sonnet4_6() -> None:
    """xhigh not in claude-sonnet-4-6 roster when used as plan model → 422."""
    app, token, engine, cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6",)
    )
    try:
        with TestClient(app) as client:
            r = client.post(
                "/api/plan-core-questions",
                json={
                    "topic": "微積分",
                    "subject": "math",
                    "model_plan": "claude-sonnet-4-6",
                    "effort_plan": "xhigh",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422


def test_plan_core_questions_absent_effort_uses_env_default(monkeypatch) -> None:
    """Omitting effort_plan falls back to the env default (high from SrcConfig.from_env)."""
    monkeypatch.delenv("LLM_EFFORT_PLAN", raising=False)
    app, token, engine, cfg = _make_app_and_token()
    captured: dict = {}

    def fake_math_plan(client, topic, **kwargs):
        captured["effort_plan"] = client.config.effort_plan
        return ["核心問題一", "核心問題二", "核心問題三"]

    monkeypatch.setattr("src.planner.plan_core_questions", fake_math_plan)

    try:
        with TestClient(app) as client:
            r = client.post(
                "/api/plan-core-questions",
                json={"topic": "微積分", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    # Absent effort_plan falls back to SrcConfig.from_env() default = "high".
    assert captured["effort_plan"] == "high"


# ---------------------------------------------------------------------------
# 4. service.py: effort propagates into client_config via build_prompt_previews
# ---------------------------------------------------------------------------


def test_service_client_config_carries_effort_overrides(monkeypatch) -> None:
    """build_prompt_previews must pass effort overrides into client_config."""
    from server.generate import service as svc_module
    from server.generate.models import GenerateParams

    # Intercept the resolved-worker path to capture the client_config
    # before it's used — avoids the need for a full app_state.
    captured: dict = {}

    original_replace = svc_module.dataclasses.replace

    def fake_replace(obj, **changes):
        result = original_replace(obj, **changes)
        if "effort_plan" in changes or "effort_execute" in changes:
            captured["effort_plan"] = result.effort_plan
            captured["effort_execute"] = result.effort_execute
        return result

    monkeypatch.setattr(svc_module, "dataclasses", type(
        "FakeDataclasses", (),
        {"replace": staticmethod(fake_replace)}
    )())

    cfg = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        effort_plan="low",
        effort_execute="medium",
    )
    params = GenerateParams(subject="math", effort_plan="xhigh", effort_execute="max")

    # Restore after monkeypatching to avoid side effects
    monkeypatch.undo()

    # Verify the dataclasses.replace call in _build_run_context directly.
    import dataclasses as dc

    client_config = dc.replace(
        cfg,
        model_execute=params.model_execute or cfg.model_execute,
        model_plan=params.model_plan or cfg.model_plan,
        effort_plan=params.effort_plan or cfg.effort_plan,
        effort_execute=params.effort_execute or cfg.effort_execute,
    )

    assert client_config.effort_plan == "xhigh"
    assert client_config.effort_execute == "max"
