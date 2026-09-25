from __future__ import annotations

import uuid
from types import SimpleNamespace

from server.generate.exchange_recorder import ExchangeRecorder
from src.common.generation_events import QuestionContext, new_operation_scope
from src.config import Config
from src.llm_client import LLMClient


def _response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(
            prompt_tokens=3,
            completion_tokens=2,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        ),
    )


def test_json_resend_gets_a_new_call_in_the_same_operation() -> None:
    client = LLMClient(Config(api_key="x", openai_api_key="o", llm_stream=False))
    events: list[dict] = []
    client.set_observer(events.append)
    responses = iter([_response("not json"), _response('{"ok": true}')])
    client._compat_clients["openai"] = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: next(responses)))
    )
    scope = new_operation_scope(
        QuestionContext(run_id="RUN", question_id="q-1", index=0),
        kind="text",
    )

    assert client.generate_json("sys", "user", model="gpt-4o", scope=scope) == {"ok": True}

    requests = [event for event in events if event["type"] == "llm_request"]
    responses_seen = [event for event in events if event["type"] == "llm_response"]
    assert len(requests) == len(responses_seen) == 2
    assert {event["operation_id"] for event in requests} == {scope.operation_id}
    assert len({event["call_id"] for event in requests}) == 2
    assert requests[1]["retry_of_call_id"] == requests[0]["call_id"]
    assert all(event["operation_id"] == scope.operation_id for event in responses_seen)
    assert all(event["call_id"] in {r["call_id"] for r in requests} for event in responses_seen)


def test_provider_failure_has_the_same_call_identity() -> None:
    client = LLMClient(Config(api_key="x", openai_api_key="o", llm_stream=False))
    events: list[dict] = []
    client.set_observer(events.append)

    def fail(**_: object) -> None:
        raise RuntimeError("provider unavailable")

    client._compat_clients["openai"] = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fail))
    )
    scope = new_operation_scope(
        QuestionContext(run_id="RUN", question_id="q-1", index=0),
        kind="text",
    )

    try:
        client.generate("sys", "user", model="gpt-4o", scope=scope)
    except RuntimeError:
        pass
    else:  # pragma: no cover - assertion gives a clearer failure
        raise AssertionError("provider failure must be re-raised")

    request = next(event for event in events if event["type"] == "llm_request")
    failure = next(event for event in events if event["type"] == "llm_failure")
    assert failure["operation_id"] == request["operation_id"] == scope.operation_id
    assert failure["call_id"] == request["call_id"]


def test_tool_continuations_get_distinct_calls_in_one_operation() -> None:
    client = LLMClient(Config(api_key="x", llm_stream=False))
    events: list[dict] = []
    client.set_observer(events.append)
    responses = iter([
        SimpleNamespace(
            stop_reason="pause_turn",
            content=[SimpleNamespace(type="text", text="查詢中…", citations=[])],
        ),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="完成", citations=[])],
        ),
    ])
    client.client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **_: next(responses)),
    )
    scope = new_operation_scope(
        QuestionContext(run_id="RUN", question_id="q-1", index=0),
        kind="fact_check",
    )

    text, _ = client.generate_with_tools(
        "sys",
        "user",
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        purpose="fact_check",
        scope=scope,
    )

    assert text == "查詢中…完成"
    requests = [event for event in events if event["type"] == "llm_request"]
    responses_seen = [event for event in events if event["type"] == "llm_response"]
    assert len(requests) == len(responses_seen) == 2
    assert {event["operation_id"] for event in requests} == {scope.operation_id}
    assert len({event["call_id"] for event in requests}) == 2
    assert {event["call_id"] for event in responses_seen} == {
        event["call_id"] for event in requests
    }


def test_unscoped_modification_client_keeps_legacy_events_and_exchange_pairing() -> None:
    client = LLMClient(Config(api_key="x", openai_api_key="o", llm_stream=False))
    events: list[dict] = []
    rows: list[dict] = []
    recorder = ExchangeRecorder(uuid.uuid4(), rows.append)

    def observe(event: dict) -> None:
        events.append(event)
        recorder(event)

    client.set_observer(observe)
    client._compat_clients["openai"] = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_: _response('{"ok": true}')
            )
        )
    )

    assert client.generate_json(
        "sys", "user", model="gpt-4o", purpose="correct"
    ) == {"ok": True}

    assert [event["type"] for event in events] == ["llm_request", "llm_response"]
    assert all(
        key not in event
        for event in events
        for key in ("run_id", "operation_id", "call_id", "retry_of_call_id")
    )
    assert len(rows) == 1
    assert rows[0]["agent"] == "corrector"
    assert rows[0]["request_body"]["messages"][1]["content"] == "user"
    assert rows[0]["response_body"]["content"] == '{"ok": true}'
    assert all(
        key not in rows[0]
        for key in ("run_id", "operation_id", "call_id", "retry_of_call_id")
    )
    assert "identity" not in rows[0]["request_body"]
    assert "identity" not in rows[0]["response_body"]
