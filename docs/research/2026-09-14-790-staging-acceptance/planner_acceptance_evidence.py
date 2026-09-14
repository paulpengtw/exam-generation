"""Controlled-provider acceptance evidence for issue #790 (criteria 4 and 6).

Runs the real planner and the real FastAPI planning endpoint at the deployed
revision, with the provider seam scripted and Sentry routed to an in-memory
transport.  No telemetry leaves the process and no shared deployment changes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

import sentry_sdk
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from server import observability
from server.rate_limit import limiter
from src.common.planner import CandidateValidationError, plan_core_questions
from src.llm_client import LLMClient

from src.natural_sciences.planner import _PLANNER_SYSTEM_PROMPT as NS_SYSTEM
from src.natural_sciences.planner import _PLANNER_USER_TEMPLATE as NS_USER

TOPIC = "合成測試主題：校園雨水回收"
SHORT_VALID = '["短問甲？", "短問乙？", "短問丙？"]'
results: dict[str, object] = {}


class _Scripted:
    """Return each scripted provider reply in order; record the call count."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def as_plan(self):
        """Return a plain function so class-attribute lookup binds `self`."""
        def plan(_client_self, system, user, *, purpose):
            self.calls += 1
            return self.replies[min(self.calls - 1, len(self.replies) - 1)]
        return plan


def _planner_case(name, replies, *, expect):
    scripted = _Scripted(replies)
    original = LLMClient.plan
    LLMClient.plan = scripted.as_plan()
    row = {"name": name, "expect": expect}
    try:
        out = plan_core_questions(
            LLMClient.__new__(LLMClient), TOPIC, n=3,
            system_prompt=NS_SYSTEM, user_prompt_template=NS_USER,
        )
        row.update(outcome="success", candidates=out, calls=scripted.calls)
    except CandidateValidationError as exc:
        row.update(
            outcome="controlled_failure",
            calls=scripted.calls,
            stage=exc.stage,
            attempt=exc.attempt,
            expected_count=exc.expected_count,
            actual_count=exc.actual_count,
            received_count=exc.received_count,
            message=str(exc),
        )
    except Exception as exc:  # pragma: no cover - surfaced as a defect
        row.update(outcome="unexpected_exception", calls=scripted.calls,
                   error=f"{type(exc).__name__}: {exc}")
    finally:
        LLMClient.plan = original
    return row


# --- Criterion 4: deterministic recovery, exhaustion, and candidate fidelity ---
planner_rows = [
    _planner_case(
        "recovery: insufficient then valid",
        ['["短問甲？", "短問乙？"]', SHORT_VALID],
        expect="success in exactly 2 calls, 3 short candidates verbatim",
    ),
    _planner_case(
        "exhaustion: invalid then invalid",
        ['["短問甲？", "短問乙？"]', '["短問甲？", "短問乙？"]'],
        expect="controlled failure after exactly 2 calls",
    ),
    _planner_case(
        "exhaustion: unparseable then unparseable",
        ["not JSON at all", "still not JSON"],
        expect="controlled failure after exactly 2 calls",
    ),
    _planner_case(
        "short candidates on first call are preserved",
        [SHORT_VALID],
        expect="success in 1 call, short candidates kept verbatim",
    ),
    _planner_case(
        "numbered plain-text list keeps all three (the #763 regression)",
        ["1. 短問甲？\n2. 短問乙？\n3.短問丙？"],
        expect="success in 1 call, three numbered questions preserved",
    ),
    _planner_case(
        "duplicates are not padded back to three",
        ['["重複問？", "重複問？", "重複問？"]', '["重複問？", "重複問？", "重複問？"]'],
        expect="controlled failure; no placeholder or duplicate padding",
    ),
    _planner_case(
        "non-text items are not coerced into candidates",
        ['["短問甲？", "短問乙？", 42]', '["短問甲？", "短問乙？", 42]'],
        expect="controlled failure; 42 never becomes a candidate",
    ),
    _planner_case(
        "recovery after an unparseable first output",
        ["not JSON at all", SHORT_VALID],
        expect="success in exactly 2 calls",
    ),
]
results["planner_cases"] = planner_rows


