"""The planning endpoint reports exhausted retries once to Sentry."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

import sentry_sdk
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from server import observability
from server.rate_limit import limiter
from src.llm_client import LLMClient


def _event_items(envelopes):
    return [
        json.loads(item.get_bytes())
        for envelope in envelopes
        for item in envelope.items
        if item.type == "event"
    ]


@pytest.mark.parametrize(
    ("provider_response", "diagnostic"),
    [
        (
            '["短候選甲", "短候選乙"]',
            {
                "stage": "candidate_validation",
                "attempt": 2,
                "expected_count": 3,
                "actual_count": 2,
                "received_count": 2,
            },
        ),
        (
            '["短候選甲", "短候選乙", 42]',
            {
                "stage": "candidate_validation",
                "attempt": 2,
                "expected_count": 3,
                "actual_count": 2,
                "received_count": 3,
            },
        ),
        (
            "not JSON",
            {
                "stage": "response_parse",
                "attempt": 2,
                "expected_count": 3,
                "actual_count": 0,
                "received_count": 0,
            },
        ),
        (
            '{"question": "短候選甲"}',
            {
                "stage": "response_shape",
                "attempt": 2,
                "expected_count": 3,
                "actual_count": 0,
                "received_count": 0,
            },
        ),
    ],
    ids=["short-list", "invalid-third-item", "malformed-json", "object-response"],
)
def test_exhausted_planning_request_reports_one_exception_with_warning_breadcrumb(
    monkeypatch,
    provider_response,
    diagnostic,
):
    """Exhausted planner responses keep safe diagnostics while creating one issue."""
    from tests.server.test_plan_core_questions_routes import _make_app_and_token

    envelopes = []

    class CaptureTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setattr(observability, "_initialized", False)
    original_global_client = sentry_sdk.get_global_scope().client

    call_count = 0

    def short_provider_response(self: LLMClient, system: str, user: str, *, purpose: str):
        nonlocal call_count
        call_count += 1
        return provider_response

    monkeypatch.setattr(LLMClient, "plan", short_provider_response)

    app, token, engine = _make_app_and_token()
    sdk_client = sentry_sdk.get_client()
    original_transport = sdk_client.transport
    sdk_client.transport = CaptureTransport()

    client = TestClient(app)
    try:
        response = client.post(
            "/api/plan-core-questions",
            json={"topic": "保密主題", "subject": "natural_sciences"},
            headers={"Authorization": f"Bearer {token}"},
        )
        logging.getLogger(observability.PLANNER_LOGGER_NAME).warning("unrelated planner warning")
        logging.getLogger("tests.planning").warning(
            "unrelated planning warning", extra={observability.PLANNER_DIAGNOSTIC_MARKER: True},
        )
        logging.getLogger(observability.PLANNER_LOGGER_NAME).error(
            "unrelated planning error", extra={observability.PLANNER_DIAGNOSTIC_MARKER: True},
        )
        sentry_sdk.flush()
    finally:
        client.close()
        sdk_client.transport = original_transport
        sdk_client.close()
        sentry_sdk.get_global_scope().set_client(original_global_client)
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 502
    assert call_count == 2

    events = _event_items(envelopes)
    exception_events = [event for event in events if event.get("exception")]
    warning_events = [
        event
        for event in events
        if event.get("level") == "warning"
        and event.get("logger") == observability.PLANNER_LOGGER_NAME
        and (event.get("extra") or {}).get(observability.PLANNER_DIAGNOSTIC_MARKER) is True
    ]

    assert len(exception_events) == 1
    assert len(events) == 4
    assert warning_events == []
    assert any(
        event.get("logger") == observability.PLANNER_LOGGER_NAME
        and event.get("level") == "warning"
        and event.get("logentry", {}).get("formatted") == "unrelated planner warning"
        for event in events
    )
    assert any(
        event.get("logger") == "tests.planning"
        and event.get("level") == "warning"
        and event.get("logentry", {}).get("formatted") == "unrelated planning warning"
        for event in events
    )
    assert any(
        event.get("logger") == observability.PLANNER_LOGGER_NAME
        and event.get("level") == "error"
        and event.get("logentry", {}).get("formatted") == "unrelated planning error"
        for event in events
    )

    breadcrumbs = exception_events[0].get("breadcrumbs", {}).get("values", [])
    diagnostic_breadcrumbs = [
        breadcrumb
        for breadcrumb in breadcrumbs
        if breadcrumb.get("level") == "warning"
        and breadcrumb.get("category") == observability.PLANNER_LOGGER_NAME
        and breadcrumb.get("data", {}).get(observability.PLANNER_DIAGNOSTIC_MARKER) is True
    ]
    assert len(diagnostic_breadcrumbs) == 1
    assert "Planner" in diagnostic_breadcrumbs[0].get("message", "")
    assert {key: diagnostic_breadcrumbs[0]["data"][key] for key in diagnostic} == diagnostic

    telemetry = json.dumps(events, ensure_ascii=False)
    assert "保密主題" not in telemetry
    assert "短候選甲" not in telemetry
    assert "短候選乙" not in telemetry
    assert token not in telemetry
    assert "u@example.com" not in telemetry


@pytest.mark.parametrize("provider_error", [ValueError, RuntimeError, TimeoutError])
def test_provider_exception_diagnostic_does_not_send_raw_error(monkeypatch, provider_error):
    """Provider failures expose safe counts, never the provider's raw message."""
    from tests.server.test_plan_core_questions_routes import _make_app_and_token

    envelopes = []

    class CaptureTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setattr(observability, "_initialized", False)
    original_global_client = sentry_sdk.get_global_scope().client

    call_count = 0

    def provider_failure(self: LLMClient, system: str, user: str, *, purpose: str):
        nonlocal call_count
        call_count += 1
        raise provider_error("SENSITIVE_PROVIDER_RESPONSE_763")

    monkeypatch.setattr(LLMClient, "plan", provider_failure)

    app, token, engine = _make_app_and_token()
    sdk_client = sentry_sdk.get_client()
    original_transport = sdk_client.transport
    sdk_client.transport = CaptureTransport()
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post(
            "/api/plan-core-questions",
            json={"topic": "保密主題", "subject": "natural_sciences"},
            headers={"Authorization": f"Bearer {token}"},
        )
        sentry_sdk.flush()
    finally:
        client.close()
        sdk_client.transport = original_transport
        sdk_client.close()
        sentry_sdk.get_global_scope().set_client(original_global_client)
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 502
    assert call_count == 1

    events = _event_items(envelopes)
    exception_events = [event for event in events if event.get("exception")]
    assert len(exception_events) == 1

    breadcrumbs = exception_events[0].get("breadcrumbs", {}).get("values", [])
    diagnostic_breadcrumbs = [
        breadcrumb
        for breadcrumb in breadcrumbs
        if breadcrumb.get("level") == "warning"
        and breadcrumb.get("category") == observability.PLANNER_LOGGER_NAME
        and breadcrumb.get("data", {}).get(observability.PLANNER_DIAGNOSTIC_MARKER) is True
    ]
    assert len(diagnostic_breadcrumbs) == 1
    assert {
        key: diagnostic_breadcrumbs[0]["data"][key]
        for key in ("stage", "attempt", "expected_count", "actual_count", "received_count")
    } == {
        "stage": "provider_call",
        "attempt": 1,
        "expected_count": 3,
        "actual_count": 0,
        "received_count": 0,
    }

    telemetry = json.dumps(events, ensure_ascii=False)
    assert "SENSITIVE_PROVIDER_RESPONSE_763" not in telemetry
    assert "保密主題" not in telemetry
    assert token not in telemetry
    assert "u@example.com" not in telemetry
