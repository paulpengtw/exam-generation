"""Tests for effort_verify / effort_correct per-tier effort routing (issue #377).

Written test-first (TDD): each slice is RED before its implementation lands.

Run:
    export PATH="$HOME/.local/bin:$PATH" && uv run pytest tests/server/test_effort_tier_routes.py -v
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

# ── Slice 1: Config defaults and env vars ─────────────────────────────────────

from src.config import Config
from server.config import ServerConfig


def test_src_config_effort_verify_default_empty() -> None:
    """effort_verify must default to '' (empty), signalling 'inherit effort_execute'."""
    assert Config().effort_verify == ""


def test_src_config_effort_correct_default_empty() -> None:
    """effort_correct must default to '' (empty)."""
    assert Config().effort_correct == ""


def test_src_config_effort_verify_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_EFFORT_VERIFY", "high")
    monkeypatch.delenv("LLM_EFFORT_CORRECT", raising=False)
    cfg = Config.from_env()
    assert cfg.effort_verify == "high"


def test_src_config_effort_correct_from_env(monkeypatch) -> None:
    monkeypatch.delenv("LLM_EFFORT_VERIFY", raising=False)
    monkeypatch.setenv("LLM_EFFORT_CORRECT", "max")
    cfg = Config.from_env()
    assert cfg.effort_correct == "max"


def test_server_config_effort_verify_default_empty() -> None:
    """ServerConfig must also expose effort_verify with empty default."""
    cfg = ServerConfig(api_key="x", jwt_secret="s")
    assert cfg.effort_verify == ""


def test_server_config_effort_correct_default_empty() -> None:
    """ServerConfig must also expose effort_correct with empty default."""
    cfg = ServerConfig(api_key="x", jwt_secret="s")
    assert cfg.effort_correct == ""


def test_server_config_effort_verify_from_env(tmp_path) -> None:
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s", "LLM_EFFORT_VERIFY": "high"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.effort_verify == "high"


def test_server_config_effort_correct_from_env(tmp_path) -> None:
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s", "LLM_EFFORT_CORRECT": "max"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.effort_correct == "max"


# ── Slice 2: Client resolution (_effort_for_purpose) ─────────────────────────

from src.llm_client import LLMClient


class _FakeMessagesAPI:
    """Records Anthropic messages.create() without hitting the network."""

    def __init__(self, response_text: str = '{"ok": true}') -> None:
        self.calls: list[dict] = []
        self._response_text = response_text

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content_block = SimpleNamespace(text=self._response_text)
        usage = SimpleNamespace(
            input_tokens=1,
            output_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return SimpleNamespace(
            content=[content_block],
            stop_reason="end_turn",
            usage=usage,
        )


def _make_tier_effort_client(
    effort_plan: str = "medium",
    effort_execute: str = "medium",
    effort_verify: str = "",
    effort_correct: str = "",
    model_execute: str = "claude-opus-5",
    model_verify: str = "",
    model_correct: str = "",
) -> tuple[LLMClient, _FakeMessagesAPI]:
    cfg = Config(
        api_key="x",
        llm_stream=False,
        model_execute=model_execute,
        model_verify=model_verify,
        model_correct=model_correct,
        effort_plan=effort_plan,
        effort_execute=effort_execute,
        effort_verify=effort_verify,
        effort_correct=effort_correct,
    )
    client = LLMClient(cfg)
    fake = _FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)
    return client, fake


def _effort_from_call(call: dict) -> str | None:
    return call.get("extra_body", {}).get("output_config", {}).get("effort")


def test_verify_purpose_uses_effort_verify_when_set() -> None:
    """When effort_verify is set, verify calls must use it, not effort_execute."""
    client, fake = _make_tier_effort_client(
        effort_execute="medium",
        effort_verify="high",
    )
    client.generate("sys", "user", purpose="verify")
    assert len(fake.calls) == 1
    assert _effort_from_call(fake.calls[0]) == "high"


def test_correct_purpose_uses_effort_correct_when_set() -> None:
    """When effort_correct is set, correct calls must use it, not effort_execute."""
    client, fake = _make_tier_effort_client(
        effort_execute="medium",
        effort_correct="max",
    )
    client.generate("sys", "user", purpose="correct")
    assert len(fake.calls) == 1
    assert _effort_from_call(fake.calls[0]) == "max"


def test_verify_purpose_falls_back_to_effort_execute_when_unset() -> None:
    """When effort_verify is '' (unset), verify calls use effort_execute."""
    client, fake = _make_tier_effort_client(
        effort_execute="high",
        effort_verify="",
    )
    client.generate("sys", "user", purpose="verify")
    assert _effort_from_call(fake.calls[0]) == "high"


def test_correct_purpose_falls_back_to_effort_execute_when_unset() -> None:
    """When effort_correct is '' (unset), correct calls use effort_execute."""
    client, fake = _make_tier_effort_client(
        effort_execute="high",
        effort_correct="",
    )
    client.generate("sys", "user", purpose="correct")
    assert _effort_from_call(fake.calls[0]) == "high"


def test_generate_purpose_still_uses_effort_execute() -> None:
    client, fake = _make_tier_effort_client(
        effort_execute="max",
        effort_verify="low",
        effort_correct="low",
    )
    client.generate("sys", "user", purpose="generate")
    assert _effort_from_call(fake.calls[0]) == "max"


def test_html_image_purpose_uses_effort_execute() -> None:
    client, fake = _make_tier_effort_client(
        effort_execute="max",
        effort_verify="low",
        effort_correct="low",
    )
    client.generate("sys", "user", purpose="html_image")
    assert _effort_from_call(fake.calls[0]) == "max"


def test_fact_check_purpose_uses_effort_execute() -> None:
    client, fake = _make_tier_effort_client(
        effort_execute="high",
        effort_verify="low",
        effort_correct="low",
    )
    client.generate("sys", "user", purpose="fact_check")
    assert _effort_from_call(fake.calls[0]) == "high"


def test_plan_purpose_still_uses_effort_plan() -> None:
    """plan purposes must continue to use effort_plan, not effort_verify/correct."""
    client, fake = _make_tier_effort_client(
        effort_plan="xhigh",
        effort_execute="low",
        effort_verify="medium",
    )
    client.generate("sys", "user", purpose="plan_core_questions")
    assert _effort_from_call(fake.calls[0]) == "xhigh"


# ── Slice 3: Inheritance chaining pin ────────────────────────────────────────


def test_verify_effort_uses_overridden_execute_when_unset() -> None:
    """Per-request effort_execute override with effort_verify unset → verify uses
    the OVERRIDDEN execute effort, not the env-time one.

    This mirrors the model tier chaining test in test_model_tiers_verify_correct.py.
    """
    base_cfg = Config(
        api_key="x",
        llm_stream=False,
        model_execute="claude-opus-5",
        effort_execute="medium",
        effort_verify="",  # unset — should chain to effective execute effort
    )
    # Simulate the per-request override in service.py
    overridden_cfg = dataclasses.replace(base_cfg, effort_execute="xhigh")
    client = LLMClient(overridden_cfg)
    fake = _FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)

    client.generate("sys", "user", purpose="verify")
    # Must use the OVERRIDDEN execute effort, not the original "medium"
    assert _effort_from_call(fake.calls[0]) == "xhigh"


def test_correct_effort_uses_overridden_execute_when_unset() -> None:
    """Parallel test for correct tier fallback chaining."""
    base_cfg = Config(
        api_key="x",
        llm_stream=False,
        model_execute="claude-opus-5",
        effort_execute="medium",
        effort_correct="",
    )
    overridden_cfg = dataclasses.replace(base_cfg, effort_execute="max")
    client = LLMClient(overridden_cfg)
    fake = _FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)

    client.generate("sys", "user", purpose="correct")
    assert _effort_from_call(fake.calls[0]) == "max"


# ── Slice 4–6: Route-level validation ────────────────────────────────────────

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter

try:
    from fastapi.testclient import TestClient
    _HAS_TESTCLIENT = True
except ImportError:
    _HAS_TESTCLIENT = False


def _make_app_and_token(
    allowed: tuple[str, ...] = (),
    effort_execute: str = "medium",
    effort_verify: str = "",
    effort_correct: str = "",
    model_verify: str = "",
    model_correct: str = "",
    model_execute: str = "claude-sonnet-4-6",
    gemini_api_key: str = "x",
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
            "gemini-3.1-pro-preview",
        )
    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        gemini_api_key=gemini_api_key,
        llm_models_allowed=allowed,
        model_execute=model_execute,
        model_verify=model_verify,
        model_correct=model_correct,
        effort_execute=effort_execute,
        effort_verify=effort_verify,
        effort_correct=effort_correct,
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


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="requires httpx")
def test_generate_endpoint_rejects_invalid_effort_verify_format_422() -> None:
    """Format-invalid effort_verify (e.g. 'turbo') → 422 from Pydantic validator."""
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token()
    called = {"count": 0}

    async def fake_stream(params, *_args, **_kwargs):
        called["count"] += 1
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(
                "/api/generate?subject=math&effort_verify=turbo",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422
    assert called["count"] == 0


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="requires httpx")
def test_generate_endpoint_rejects_invalid_effort_correct_format_422() -> None:
    """Format-invalid effort_correct → 422 from Pydantic validator."""
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token()
    called = {"count": 0}

    async def fake_stream(params, *_args, **_kwargs):
        called["count"] += 1
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(
                "/api/generate?subject=math&effort_correct=bogus",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422
    assert called["count"] == 0


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="requires httpx")
def test_generate_endpoint_rejects_explicitly_invalid_effort_verify_for_tier_model_422() -> None:
    """Explicitly-invalid effort_verify for the tier's effective model → 422 naming effort_verify.

    Setup: model_verify resolves to gemini-3.1-pro-preview (only low/medium/high),
    effort_verify='xhigh' is explicitly specified → route-level 422.
    """
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6", "gemini-3.1-pro-preview"),
        model_execute="claude-sonnet-4-6",
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
                "/api/generate?subject=math"
                "&model_verify=gemini-3.1-pro-preview"
                "&effort_verify=xhigh",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "effort_verify" in detail
    assert called["count"] == 0


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="requires httpx")
def test_generate_endpoint_rejects_inherited_effort_invalid_for_tier_model_422() -> None:
    """Inherited effort invalid for a diverged tier model → 422 naming the tier field.

    This is the case the removed interim guard used to silently swallow:
    no explicit effort_verify, but effort_execute='xhigh' inherited by a verify
    tier on gemini (which only accepts low/medium/high) → must now 422 at route.
    """
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6", "gemini-3.1-pro-preview"),
        model_execute="claude-sonnet-4-6",
        effort_execute="xhigh",  # env-level execute effort that gemini can't accept
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
                "/api/generate?subject=math"
                "&model_verify=gemini-3.1-pro-preview",
                # No effort_verify → inherits effort_execute=xhigh from config
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "effort_verify" in detail
    assert called["count"] == 0


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="requires httpx")
def test_preview_endpoint_also_validates_effort_verify() -> None:
    """The prompt-preview route must validate effort_verify identically."""
    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6", "gemini-3.1-pro-preview"),
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(
                "/api/generate/preview?subject=math"
                "&model_verify=gemini-3.1-pro-preview"
                "&effort_verify=xhigh",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "effort_verify" in detail


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="requires httpx")
def test_preview_endpoint_also_validates_effort_correct() -> None:
    """The prompt-preview route must validate effort_correct identically."""
    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6", "gemini-3.1-pro-preview"),
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(
                "/api/generate/preview?subject=math"
                "&model_correct=gemini-3.1-pro-preview"
                "&effort_correct=xhigh",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "effort_correct" in detail


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="requires httpx")
def test_generate_endpoint_all_params_unset_no_regression() -> None:
    """Regression: all effort params unset → behaviour unchanged (200, no 422)."""
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
            r = client.get(
                "/api/generate?subject=math",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    assert captured["params"].effort_verify is None
    assert captured["params"].effort_correct is None


# ── Slice 7: GET /api/models defaults include effort_verify / effort_correct ──


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="requires httpx")
def test_models_endpoint_defaults_include_effort_verify_correct() -> None:
    """GET /api/models defaults must include effort_verify and effort_correct."""
    app, token, engine, cfg = _make_app_and_token(effort_verify="high", effort_correct="max")
    try:
        with TestClient(app) as client:
            r = client.get("/api/models")
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    body = r.json()
    assert body["defaults"]["effort_verify"] == "high"
    assert body["defaults"]["effort_correct"] == "max"


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="requires httpx")
def test_models_endpoint_effort_verify_correct_empty_when_unset() -> None:
    """GET /api/models defaults: empty string when not configured (signals 'inherit')."""
    app, token, engine, cfg = _make_app_and_token()  # effort_verify/correct default ""
    try:
        with TestClient(app) as client:
            r = client.get("/api/models")
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert r.status_code == 200
    body = r.json()
    assert body["defaults"]["effort_verify"] == ""
    assert body["defaults"]["effort_correct"] == ""