# --- Criterion 6: one exhausted request -> exactly one Sentry exception event ---
def _event_items(envelopes):
    return [
        json.loads(item.get_bytes())
        for envelope in envelopes
        for item in envelope.items
        if item.type == "event"
    ]


def _http_case(name, replies, *, with_unrelated_logs):
    sys.path.insert(0, ".")
    from tests.server.test_plan_core_questions_routes import _make_app_and_token

    envelopes: list = []

    class CaptureTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    import os
    os.environ["SENTRY_DSN"] = "https://public@example.com/1"
    observability._initialized = False
    original_global_client = sentry_sdk.get_global_scope().client

    scripted = _Scripted(replies)
    original_plan = LLMClient.plan
    LLMClient.plan = scripted.as_plan()

    app, token, engine = _make_app_and_token()
    sdk_client = sentry_sdk.get_client()
    original_transport = sdk_client.transport
    sdk_client.transport = CaptureTransport()

    client = TestClient(app)
    try:
        response = client.post(
            "/api/plan-core-questions",
            json={"topic": TOPIC, "subject": "natural_sciences"},
            headers={"Authorization": f"Bearer {token}"},
        )
        status, payload = response.status_code, response.text
        if with_unrelated_logs:
            logging.getLogger(observability.PLANNER_LOGGER_NAME).warning(
                "unrelated planner warning")
            logging.getLogger(observability.PLANNER_LOGGER_NAME).error(
                "unrelated planner error")
        sentry_sdk.flush()
    finally:
        client.close()
        sdk_client.transport = original_transport
        sdk_client.close()
        sentry_sdk.get_global_scope().set_client(original_global_client)
        limiter.reset()
        asyncio.run(engine.dispose())
        LLMClient.plan = original_plan

    events = _event_items(envelopes)
    exception_events = [e for e in events if e.get("exception")]
    marked_warning_issues = [
        e for e in events
        if e.get("level") == "warning"
        and e.get("logger") == observability.PLANNER_LOGGER_NAME
        and (e.get("extra") or {}).get(observability.PLANNER_DIAGNOSTIC_MARKER) is True
    ]
    breadcrumbs = (
        exception_events[0].get("breadcrumbs", {}).get("values", [])
        if exception_events else []
    )
    diagnostic_breadcrumbs = [
        b for b in breadcrumbs
        if b.get("level") == "warning"
        and b.get("category") == observability.PLANNER_LOGGER_NAME
        and (b.get("data") or {}).get(observability.PLANNER_DIAGNOSTIC_MARKER) is True
    ]
    telemetry = json.dumps(events, ensure_ascii=False)
    leak_probes = {
        "topic": TOPIC,
        "candidate_text": "短問甲？",
        "auth_token": token,
        "teacher_identity": "u@example.com",
    }
    return {
        "name": name,
        "http_status": status,
        "response_body": payload[:200],
        "provider_calls": scripted.calls,
        "total_sentry_events": len(events),
        "exception_events": len(exception_events),
        "marked_warning_issue_events": len(marked_warning_issues),
        "diagnostic_breadcrumbs": len(diagnostic_breadcrumbs),
        "breadcrumb_diagnostic_fields": (
            {k: diagnostic_breadcrumbs[0]["data"].get(k)
             for k in ("stage", "attempt", "expected_count", "actual_count", "received_count")}
            if diagnostic_breadcrumbs else None
        ),
        "unrelated_warning_event_present": any(
            e.get("level") == "warning"
            and e.get("logentry", {}).get("formatted") == "unrelated planner warning"
            for e in events),
        "unrelated_error_event_present": any(
            e.get("level") == "error"
            and e.get("logentry", {}).get("formatted") == "unrelated planner error"
            for e in events),
        "leaks_found": {k: (v in telemetry) for k, v in leak_probes.items()},
        "request_body_in_telemetry": '"data"' in telemetry and TOPIC in telemetry,
    }


results["http_cases"] = [
    _http_case("exhausted planning (insufficient twice)",
               ['["短問甲？", "短問乙？"]', '["短問甲？", "短問乙？"]'],
               with_unrelated_logs=True),
    _http_case("successful recovery (insufficient then valid)",
               ['["短問甲？", "短問乙？"]', SHORT_VALID],
               with_unrelated_logs=False),
]

print(json.dumps(results, ensure_ascii=False, indent=1))
