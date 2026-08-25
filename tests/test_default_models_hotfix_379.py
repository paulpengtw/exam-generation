"""Specification tests for hotfix #379 — assert that ``claude-sonnet-4-6`` is the
code-level default plan and execute model for both ``src.config.Config`` and
``server.config.ServerConfig``.  Environment variables and per-request overrides
still take precedence, and ``claude-opus-5`` remains selectable.

Issue: https://github.com/paulpengtw/exam-generation/issues/379
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest import mock

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.config
import src.config
from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter


def test_src_config_defaults_to_sonnet_4_6_when_env_unset(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = src.config.Config.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.model_plan == "claude-sonnet-4-6"
    assert cfg.model_execute == "claude-sonnet-4-6"


def test_server_config_defaults_to_sonnet_4_6_when_env_unset(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = server.config.ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.model_plan == "claude-sonnet-4-6"
    assert cfg.model_execute == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Shared setup helper for authenticated endpoint tests.
# ---------------------------------------------------------------------------


def _make_authed_app() -> tuple:
    """Set up an in-memory DB + ServerConfig + JWT token for authenticated route tests.

    Config defaults: model_plan/execute = claude-sonnet-4-6 (via dataclass default).
    Allowed list: claude-sonnet-4-6 and claude-opus-5.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    cfg = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        gemini_api_key="x",
        llm_models_allowed=("claude-sonnet-4-6", "claude-opus-5"),
    )
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: cfg
    limiter.reset()

    token = create_jwt(user_id, "u@example.com", config=cfg)
    return app, token, engine


# ---------------------------------------------------------------------------
# Regression guard: explicit LLM_MODEL_PLAN env var wins over the code default.
# ---------------------------------------------------------------------------


def test_explicit_env_model_plan_still_wins_over_default(tmp_path: Path) -> None:
    """LLM_MODEL_PLAN from the environment must override the claude-sonnet-4-6
    code default for both Config and ServerConfig.  Regression guard for
    pinned deploys."""
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s", "LLM_MODEL_PLAN": "claude-opus-5"}
    with mock.patch.dict(os.environ, env, clear=True):
        src_cfg = src.config.Config.from_env(env_file=tmp_path / ".env.missing")
        srv_cfg = server.config.ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert src_cfg.model_plan == "claude-opus-5"
    assert srv_cfg.model_plan == "claude-opus-5"


# ---------------------------------------------------------------------------
# GET /api/models reports the new default and preserves the full allowed-model roster.
# ---------------------------------------------------------------------------


def test_models_endpoint_reports_sonnet_default_and_keeps_opus_and_gemini_allowed(
    tmp_path: Path,
) -> None:
    """GET /api/models on a fresh (env-less) config must:
    - Report claude-sonnet-4-6 as both plan and execute default.
    - Include claude-opus-5 and gemini-3.1-pro-preview in the allowed list.
    - Have claude-sonnet-4-6 as the FIRST entry (ordering requirement, issue #379).
    - Report the correct 4-level effort roster for claude-sonnet-4-6 (no xhigh)."""
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "test-secret"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = server.config.ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    app = create_app()
    app.dependency_overrides[get_config] = lambda: cfg
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["defaults"]["plan"] == "claude-sonnet-4-6"
    assert body["defaults"]["execute"] == "claude-sonnet-4-6"
    assert "claude-opus-5" in body["allowed"]
    assert "gemini-3.1-pro-preview" in body["allowed"]
    # ParamForm.tsx renders models.allowed in roster order; default must head the list
    assert body["allowed"][0] == "claude-sonnet-4-6"
    assert body["effort"]["claude-sonnet-4-6"] == ["low", "medium", "high", "max"]


# ---------------------------------------------------------------------------
# xhigh is rejected for the default plan model when no model_plan override is in the request body.
# ---------------------------------------------------------------------------


def test_plan_core_questions_rejects_effort_plan_xhigh_against_default_model() -> None:
    """With the new default plan model (claude-sonnet-4-6) and NO model_plan
    override in the request body, effort_plan=xhigh must be rejected with 422.
    This pins the existing reject (not degrade) contract under the new default."""
    app, token, engine = _make_authed_app()
    try:
        with TestClient(app) as client:
            r = client.post(
                "/api/plan-core-questions",
                json={"topic": "民主政治", "effort_plan": "xhigh"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Per-request model_plan override wins over the config default; claude-opus-5 remains allowed.
# ---------------------------------------------------------------------------


def test_per_request_model_plan_override_beats_config_and_opus_still_allowed(
    monkeypatch,
) -> None:
    """A per-request model_plan=claude-opus-5 must override the config default
    (claude-sonnet-4-6), pass the allowlist check, and reach the planner with
    the requested model."""
    app, token, engine = _make_authed_app()
    captured: dict = {}

    def fake_ss_plan(client, topic, **kwargs):
        captured["model_plan"] = client.config.model_plan
        return ["問題一", "問題二", "問題三"]

    monkeypatch.setattr("src.social_studies.planner.plan_core_questions", fake_ss_plan)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "民主政治", "model_plan": "claude-opus-5"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["model_plan"] == "claude-opus-5"
