"""Server-level tests for issue #940: LLM_FABLE_DOWNGRADE admission guard.

Task 4.1 requirements:
- GET /api/models returns the same entries in the same order with the switch on.
- A generation request naming claude-fable-5 with effort xhigh is admitted
  without HTTP 422 when LLM_FABLE_DOWNGRADE=1 (admission uses the requested
  model; dispatch happens at call time, after admission).
"""

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
from server.config import _DEFAULT_MODELS_ALLOWED, ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params


def _make_app_and_token(fable_downgrade: bool = False) -> tuple:
    """Create a TestClient app + JWT token with the given fable_downgrade setting."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        gemini_api_key="x",
        fable_downgrade=fable_downgrade,
        # Use the default roster which includes claude-fable-5.
        llm_models_allowed=_DEFAULT_MODELS_ALLOWED,
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
# 1. GET /api/models — same entries and order with switch on vs. off
# ---------------------------------------------------------------------------


def test_models_endpoint_same_allowed_list_with_fable_downgrade_on() -> None:
    """GET /api/models returns the same allowed list regardless of fable_downgrade."""
    app_on, _tok_on, engine_on, _cfg_on = _make_app_and_token(fable_downgrade=True)
    app_off, _tok_off, engine_off, _cfg_off = _make_app_and_token(fable_downgrade=False)
    try:
        with TestClient(app_on) as client_on:
            r_on = client_on.get("/api/models")
        with TestClient(app_off) as client_off:
            r_off = client_off.get("/api/models")
    finally:
        limiter.reset()
        asyncio.run(engine_on.dispose())
        asyncio.run(engine_off.dispose())

    assert r_on.status_code == 200
    assert r_off.status_code == 200
    body_on = r_on.json()
    body_off = r_off.json()
    # Same allowed list, same order.
    assert body_on["allowed"] == body_off["allowed"]
    # claude-fable-5 is present in both.
    assert "claude-fable-5" in body_on["allowed"]


def test_models_endpoint_includes_fable_effort_roster_when_downgrade_on() -> None:
    """claude-fable-5 still has its 5-level roster (including xhigh) with switch on.

    Admission reads the roster from EFFORT_LEVELS; the switch does not affect it.
    """
    from server.config import _EFFORT_LEVELS

    app, _tok, engine, _cfg = _make_app_and_token(fable_downgrade=True)
    try:
        with TestClient(app) as client:
            r = client.get("/api/models")
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    effort_map = r.json()["effort"]
    assert "claude-fable-5" in effort_map
    expected = _EFFORT_LEVELS.get("claude-fable-5", ["low", "medium", "high", "max"])
    assert effort_map["claude-fable-5"] == expected
    assert "xhigh" in effort_map["claude-fable-5"]


# ---------------------------------------------------------------------------
# 2. Generation admission: claude-fable-5 + effort xhigh admitted (no 422)
# ---------------------------------------------------------------------------


def test_fable_with_xhigh_effort_admitted_when_downgrade_on() -> None:
    """A request naming claude-fable-5 + effort_execute=xhigh passes admission.

    With LLM_FABLE_DOWNGRADE=1 the route must NOT return 422 — admission
    validates against the requested model's roster (xhigh is valid for fable-5),
    and dispatch to claude-opus-4-6 happens at call time.

    Under the detached-run architecture (#929), GET /api/generate returns 202
    immediately on acceptance; no stream is emitted on the wire.
    """
    app, token, engine, _cfg = _make_app_and_token(fable_downgrade=True)

    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/generate",
                params=complete_math_query_params(
                    model_execute="claude-fable-5",
                    effort_execute="xhigh",
                ),
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    # Must not be 422 (admission failure).
    assert r.status_code != 422, (
        f"Expected admission to pass for claude-fable-5 + xhigh, got 422. "
        f"Body: {r.text}"
    )
    # Detached-run acceptance returns 202.
    assert r.status_code == 202


def test_fable_with_xhigh_effort_admitted_when_downgrade_off() -> None:
    """Baseline: fable-5 + xhigh is also admitted with switch off (roster unchanged).

    Under the detached-run architecture (#929), GET /api/generate returns 202
    immediately on acceptance; no stream is emitted on the wire.
    """
    app, token, engine, _cfg = _make_app_and_token(fable_downgrade=False)

    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/generate",
                params=complete_math_query_params(
                    model_execute="claude-fable-5",
                    effort_execute="xhigh",
                ),
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code != 422
    # Detached-run acceptance returns 202.
    assert r.status_code == 202
