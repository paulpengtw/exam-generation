"""
Research test for issue #928: do raw LLM provider exceptions reach Sentry?

This module documents *current behaviour* by asserting what the AnthropicIntegration
and OpenAIIntegration actually capture.  It uses real provider SDK exceptions raised
through httpx.MockTransport (not monkeypatched client methods), and initialises Sentry
with the same configuration as the production observability module.

Key findings documented here:
  1. AnthropicIntegration._sentry_patched_create_sync/_sentry_patched_create_async
     (sentry_sdk.integrations.anthropic, lines ~664 and ~762) call
     sentry_sdk.capture_event() **directly** when messages.create raises any exception.
     This happens inside the patched wrapper, before the exception propagates to the
     caller.  The planner's `raise CandidateValidationError(...) from None` therefore
     cannot prevent this – the event has already been sent.
  2. OpenAIIntegration does the same for OpenAI-compat calls (Gemini/OpenAI models).
  3. The exception **message** (str(exc)) contains the API response body verbatim,
     e.g. "Error code: 400 - {'error': {'type': '...', 'message': '...'}}".  This is
     ADR-0004 significant because it includes the provider's error text, which for
     credit-balance or quota errors is harmless, but for content-filter or
     invalid_request errors could in principle contain token counts or category labels.
  4. Prompt content does NOT appear in the event under the production config
     (include_local_variables=False eliminates local-variable serialisation from
     _sentry_patched_create_* frames; include_prompts=False eliminates span input data).
  5. before_send / _before_send in server/observability.py runs for these events
     (all capture_event calls pass through before_send), but _before_send only drops
     events tagged PLANNER_DIAGNOSTIC_MARKER=True at level=warning.  The
     AnthropicIntegration events are level="error" with mechanism.handled=False, so
     _before_send does NOT drop them.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

import sentry_sdk
from sentry_sdk.transport import Transport

from server import observability
from server.rate_limit import limiter
from src.config import Config as SrcConfig
from src.llm_client import LLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


class _RecordingTransport(Transport):
    def __init__(self) -> None:
        self.envelopes: list = []

    def capture_envelope(self, envelope) -> None:  # type: ignore[override]
        self.envelopes.append(envelope)


# ---------------------------------------------------------------------------
# Fixture: isolated Sentry init with production-equivalent config
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_sentry():
    """
    Initialise Sentry with the same options as server.observability.init_sentry()
    but using an in-memory recording transport, with no network calls.

    Yields the recording transport.  Restores the original SDK state afterwards.
    """
    original_global_client = sentry_sdk.get_global_scope().client
    monkeypatch_was_reset = False

    rec = _RecordingTransport()

    # Duplicate the production init_kwargs from server/observability.py, substituting
    # our recording transport.  We must reset _initialized so the real init runs.
    import sentry_sdk.integrations.anthropic as _ai
    import sentry_sdk.integrations.openai as _oi
    from sentry_sdk.integrations.anthropic import AnthropicIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.openai import OpenAIIntegration

    was_initialized = observability._initialized
    observability._initialized = False

    data_collection = {
        "user_info": False,
        "cookies": {"mode": "off"},
        "http_headers": {"request": {"mode": "off"}},
        "http_bodies": [],
        "query_params": {"mode": "allowlist", "terms": []},
        "graphql": {"document": False, "variables": False},
        "gen_ai": {"inputs": False, "outputs": False},
        "database_query_data": False,
        "queues": False,
        "stack_frame_variables": False,
        "frame_context_lines": 5,
    }

    sentry_sdk.init(
        dsn="https://public@example.com/1",
        transport=rec,
        before_send=observability._before_send,
        traces_sample_rate=1.0,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        include_source_context=True,
        _experiments={"data_collection": data_collection},
        integrations=[
            AnthropicIntegration(include_prompts=False),
            OpenAIIntegration(include_prompts=False),
            LoggingIntegration(
                level=logging.WARNING,
                event_level=logging.WARNING,
            ),
        ],
    )
    observability._initialized = True

    try:
        yield rec
    finally:
        sentry_sdk.flush()
        sdk_client = sentry_sdk.get_client()
        sdk_client.close()
        sentry_sdk.get_global_scope().set_client(original_global_client)
        observability._initialized = was_initialized


# ---------------------------------------------------------------------------
# Test 1: AnthropicIntegration fires independently of planner's re-raise-from-None
# ---------------------------------------------------------------------------


def test_anthropic_integration_captures_bad_request_before_planner_re_raise(
    isolated_sentry: _RecordingTransport, monkeypatch
) -> None:
    """
    DOCUMENTS CURRENT BEHAVIOUR: AnthropicIntegration emits a Sentry event for the raw
    BadRequestError even though the planner wraps it in CandidateValidationError(...) from None.

    Mechanism (file:line):
        sentry_sdk/integrations/anthropic.py _sentry_patched_create_sync / _sentry_patched_create_async
        -> except Exception as exc: _capture_exception(exc) -> sentry_sdk.capture_event(event, hint=hint)
        This call precedes any caller try/except, so `from None` suppression is irrelevant.
    """
    from tests.server.test_plan_core_questions_routes import _make_app_and_token
    from fastapi.testclient import TestClient

    CREDIT_MSG = "RESEARCH_928_Your credit balance is too low to access the Anthropic API"

    http_mock = _make_anthropic_400_transport(CREDIT_MSG)

    # Patch LLMClient so the Anthropic client uses our mock HTTP transport.
    from anthropic import Anthropic as _Anthropic

    original_anthropic_init = _Anthropic.__init__

    def patched_anthropic_init(self, *args, **kwargs):
        kwargs["http_client"] = http_mock
        original_anthropic_init(self, *args, **kwargs)

    monkeypatch.setattr(_Anthropic, "__init__", patched_anthropic_init)

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
        limiter.reset()
        asyncio.run(engine.dispose())

    events = _event_items(isolated_sentry.envelopes)
    exception_events = [e for e in events if e.get("exception")]
    telemetry = json.dumps(events, ensure_ascii=False)

    # DOCUMENTS CURRENT BEHAVIOUR:
    # The AnthropicIntegration fires and produces at least one exception event for
    # the raw BadRequestError.  The planner's from-None re-raise does NOT prevent this.
    assert len(exception_events) >= 1, (
        "Expected at least one Sentry exception event from AnthropicIntegration "
        "for the raw BadRequestError, but got none."
    )

    # The exception type is BadRequestError (the raw Anthropic SDK exception).
    exc_types = [
        v["type"]
        for e in exception_events
        for v in e["exception"]["values"]
    ]
    assert "BadRequestError" in exc_types, (
        f"Expected BadRequestError in captured exception types; got {exc_types}"
    )

    # The mechanism is 'anthropic' with handled=False — set by AnthropicIntegration.
    mechanisms = [
        v.get("mechanism", {})
        for e in exception_events
        for v in e["exception"]["values"]
        if v.get("type") == "BadRequestError"
    ]
    assert any(m.get("type") == "anthropic" for m in mechanisms), (
        f"Expected mechanism.type='anthropic'; got {mechanisms}"
    )

    # The error MESSAGE (provider's response body text) is captured.
    # This is expected and currently unavoidable with the production config.
    assert CREDIT_MSG in telemetry, (
        "Expected provider error message in Sentry telemetry (confirms current behaviour)"
    )

    # CRITICAL: prompt content is NOT in the telemetry (include_local_variables=False).
    assert "Taiwan geography" not in telemetry, (
        "Prompt topic leaked into Sentry telemetry — violates ADR 0004"
    )

    # The endpoint still returns 502 (the planner's re-raise-from-None is unaffected
    # at the HTTP level).
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# Test 2: AnthropicIntegration fires for a direct LLM call (generation path)
# ---------------------------------------------------------------------------


def test_anthropic_integration_captures_bad_request_on_generate_path(
    isolated_sentry: _RecordingTransport,
) -> None:
    """
    DOCUMENTS CURRENT BEHAVIOUR: AnthropicIntegration fires for every call site that
    goes through client.messages.create — not just the planner.

    This test exercises the direct LLMClient.generate call (used by execute,
    verification, correction, and fact-check paths), bypassing the server endpoint.
    """
    QUOTA_MSG = "RESEARCH_928_overloaded_error: 529 Overloaded"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            529,
            json={"error": {"type": "overloaded_error", "message": QUOTA_MSG}},
            request=request,
        )

    http_mock = httpx.Client(transport=httpx.MockTransport(handler))

    from anthropic import Anthropic as _Anthropic

    # Directly construct a config and inject the mock http_client into Anthropic.
    config = SrcConfig(
        api_key="test-key",
        base_url="https://api.anthropic.com/v1",
    )

    llm_client = LLMClient(config)
    # Patch the already-constructed Anthropic client's http_client.
    llm_client.client = _Anthropic(api_key="test-key", http_client=http_mock)

    with pytest.raises(Exception):
        llm_client.generate(
            system="system prompt",
            user="SENTINEL_GENERATE_PROMPT_928",
            model="claude-opus-4-6",
            purpose="generate",
        )

    sentry_sdk.flush()

    events = _event_items(isolated_sentry.envelopes)
    exception_events = [e for e in events if e.get("exception")]
    telemetry = json.dumps(events, ensure_ascii=False)

    # DOCUMENTS CURRENT BEHAVIOUR: exception event is captured for generate path too.
    assert len(exception_events) >= 1, (
        "Expected at least one Sentry exception event for the generate path; got none."
    )

    exc_types = [
        v["type"]
        for e in exception_events
        for v in e["exception"]["values"]
    ]
    assert "OverloadedError" in exc_types or "InternalServerError" in exc_types or any(
        "Error" in t for t in exc_types
    ), f"Expected a provider error type; got {exc_types}"

    # Provider error message is in telemetry.
    assert QUOTA_MSG in telemetry

    # Prompt content is NOT in telemetry (include_local_variables=False protects this).
    assert "SENTINEL_GENERATE_PROMPT_928" not in telemetry, (
        "Prompt text leaked into Sentry telemetry — violates ADR 0004"
    )


# ---------------------------------------------------------------------------
# Test 3: OpenAIIntegration fires for Gemini/OpenAI-compat calls
# ---------------------------------------------------------------------------


def test_openai_integration_captures_bad_request_for_gemini_call(
    isolated_sentry: _RecordingTransport, monkeypatch
) -> None:
    """
    DOCUMENTS CURRENT BEHAVIOUR: OpenAIIntegration fires for openai.OpenAI-compat calls,
    which are used for Gemini and OpenAI model paths in LLMClient.
    """
    GEMINI_ERROR_MSG = "RESEARCH_928_Gemini context window exceeded"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"type": "invalid_request_error", "message": GEMINI_ERROR_MSG}},
            request=request,
        )

    http_mock_sync = httpx.Client(transport=httpx.MockTransport(handler))

    import openai

    original_openai_init = openai.OpenAI.__init__

    def patched_openai_init(self, *args, **kwargs):
        kwargs["http_client"] = http_mock_sync
        original_openai_init(self, *args, **kwargs)

    monkeypatch.setattr(openai.OpenAI, "__init__", patched_openai_init)

    config = SrcConfig(
        api_key="test-anthropic-key",
        gemini_api_key="test-gemini-key",
        model_execute="gemini-3.1-pro-preview",
    )
    llm_client = LLMClient(config)

    with pytest.raises(Exception):
        llm_client.generate(
            system="system",
            user="SENTINEL_GEMINI_PROMPT_928",
            model="gemini-3.1-pro-preview",
            purpose="generate",
        )

    sentry_sdk.flush()

    events = _event_items(isolated_sentry.envelopes)
    exception_events = [e for e in events if e.get("exception")]
    telemetry = json.dumps(events, ensure_ascii=False)

    # DOCUMENTS CURRENT BEHAVIOUR: OpenAI integration fires too.
    assert len(exception_events) >= 1, (
        "Expected at least one Sentry exception event for Gemini/OpenAI-compat call; got none."
    )

    # Prompt content NOT in telemetry.
    assert "SENTINEL_GEMINI_PROMPT_928" not in telemetry, (
        "Gemini prompt text leaked into Sentry telemetry — violates ADR 0004"
    )

    # Provider error message IS in telemetry.
    assert GEMINI_ERROR_MSG in telemetry


# ---------------------------------------------------------------------------
# Test 4: before_send does NOT filter these exception events
# ---------------------------------------------------------------------------


def test_before_send_does_not_filter_anthropic_integration_exception_events(
    isolated_sentry: _RecordingTransport,
) -> None:
    """
    DOCUMENTS CURRENT BEHAVIOUR: _before_send only drops events that are:
      - level='warning'
      - logger=PLANNER_LOGGER_NAME
      - extra.PLANNER_DIAGNOSTIC_MARKER=True

    The AnthropicIntegration events are level='error' with mechanism.handled=False,
    so they pass through _before_send unchanged.
    """
    BALANCE_MSG = "RESEARCH_928_before_send_test_credit_balance"

    http_mock = _make_anthropic_400_transport(BALANCE_MSG)

    from anthropic import Anthropic as _Anthropic

    client = _Anthropic(api_key="test", http_client=http_mock)

    try:
        client.messages.create(
            model="claude-opus-4-6",
            max_tokens=10,
            messages=[{"role": "user", "content": "test"}],
        )
    except Exception:
        pass

    sentry_sdk.flush()

    events = _event_items(isolated_sentry.envelopes)
    exception_events = [e for e in events if e.get("exception")]

    # before_send did NOT drop the event — it reached the recording transport.
    assert len(exception_events) >= 1, (
        "Expected AnthropicIntegration exception event to reach transport "
        "(before_send should not drop it)"
    )

    # The level is error (not warning), confirming _before_send's warning filter doesn't match.
    levels = [e.get("level") for e in exception_events]
    assert all(lvl == "error" for lvl in levels if lvl is not None), (
        f"Expected all exception events at level='error'; got {levels}"
    )
