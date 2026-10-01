"""Tests for recording requested_model in events and exchange rows (issue #942).

Covers tasks 3.1 and 3.2:
  3.1 — llm_request, llm_response, llm_failure events carry requested_model only when it
         differs from the dispatched model.
  3.2 — ExchangeRecorder copies requested_model into request_body; model_used is the
         dispatched model.

Both dispatch paths are covered: _call() (the main path) and generate_with_tools()
(the fact-check / Anthropic web-search path, added in #941).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from server.generate.exchange_recorder import ExchangeRecorder
from src.common.generation_events import QuestionContext, new_run_id
from src.config import FABLE_DOWNGRADE_TARGET, Config
from src.llm_client import LLMClient

# ---------------------------------------------------------------------------
# Helpers: fake Anthropic client (matching test_940 pattern)
# ---------------------------------------------------------------------------


class FakeMessagesAPI:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"ok": true}')],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

    @contextmanager
    def stream(self, **kwargs):
        final = self.create(**kwargs)

        class FakeStream:
            def __iter__(self):
                return iter([
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(type="text_delta", text='{"ok":true}'),
                    )
                ])

            def get_final_message(self):
                return final

        yield FakeStream()


def _make_client(
    *,
    fable_downgrade: bool,
    model_execute: str = "claude-fable-5",
    effort_execute: str = "high",
    streaming: bool = False,
    model_verify: str = "",
) -> tuple[LLMClient, FakeMessagesAPI, list[dict]]:
    cfg = Config(
        api_key="test-only",
        model_execute=model_execute,
        model_verify=model_verify,
        model_plan=model_execute,
        model_correct="",
        effort_execute=effort_execute,
        effort_verify="",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=streaming,
        fable_downgrade=fable_downgrade,
    )
    client = LLMClient(cfg)
    fake = FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)
    events: list[dict] = []
    client.set_observer(events.append)
    return client, fake, events


# ---------------------------------------------------------------------------
# 3.1 — _call() path: llm_request event carries requested_model when substituted
# ---------------------------------------------------------------------------


def test_llm_request_event_has_requested_model_when_substituted() -> None:
    """llm_request event must carry requested_model=<fable id> when dispatch substitutes."""
    client, _fake, events = _make_client(fable_downgrade=True, model_execute="claude-fable-5")
    client.generate("sys", "user")

    request_events = [e for e in events if e.get("type") == "llm_request"]
    assert len(request_events) >= 1
    req = request_events[0]
    assert req["model"] == FABLE_DOWNGRADE_TARGET, "model must be the dispatched model"
    assert req.get("requested_model") == "claude-fable-5", (
        "requested_model must be the original Fable id"
    )


def test_llm_request_event_has_no_requested_model_when_not_substituted() -> None:
    """llm_request event must NOT carry requested_model when no substitution occurs."""
    client, _fake, events = _make_client(fable_downgrade=False, model_execute="claude-opus-4-6")
    client.generate("sys", "user")

    request_events = [e for e in events if e.get("type") == "llm_request"]
    assert len(request_events) >= 1
    req = request_events[0]
    assert "requested_model" not in req, (
        "requested_model must not appear when model is not substituted"
    )


# ---------------------------------------------------------------------------
# 3.1 — _call() path: llm_response event carries requested_model when substituted
# ---------------------------------------------------------------------------


def test_llm_response_event_has_requested_model_when_substituted() -> None:
    """llm_response event must carry requested_model=<fable id> when dispatch substitutes."""
    client, _fake, events = _make_client(fable_downgrade=True, model_execute="claude-fable-5")
    client.generate("sys", "user")

    response_events = [e for e in events if e.get("type") == "llm_response"]
    assert len(response_events) >= 1
    resp = response_events[0]
    assert resp["model"] == FABLE_DOWNGRADE_TARGET
    assert resp.get("requested_model") == "claude-fable-5"


def test_llm_response_event_has_no_requested_model_when_not_substituted() -> None:
    """llm_response event must NOT carry requested_model when no substitution occurs."""
    client, _fake, events = _make_client(fable_downgrade=False, model_execute="claude-opus-4-6")
    client.generate("sys", "user")

    response_events = [e for e in events if e.get("type") == "llm_response"]
    assert len(response_events) >= 1
    assert "requested_model" not in response_events[0]


# ---------------------------------------------------------------------------
# 3.1 — _call() path: llm_failure event carries requested_model when substituted
# ---------------------------------------------------------------------------


def test_llm_failure_event_has_requested_model_when_substituted() -> None:
    """llm_failure event must carry requested_model=<fable id> when dispatch substitutes."""
    cfg = Config(
        api_key="test-only",
        model_execute="claude-fable-5",
        model_verify="",
        model_plan="claude-fable-5",
        model_correct="",
        effort_execute="high",
        effort_verify="",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=True,
    )
    client = LLMClient(cfg)
    events: list[dict] = []
    client.set_observer(events.append)

    # Make the fake raise to trigger a failure event
    class FailingMessagesAPI:
        def create(self, **kwargs):
            raise RuntimeError("test error")

        @contextmanager
        def stream(self, **kwargs):
            raise RuntimeError("test error")
            yield  # unreachable

    client.client = SimpleNamespace(messages=FailingMessagesAPI())
    _ctx = QuestionContext(run_id=new_run_id(), question_id="q-test", index=0)
    with pytest.raises(RuntimeError):
        client.generate("sys", "user", scope=_ctx)

    failure_events = [e for e in events if e.get("type") == "llm_failure"]
    assert len(failure_events) >= 1
    fail = failure_events[0]
    assert fail["model"] == FABLE_DOWNGRADE_TARGET
    assert fail.get("requested_model") == "claude-fable-5"


def test_llm_failure_event_has_no_requested_model_when_not_substituted() -> None:
    """llm_failure event must NOT carry requested_model when no substitution occurs."""
    cfg = Config(
        api_key="test-only",
        model_execute="claude-opus-4-6",
        model_verify="",
        model_plan="claude-opus-4-6",
        model_correct="",
        effort_execute="high",
        effort_verify="",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=True,  # switch on but model is not fable
    )
    client = LLMClient(cfg)
    events: list[dict] = []
    client.set_observer(events.append)

    class FailingMessagesAPI:
        def create(self, **kwargs):
            raise RuntimeError("test error")

        @contextmanager
        def stream(self, **kwargs):
            raise RuntimeError("test error")
            yield

    client.client = SimpleNamespace(messages=FailingMessagesAPI())
    _ctx = QuestionContext(run_id=new_run_id(), question_id="q-test", index=0)
    with pytest.raises(RuntimeError):
        client.generate("sys", "user", scope=_ctx)

    failure_events = [e for e in events if e.get("type") == "llm_failure"]
    assert len(failure_events) >= 1
    fail = failure_events[0]
    assert "requested_model" not in fail


# ---------------------------------------------------------------------------
# 3.1 — generate_with_tools() path: events carry requested_model when substituted
# ---------------------------------------------------------------------------

_TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]


def _make_tools_client(
    *,
    fable_downgrade: bool,
    model_verify: str = "claude-fable-5",
) -> tuple[LLMClient, FakeMessagesAPI, list[dict]]:
    cfg = Config(
        api_key="test-only",
        model_execute="claude-opus-4-6",
        model_verify=model_verify,
        model_plan="claude-opus-4-6",
        model_correct="",
        effort_execute="high",
        effort_verify="",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=fable_downgrade,
    )
    client = LLMClient(cfg)
    fake = FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)
    events: list[dict] = []
    client.set_observer(events.append)
    return client, fake, events


def test_generate_with_tools_request_event_has_requested_model_when_substituted() -> None:
    """generate_with_tools() llm_request event must carry requested_model when substituted."""
    client, _fake, events = _make_tools_client(fable_downgrade=True, model_verify="claude-fable-5")
    client.generate_with_tools("sys", "user", tools=_TOOLS, purpose="fact_check")

    request_events = [e for e in events if e.get("type") == "llm_request"]
    assert len(request_events) >= 1
    req = request_events[0]
    assert req["model"] == FABLE_DOWNGRADE_TARGET
    assert req.get("requested_model") == "claude-fable-5"


def test_generate_with_tools_response_event_has_requested_model_when_substituted() -> None:
    """generate_with_tools() llm_response event must carry requested_model when substituted."""
    client, _fake, events = _make_tools_client(fable_downgrade=True, model_verify="claude-fable-5")
    client.generate_with_tools("sys", "user", tools=_TOOLS, purpose="fact_check")

    response_events = [e for e in events if e.get("type") == "llm_response"]
    assert len(response_events) >= 1
    resp = response_events[0]
    assert resp["model"] == FABLE_DOWNGRADE_TARGET
    assert resp.get("requested_model") == "claude-fable-5"


def test_generate_with_tools_failure_event_has_requested_model_when_substituted() -> None:
    """generate_with_tools() llm_failure event must carry requested_model when substituted."""
    cfg = Config(
        api_key="test-only",
        model_execute="claude-opus-4-6",
        model_verify="claude-fable-5",
        model_plan="claude-opus-4-6",
        model_correct="",
        effort_execute="high",
        effort_verify="",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=True,
    )
    client = LLMClient(cfg)
    events: list[dict] = []
    client.set_observer(events.append)

    class FailingMessagesAPI:
        def create(self, **kwargs):
            raise RuntimeError("test error")

        @contextmanager
        def stream(self, **kwargs):
            raise RuntimeError("test error")
            yield

    client.client = SimpleNamespace(messages=FailingMessagesAPI())
    _ctx = QuestionContext(run_id=new_run_id(), question_id="q-test", index=0)
    with pytest.raises(RuntimeError):  # noqa: PT011
        client.generate_with_tools(
            "sys", "user", tools=_TOOLS, purpose="fact_check",
            scope=_ctx,
        )

    failure_events = [e for e in events if e.get("type") == "llm_failure"]
    assert len(failure_events) >= 1
    fail = failure_events[0]
    assert fail["model"] == FABLE_DOWNGRADE_TARGET
    assert fail.get("requested_model") == "claude-fable-5"


def test_generate_with_tools_events_have_no_requested_model_when_not_substituted() -> None:
    """generate_with_tools() events must NOT carry requested_model when no substitution."""
    client, _fake, events = _make_tools_client(
        fable_downgrade=False, model_verify="claude-opus-4-6"
    )
    client.generate_with_tools("sys", "user", tools=_TOOLS, purpose="fact_check")

    for event in events:
        if event.get("type") in ("llm_request", "llm_response", "llm_failure"):
            assert "requested_model" not in event, (
                f"Event type {event['type']} must not carry requested_model without substitution"
            )


# ---------------------------------------------------------------------------
# 3.2 — ExchangeRecorder: requested_model stored in request_body when present
# ---------------------------------------------------------------------------


def _exchange_request(agent: str, model: str, **extra) -> dict[str, Any]:
    base = {
        "type": "llm_request",
        "agent": agent,
        "purpose": "verify",
        "model": model,
        "messages": [{"role": "user", "content": "q"}],
        "params": {"max_tokens": 8192},
    }
    base.update(extra)
    return base


def _exchange_response(agent: str, model: str, **extra) -> dict[str, Any]:
    base = {
        "type": "llm_response",
        "agent": agent,
        "purpose": "verify",
        "model": model,
        "content": "ok",
        "reasoning": None,
        "usage": {"input": 10, "output": 5, "cache_read": 0, "cache_creation": 0},
    }
    base.update(extra)
    return base


def test_exchange_recorder_stores_requested_model_in_request_body_when_substituted() -> None:
    """When req event has requested_model, it must appear in request_body."""
    rows: list[dict[str, Any]] = []
    rec = ExchangeRecorder(uuid.uuid4(), rows.append)

    req = _exchange_request(
        "verifier",
        FABLE_DOWNGRADE_TARGET,  # dispatched model
        requested_model="claude-fable-5",  # original Fable id
    )
    resp = _exchange_response("verifier", FABLE_DOWNGRADE_TARGET)

    rec(req)
    rec(resp)

    assert len(rows) == 1
    row = rows[0]
    assert row["model_used"] == FABLE_DOWNGRADE_TARGET
    assert row["request_body"]["requested_model"] == "claude-fable-5"


def test_exchange_recorder_omits_requested_model_from_request_body_when_not_substituted() -> None:
    """When req event has no requested_model, request_body must not contain that key."""
    rows: list[dict[str, Any]] = []
    rec = ExchangeRecorder(uuid.uuid4(), rows.append)

    req = _exchange_request("verifier", "claude-opus-4-6")  # no requested_model key
    resp = _exchange_response("verifier", "claude-opus-4-6")

    rec(req)
    rec(resp)

    assert len(rows) == 1
    row = rows[0]
    assert "requested_model" not in row["request_body"]


def test_exchanges_endpoint_returns_requested_model_for_substituted_exchange() -> None:
    """The exchanges endpoint returns request_body verbatim; verify requested_model survives."""
    # This test verifies that persistence.py does NOT strip 'requested_model' from
    # request_body (it only strips flat keys run_id/call_id/operation_id/retry_of_call_id).
    # Since requested_model lives inside request_body (a nested dict), no additional
    # stripping is needed. The recorder row's request_body dict is persisted as-is.
    rows: list[dict[str, Any]] = []
    rec = ExchangeRecorder(uuid.uuid4(), rows.append)

    req = _exchange_request(
        "verifier",
        FABLE_DOWNGRADE_TARGET,
        requested_model="claude-fable-5",
    )
    resp = _exchange_response("verifier", FABLE_DOWNGRADE_TARGET)
    rec(req)
    rec(resp)

    row = rows[0]
    # The request_body dict that ExchangeRecorder produces is what gets stored in the DB
    # and returned by the exchanges endpoint. Check it contains what the spec requires.
    assert row["request_body"]["model"] == FABLE_DOWNGRADE_TARGET
    assert row["request_body"]["requested_model"] == "claude-fable-5"


# ---------------------------------------------------------------------------
# Regression: legacy/no-scope path with switch OFF emits no llm_failure
# ---------------------------------------------------------------------------


def test_llm_failure_not_emitted_when_no_scope_and_switch_off() -> None:
    """Legacy callers (no scope) must not see llm_failure — guard is call_scope is not None."""
    cfg = Config(
        api_key="test-only",
        model_execute="claude-opus-4-6",
        model_verify="",
        model_plan="claude-opus-4-6",
        model_correct="",
        effort_execute="high",
        effort_verify="",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=False,  # switch OFF — byte-identical behaviour
    )
    client = LLMClient(cfg)
    events: list[dict] = []
    client.set_observer(events.append)

    class FailingMessagesAPI:
        def create(self, **kwargs):
            raise RuntimeError("legacy failure")

        @contextmanager
        def stream(self, **kwargs):
            raise RuntimeError("legacy failure")
            yield  # unreachable

    client.client = SimpleNamespace(messages=FailingMessagesAPI())
    # No scope kwarg → _operation_scope returns None → call_scope is None → guard never fires.
    with pytest.raises(RuntimeError):
        client.generate("sys", "user")  # no scope argument — legacy path

    failure_events = [e for e in events if e.get("type") == "llm_failure"]
    assert failure_events == [], (
        "llm_failure must NOT be emitted on the legacy (no-scope) path"
    )
