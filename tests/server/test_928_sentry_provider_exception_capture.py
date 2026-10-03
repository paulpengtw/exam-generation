"""Regression tests for expected provider failures reaching Sentry (#928/#967).

These tests use real Anthropic and OpenAI SDK calls with ``httpx.MockTransport``
and initialise Sentry through ``server.observability.init_sentry``.  The SDK
integrations still provide GenAI tracing, but their raw unhandled provider
exception events are filtered.  The application keeps one safe operational signal:
the normal WARNING event emitted by ``LLMClient`` (and the pre-existing sanitized
planner event remains available for malformed, non-provider output).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

import sentry_sdk
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from server import observability
from server.rate_limit import limiter
from src.config import Config as SrcConfig
from src.llm_client import LLMClient


def _make_anthropic_400_transport(error_message: str) -> httpx.Client:
    """Return an httpx.Client whose transport always returns a 400 Bad Request."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "message": error_message,
                }
            },
            request=request,
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _event_items(envelopes: list) -> list[dict]:
    return [
        json.loads(item.get_bytes())
        for envelope in envelopes
        for item in envelope.items
        if item.type == "event"
    ]


def _provider_integration_events(events: list[dict]) -> list[dict]:
    return [
        event
        for event in events
        if any(
            value.get("mechanism", {}).get("type") in {"anthropic", "openai"}
            and value.get("mechanism", {}).get("handled") is False
            for value in event.get("exception", {}).get("values", [])
        )
    ]


def _warning_events(events: list[dict], logger_name: str) -> list[dict]:
    return [
        event
        for event in events
        if event.get("level") == "warning" and event.get("logger") == logger_name
    ]


class _RecordingTransport(Transport):
    def __init__(self) -> None:
        self.envelopes: list = []

    def capture_envelope(self, envelope) -> None:  # type: ignore[override]
        self.envelopes.append(envelope)


@pytest.fixture()
def isolated_sentry(monkeypatch) -> _RecordingTransport:
    """Initialise the production Sentry configuration with an in-memory transport."""

    original_global_client = sentry_sdk.get_global_scope().client
    was_initialized = observability._initialized
    recording_transport = _RecordingTransport()

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    # The planner endpoint builds its source Config from the environment rather
    # than the ServerConfig dependency used by the test app helper.
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    observability._initialized = False

    assert observability.init_sentry(transport=recording_transport)

    try:
        yield recording_transport
    finally:
        sentry_sdk.flush()
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(original_global_client)
        observability._initialized = was_initialized


def test_anthropic_provider_event_is_filtered_before_planner_re_raise(
    isolated_sentry: _RecordingTransport, monkeypatch
) -> None:
    """Planner keeps one safe warning signal and drops the raw SDK event."""

    from anthropic import Anthropic

    from tests.server.test_plan_core_questions_routes import _make_app_and_token

    credit_message = (
        "RESEARCH_928_Your credit balance is too low to access the Anthropic API"
    )
    http_mock = _make_anthropic_400_transport(credit_message)
    real_llm_client = LLMClient

    def make_client(config: SrcConfig) -> LLMClient:
        client = real_llm_client(config)
        client.client = Anthropic(api_key=config.api_key, http_client=http_mock)
        return client

    # The route imports LLMClient at call time.  Replace only that factory so
    # the route still exercises the real planner and SDK integration wrapper.
    monkeypatch.setattr("src.llm_client.LLMClient", make_client)

    app, token, engine = _make_app_and_token()
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post(
            "/api/plan-core-questions",
            json={"topic": "Taiwan geography", "subject": "social_studies"},
            headers={"Authorization": f"Bearer {token}"},
        )
        sentry_sdk.flush()
    finally:
        client.close()
        http_mock.close()
        limiter.reset()
        asyncio.run(engine.dispose())

    events = _event_items(isolated_sentry.envelopes)
    exception_events = [event for event in events if event.get("exception")]
    provider_events = _provider_integration_events(events)
    telemetry = json.dumps(events, ensure_ascii=False)

    assert response.status_code == 502
    assert provider_events == []
    assert exception_events == []
    warning_events = _warning_events(events, "src.llm_client")
    assert len(warning_events) == 1
    assert "llm_failure provider=anthropic" in warning_events[0]["logentry"]["formatted"]

    assert credit_message not in telemetry
    assert "Taiwan geography" not in telemetry


