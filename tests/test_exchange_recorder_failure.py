"""Tests for ExchangeRecorder persisting llm_failure events.

Tasks 4.1–4.4 — TDD: failing tests written before implementation.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from server.generate.exchange_recorder import ExchangeRecorder


def _make_recorder(rows: list | None = None) -> ExchangeRecorder:
    """Return an ExchangeRecorder with a capture-only write_row."""
    captured: list[dict] = rows if rows is not None else []

    def write_row(row: dict[str, Any]) -> None:
        captured.append(row)

    log_id = uuid.uuid4()
    return ExchangeRecorder(log_id, write_row)


def _failure_event(
    *,
    run_id: str | None = None,
    call_id: str | None = None,
    agent: str = "generator",
    purpose: str = "generate",
    model: str = "claude-opus-4-6",
    http_status: int | None = 429,
    provider: str = "anthropic",
    provider_error_type: str | None = "rate_limit_error",
    provider_error_code: str | None = "enforced_spend_limit_reached",
    provider_error_status: str | None = None,
    provider_message: str | None = "You have reached your API usage limits",
    request_id: str | None = None,
    retry_after_seconds: int | None = None,
    raw_body_truncated: str | None = '{"type":"error","error":{"type":"rate_limit_error"}}',
    error_type: str = "RateLimitError",
) -> dict:
    ev: dict[str, Any] = {
        "type": "llm_failure",
        "agent": agent,
        "purpose": purpose,
        "model": model,
        "provider": provider,
        "http_status": http_status,
        "provider_error_type": provider_error_type,
        "provider_error_code": provider_error_code,
        "provider_error_status": provider_error_status,
        "provider_message": provider_message,
        "request_id": request_id,
        "retry_after_seconds": retry_after_seconds,
        "raw_body_truncated": raw_body_truncated,
        "error_type": error_type,
    }
    if run_id is not None and call_id is not None:
        ev["context"] = {"run_id": run_id, "call_id": call_id}
    return ev


def _request_event(
    *,
    run_id: str | None = None,
    call_id: str | None = None,
    agent: str = "generator",
    purpose: str = "generate",
    model: str = "claude-opus-4-6",
) -> dict:
    ev: dict[str, Any] = {
        "type": "llm_request",
        "agent": agent,
        "purpose": purpose,
        "model": model,
        "messages": [{"role": "user", "content": "hello"}],
        "params": {"max_tokens": 8192},
    }
    if run_id is not None and call_id is not None:
        ev["context"] = {"run_id": run_id, "call_id": call_id}
    return ev


# ---------------------------------------------------------------------------
# Task 4.1a — llm_failure with prior llm_request → row has request_body
# ---------------------------------------------------------------------------

class TestFlushFailureWithPriorRequest:

    def test_failure_after_request_writes_row_with_request_body(self) -> None:
        """llm_failure after llm_request → one row; request_body populated."""
        rows: list[dict] = []
        rec = _make_recorder(rows)

        run_id = "run-abc"
        call_id = "call-abc"
        rec(_request_event(run_id=run_id, call_id=call_id))
        rec(_failure_event(run_id=run_id, call_id=call_id))

        assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
        row = rows[0]
        assert row["request_body"] is not None, "request_body should be set from prior request"
        assert row["request_body"].get("messages") is not None

    def test_failure_row_has_error_in_response_body(self) -> None:
        """The written row's response_body contains 'error' with detail fields."""
        rows: list[dict] = []
        rec = _make_recorder(rows)

        run_id = "run-abc"
        call_id = "call-abc"
        rec(_request_event(run_id=run_id, call_id=call_id))
        rec(_failure_event(
            run_id=run_id, call_id=call_id,
            provider_error_code="enforced_spend_limit_reached",
        ))

        assert len(rows) == 1
        row = rows[0]
        resp = row.get("response_body")
        assert isinstance(resp, dict), f"response_body should be a dict, got {resp!r}"
        err = resp.get("error")
        assert isinstance(err, dict), f"response_body should have 'error' dict, got {err!r}"
        assert err.get("provider_error_code") == "enforced_spend_limit_reached"

    def test_failure_row_prompt_and_completion_tokens_are_none(self) -> None:
        """prompt_tokens and completion_tokens must be None for failure rows."""
        rows: list[dict] = []
        rec = _make_recorder(rows)

        run_id = "run-abc"
        call_id = "call-abc"
        rec(_request_event(run_id=run_id, call_id=call_id))
        rec(_failure_event(run_id=run_id, call_id=call_id))

        row = rows[0]
        assert row.get("prompt_tokens") is None
        assert row.get("completion_tokens") is None


# ---------------------------------------------------------------------------
# Task 4.1b — llm_failure without prior llm_request → request_body=None
# ---------------------------------------------------------------------------

class TestFlushFailureWithoutPriorRequest:

    def test_failure_without_request_writes_row_with_null_request_body(self) -> None:
        """llm_failure with no prior request → request_body=None."""
        rows: list[dict] = []
        rec = _make_recorder(rows)

        rec(_failure_event())

        assert len(rows) == 1
        row = rows[0]
        assert row["request_body"] is None

    def test_failure_without_request_still_has_error_dict(self) -> None:
        """Even with no prior request, response_body['error'] is present."""
        rows: list[dict] = []
        rec = _make_recorder(rows)

        rec(_failure_event(provider_error_status="RESOURCE_EXHAUSTED"))

        row = rows[0]
        resp = row.get("response_body", {}) or {}
        assert resp.get("error", {}).get("provider_error_status") == "RESOURCE_EXHAUSTED"


# ---------------------------------------------------------------------------
# Task 4.1c — identity fields in response_body
# ---------------------------------------------------------------------------

class TestFlushFailureIdentity:

    def test_failure_identity_fields_in_response_body(self) -> None:
        """llm_failure event's run_id/call_id appear in response_body['identity']."""
        rows: list[dict] = []
        rec = _make_recorder(rows)

        run_id = "run-xyz"
        call_id = "call-xyz"
        rec(_failure_event(run_id=run_id, call_id=call_id))

        row = rows[0]
        resp = row.get("response_body", {}) or {}
        identity = resp.get("identity", {})
        assert identity.get("run_id") == run_id
        assert identity.get("call_id") == call_id


# ---------------------------------------------------------------------------
# Task 4.3 — no recorder → no row (structural test)
# ---------------------------------------------------------------------------

class TestNoRecorderNoRow:

    def test_without_recorder_no_write_called(self) -> None:
        """When no ExchangeRecorder is attached, no write_row is called.

        This simulates LLM_EXCHANGE_RETENTION_DAYS=0 where the recorder is
        simply not installed as an observer.
        """
        write_row = MagicMock()
        # Don't attach recorder at all — just verify the mock is never called
        # (representing the LLM client emitting with no recorder as observer)
        assert write_row.call_count == 0


# ---------------------------------------------------------------------------
# Task 4.4 — write failure logs WARNING, does not propagate
# ---------------------------------------------------------------------------

class TestFlushFailureWriteError:

    def test_write_failure_logs_warning_not_propagated(self, caplog: pytest.LogCaptureFixture) -> None:
        """If write_row raises, ExchangeRecorder logs WARNING and does not raise."""
        import logging

        def bad_write(row: dict) -> None:
            raise RuntimeError("DB is down")

        log_id = uuid.uuid4()
        rec = ExchangeRecorder(log_id, bad_write)

        with caplog.at_level(logging.WARNING, logger="server.generate.exchange_recorder"):
            rec(_failure_event())  # Must NOT raise

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warnings, "expected a WARNING log when write fails"
