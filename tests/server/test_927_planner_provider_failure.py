"""Tests for issue #927: distinguish provider-call failures from malformed-output failures
in POST /api/plan-core-questions.

Provider-call failures (credit exhausted, auth errors, rate limits, etc.) must return
502 with code=PLANNER_PROVIDER_ERROR, distinct from genuinely malformed output which
returns 502 with code=PLANNER_MALFORMED_OUTPUT.

The #763 privacy rule still holds: provider error text never appears in response/logs/Sentry.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient

from server.rate_limit import limiter
from src.llm_client import LLMClient


def _make_anthropic_credit_error():
    """Construct a real anthropic.BadRequestError that looks like a credit-balance failure."""
    anthropic = pytest.importorskip("anthropic")

    # httpx.Response requires a request to be associated before accessing .request
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        status_code=400,
        json={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "Your credit balance is too low to access the Anthropic API...",
            },
        },
        request=req,
    )
    return anthropic.BadRequestError(
        message="Your credit balance is too low",
        response=response,
        body={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "Your credit balance is too low to access the Anthropic API...",
            },
        },
    )


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
def test_provider_credit_error_returns_provider_error_code_for_ss_and_ns(
    monkeypatch,
    subject,
):
    """Anthropic 400 credit-balance error for social_studies/natural_sciences
    returns 502 PLANNER_PROVIDER_ERROR, not PLANNER_MALFORMED_OUTPUT."""
    from tests.server.test_plan_core_questions_routes import _make_app_and_token

    credit_error = _make_anthropic_credit_error()

    def raise_credit_error(self: LLMClient, system: str, user: str, *, purpose: str):
        raise credit_error

    monkeypatch.setattr(LLMClient, "plan", raise_credit_error)

    app, token, engine = _make_app_and_token()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "光合作用", "subject": subject},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "PLANNER_PROVIDER_ERROR"
    assert body["detail"] == "Planner provider call failed"
    # #763: no provider error text in response
    assert "credit balance" not in response.text.lower()
    assert "credit balance" not in str(body).lower()


def test_provider_credit_error_returns_provider_error_code_for_math(monkeypatch):
    """Anthropic 400 credit-balance error for math subject
    returns 502 PLANNER_PROVIDER_ERROR."""
    from tests.server.test_plan_core_questions_routes import _make_app_and_token

    credit_error = _make_anthropic_credit_error()

    def raise_credit_error(self: LLMClient, system: str, user: str, *, purpose: str):
        raise credit_error

    monkeypatch.setattr(LLMClient, "plan", raise_credit_error)

    app, token, engine = _make_app_and_token()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "微積分", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "PLANNER_PROVIDER_ERROR"
    assert body["detail"] == "Planner provider call failed"
    assert "credit balance" not in response.text.lower()


def test_non_json_model_output_returns_malformed_output_code(monkeypatch):
    """Non-JSON model output (parse failure) still returns 502 with
    PLANNER_MALFORMED_OUTPUT code, not PLANNER_PROVIDER_ERROR."""
    from tests.server.test_plan_core_questions_routes import _make_app_and_token

    def return_garbage(self: LLMClient, system: str, user: str, *, purpose: str):
        return "this is definitely not json or a numbered list at all whatsoever"

    monkeypatch.setattr(LLMClient, "plan", return_garbage)

    app, token, engine = _make_app_and_token()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "生態", "subject": "natural_sciences"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "PLANNER_MALFORMED_OUTPUT"
    assert body["detail"] == "Planner upstream returned malformed candidates"