def test_anthropic_provider_event_is_filtered_on_generate_path(
    isolated_sentry: _RecordingTransport,
) -> None:
    """Generation keeps its existing WARNING signal without an SDK exception event."""

    from anthropic import Anthropic

    quota_message = "RESEARCH_928_overloaded_error: 529 Overloaded"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            529,
            json={"error": {"type": "overloaded_error", "message": quota_message}},
            request=request,
        )

    http_mock = httpx.Client(transport=httpx.MockTransport(handler))
    config = SrcConfig(api_key="test-key", base_url="https://api.anthropic.com/v1")
    llm_client = LLMClient(config)
    llm_client.client = Anthropic(api_key="test-key", http_client=http_mock)

    try:
        with pytest.raises(Exception):
            llm_client.generate(
                system="system prompt",
                user="SENTINEL_GENERATE_PROMPT_928",
                model="claude-opus-4-6",
                purpose="generate",
            )
        sentry_sdk.flush()
    finally:
        http_mock.close()

    events = _event_items(isolated_sentry.envelopes)
    telemetry = json.dumps(events, ensure_ascii=False)

    assert _provider_integration_events(events) == []
    assert [event for event in events if event.get("exception")] == []
    warning_events = _warning_events(events, "src.llm_client")
    assert len(warning_events) == 1
    assert "llm_failure provider=anthropic" in warning_events[0]["logentry"]["formatted"]
    assert quota_message not in telemetry
    assert "SENTINEL_GENERATE_PROMPT_928" not in telemetry


def test_openai_provider_event_is_filtered_for_gemini_call(
    isolated_sentry: _RecordingTransport,
) -> None:
    """OpenAI-compatible Gemini calls keep one WARNING signal and no SDK event."""

    import openai

    gemini_error_message = "RESEARCH_928_Gemini context window exceeded"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "message": gemini_error_message,
                }
            },
            request=request,
        )

    http_mock = httpx.Client(transport=httpx.MockTransport(handler))
    config = SrcConfig(
        api_key="test-anthropic-key",
        gemini_api_key="test-gemini-key",
        model_execute="gemini-3.1-pro-preview",
    )
    llm_client = LLMClient(config)
    llm_client._compat_clients["gemini"] = openai.OpenAI(
        api_key="test-gemini-key",
        base_url=config.gemini_base_url,
        http_client=http_mock,
    )

    try:
        with pytest.raises(Exception):
            llm_client.generate(
                system="system",
                user="SENTINEL_GEMINI_PROMPT_928",
                model="gemini-3.1-pro-preview",
                purpose="generate",
            )
        sentry_sdk.flush()
    finally:
        http_mock.close()

    events = _event_items(isolated_sentry.envelopes)
    telemetry = json.dumps(events, ensure_ascii=False)

    assert _provider_integration_events(events) == []
    assert [event for event in events if event.get("exception")] == []
    warning_events = _warning_events(events, "src.llm_client")
    assert len(warning_events) == 1
    assert "llm_failure provider=gemini" in warning_events[0]["logentry"]["formatted"]
    assert gemini_error_message not in telemetry
    assert "SENTINEL_GEMINI_PROMPT_928" not in telemetry


def test_before_send_drops_direct_anthropic_integration_exception_event(
    isolated_sentry: _RecordingTransport,
) -> None:
    """The production before_send filter covers direct SDK calls too."""

    from anthropic import Anthropic

    http_mock = _make_anthropic_400_transport(
        "RESEARCH_928_before_send_test_credit_balance"
    )
    client = Anthropic(api_key="test-key", http_client=http_mock)

    try:
        with pytest.raises(Exception):
            client.messages.create(
                model="claude-opus-4-6",
                max_tokens=10,
                messages=[{"role": "user", "content": "test"}],
            )
        sentry_sdk.flush()
    finally:
        http_mock.close()

    events = _event_items(isolated_sentry.envelopes)
    assert _provider_integration_events(events) == []
    assert [event for event in events if event.get("exception")] == []
