"""Admission check: 422 when the effective model's provider API key is unset (issue #342)."""
from __future__ import annotations

import uuid

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.models import User
from server.rate_limit import limiter

_GEMINI_MODEL = "gemini-3.1-pro-preview"
_OPENAI_MODEL = "gpt-5.2"
_CLAUDE_PLAN = "claude-opus-5"
_CLAUDE_EXECUTE = "claude-sonnet-4-6"


def _make_client(
    *,
    api_key: str = "x",
    gemini_api_key: str = "",
    openai_api_key: str = "",
    model_plan: str = _CLAUDE_PLAN,
    model_execute: str = _CLAUDE_EXECUTE,
    extra_models_allowed: tuple[str, ...] = (),
) -> TestClient:
    """Build a TestClient with dependency overrides for the admission gate tests."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    # Build an allowlist that always contains the configured plan/execute models
    # plus any extra models the caller wants to allow.
    seen: dict[str, None] = {}
    for m in (model_plan, model_execute) + extra_models_allowed:
        if m:
            seen[m] = None
    app.dependency_overrides[get_config] = lambda: ServerConfig(
        api_key=api_key,
        gemini_api_key=gemini_api_key,
        openai_api_key=openai_api_key,
        model_plan=model_plan,
        model_execute=model_execute,
        llm_models_allowed=tuple(seen),
    )
    limiter.reset()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Gemini model_execute: missing gemini_api_key → 422 on all three endpoints
# ---------------------------------------------------------------------------


def test_gemini_execute_missing_key_rejected_422_generate() -> None:
    client = _make_client(
        extra_models_allowed=(_GEMINI_MODEL,),
        gemini_api_key="",
    )
    try:
        response = client.get(f"/api/generate?model_execute={_GEMINI_MODEL}")
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "GEMINI_API_KEY" in response.text


def test_gemini_execute_missing_key_rejected_422_preview() -> None:
    client = _make_client(
        extra_models_allowed=(_GEMINI_MODEL,),
        gemini_api_key="",
    )
    try:
        response = client.get(f"/api/generate/preview?model_execute={_GEMINI_MODEL}")
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "GEMINI_API_KEY" in response.text


def test_gemini_execute_missing_key_rejected_422_plan_core_questions() -> None:
    client = _make_client(
        extra_models_allowed=(_GEMINI_MODEL,),
        gemini_api_key="",
    )
    try:
        response = client.post(
            "/api/plan-core-questions",
            json={"topic": "測試", "model_execute": _GEMINI_MODEL},
        )
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "GEMINI_API_KEY" in response.text


# ---------------------------------------------------------------------------
# Gemini model_execute: key present → not 422 from the provider-key gate
# ---------------------------------------------------------------------------


def test_gemini_execute_with_key_passes_admission_generate() -> None:
    client = _make_client(
        extra_models_allowed=(_GEMINI_MODEL,),
        gemini_api_key="g",
    )
    try:
        response = client.get(f"/api/generate?model_execute={_GEMINI_MODEL}")
    finally:
        limiter.reset()
    assert response.status_code != 422


def test_gemini_execute_with_key_passes_admission_preview() -> None:
    client = _make_client(
        extra_models_allowed=(_GEMINI_MODEL,),
        gemini_api_key="g",
    )
    try:
        response = client.get(f"/api/generate/preview?model_execute={_GEMINI_MODEL}")
    finally:
        limiter.reset()
    assert response.status_code != 422


def test_gemini_execute_with_key_passes_admission_plan_core_questions() -> None:
    client = _make_client(
        extra_models_allowed=(_GEMINI_MODEL,),
        gemini_api_key="g",
    )
    try:
        response = client.post(
            "/api/plan-core-questions",
            json={"topic": "測試", "model_execute": _GEMINI_MODEL},
        )
    finally:
        limiter.reset()
    assert response.status_code != 422


# ---------------------------------------------------------------------------
# OpenAI model_execute: missing openai_api_key → 422
# ---------------------------------------------------------------------------


def test_openai_execute_missing_key_rejected_422_generate() -> None:
    client = _make_client(
        extra_models_allowed=(_OPENAI_MODEL,),
        openai_api_key="",
    )
    try:
        response = client.get(f"/api/generate?model_execute={_OPENAI_MODEL}")
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "OPENAI_API_KEY" in response.text


def test_openai_execute_missing_key_rejected_422_preview() -> None:
    client = _make_client(
        extra_models_allowed=(_OPENAI_MODEL,),
        openai_api_key="",
    )
    try:
        response = client.get(f"/api/generate/preview?model_execute={_OPENAI_MODEL}")
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "OPENAI_API_KEY" in response.text


def test_openai_execute_missing_key_rejected_422_plan_core_questions() -> None:
    client = _make_client(
        extra_models_allowed=(_OPENAI_MODEL,),
        openai_api_key="",
    )
    try:
        response = client.post(
            "/api/plan-core-questions",
            json={"topic": "測試", "model_execute": _OPENAI_MODEL},
        )
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "OPENAI_API_KEY" in response.text


# ---------------------------------------------------------------------------
# Anthropic (claude) models: missing api_key → 422 naming LLM_API_KEY
# ---------------------------------------------------------------------------


def test_anthropic_plan_model_missing_key_rejected_422_generate() -> None:
    # Both models are claude (anthropic); api_key is empty; other keys set.
    client = _make_client(
        api_key="",
        gemini_api_key="g",
        openai_api_key="o",
        model_plan=_CLAUDE_PLAN,
        model_execute=_CLAUDE_EXECUTE,
    )
    try:
        response = client.get("/api/generate")
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "LLM_API_KEY" in response.text


def test_anthropic_plan_model_missing_key_rejected_422_plan_core_questions() -> None:
    client = _make_client(
        api_key="",
        gemini_api_key="g",
        openai_api_key="o",
        model_plan=_CLAUDE_PLAN,
        model_execute=_CLAUDE_EXECUTE,
    )
    try:
        response = client.post(
            "/api/plan-core-questions",
            json={"topic": "測試"},
        )
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "LLM_API_KEY" in response.text


# ---------------------------------------------------------------------------
# Config-default path: config model_execute IS a gemini model, no query param
# ---------------------------------------------------------------------------


def test_config_default_gemini_execute_missing_key_rejected_422_generate() -> None:
    # model_execute config default is a gemini model; no model_execute submitted.
    # The gate must check the effective (config-derived) model.
    client = _make_client(
        api_key="x",
        gemini_api_key="",
        model_plan=_CLAUDE_PLAN,
        model_execute=_GEMINI_MODEL,
    )
    try:
        # No model_execute query param → effective_execute = config.model_execute = gemini
        response = client.get("/api/generate")
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "GEMINI_API_KEY" in response.text


def test_config_default_gemini_execute_missing_key_rejected_422_plan_core_questions() -> None:
    client = _make_client(
        api_key="x",
        gemini_api_key="",
        model_plan=_CLAUDE_PLAN,
        model_execute=_GEMINI_MODEL,
    )
    try:
        response = client.post(
            "/api/plan-core-questions",
            json={"topic": "測試"},
        )
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "GEMINI_API_KEY" in response.text


# ---------------------------------------------------------------------------
# Gate ordering: not-in-allowlist fires before the provider-key gate
# ---------------------------------------------------------------------------


def test_not_in_allowlist_fires_before_provider_key_gate_generate() -> None:
    # Gemini model NOT in allowlist, gemini_api_key also empty.
    # _check_model_allowed must fire first (before provider-key gate).
    client = _make_client(
        gemini_api_key="",
        # extra_models_allowed intentionally omits _GEMINI_MODEL
    )
    try:
        response = client.get(f"/api/generate?model_execute={_GEMINI_MODEL}")
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "not in allowlist" in response.text
    assert "GEMINI_API_KEY" not in response.text


def test_not_in_allowlist_fires_before_provider_key_gate_preview() -> None:
    client = _make_client(
        gemini_api_key="",
    )
    try:
        response = client.get(f"/api/generate/preview?model_execute={_GEMINI_MODEL}")
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "not in allowlist" in response.text
    assert "GEMINI_API_KEY" not in response.text
