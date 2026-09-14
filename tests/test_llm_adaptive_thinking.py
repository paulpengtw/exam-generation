"""Opus 4.6 thinking at the SDK and observer boundaries (issue #758)."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.config import Config
from src.llm_client import LLMClient

OPUS = "claude-opus-4-6"
TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]


class FakeMessagesAPI:
    def __init__(self, blocks: list | None = None, pause_once: bool = False) -> None:
        self.calls: list[dict] = []
        self.blocks = blocks or [SimpleNamespace(type="text", text='{"ok": true}')]
        self.pause_once = pause_once

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=self.blocks,
            stop_reason="pause_turn" if self.pause_once and len(self.calls) == 1 else "end_turn",
            usage=SimpleNamespace(input_tokens=12, output_tokens=8),
        )

    @contextmanager
    def stream(self, **kwargs):
        final = self.create(**kwargs)
        events = [
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="thinking_delta", thinking="思考摘要"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text='{"ok": true}'),
            ),
        ]

        class Stream:
            def __iter__(self):
                return iter(events)

            def get_final_message(self):
                return final

        yield Stream()


def make_client(
    model: str = OPUS, *, streaming: bool = False, blocks: list | None = None,
) -> tuple[LLMClient, FakeMessagesAPI, list[dict]]:
    client = LLMClient(Config(
        api_key="test-only", model_execute=model, model_plan=model,
        model_verify=model, model_correct=model, llm_stream=streaming,
        rate_limit_delay=0, effort_execute="high", effort_plan="high",
    ))
    fake = FakeMessagesAPI(blocks)
    client.client = SimpleNamespace(messages=fake)
    events: list[dict] = []
    client.set_observer(events.append)
    return client, fake, events


def invoke(client: LLMClient, call_site: str) -> None:
    if call_site == "tools":
        client.generate_with_tools("system", "user", tools=TOOLS, purpose="fact_check")
    else:
        client.generate("system", "user")


@pytest.mark.parametrize("call_site", ["non_streaming", "streaming", "tools"])
@pytest.mark.parametrize("model, max_tokens, thinking", [
    (OPUS, 16384, {"type": "adaptive"}),
    ("claude-opus-5", 8192, None),
    ("claude-sonnet-4-6", 8192, None),
    ("unknown-proxy-model", 8192, None),
    ("claude-opus-4-6-proxy", 8192, None),
])
def test_model_policy_reaches_every_anthropic_call_site(
    call_site: str, model: str, max_tokens: int, thinking: dict | None,
) -> None:
    """A missing call-site hook or a broadened roster changes the actual SDK request."""
    client, fake, _ = make_client(model, streaming=call_site == "streaming")
    invoke(client, call_site)
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["model"] == model
    assert call["max_tokens"] == max_tokens
    if thinking is None:
        assert "thinking" not in call
    else:
        assert call["thinking"] == thinking  # no display or budget_tokens


@pytest.mark.parametrize("call_site", ["non_streaming", "streaming", "tools"])
def test_observer_records_effective_thinking_and_output_ceiling(call_site: str) -> None:
    client, _, events = make_client(streaming=call_site == "streaming")
    invoke(client, call_site)
    request = next(event for event in events if event["type"] == "llm_request")
    assert request["params"]["thinking"] == {"type": "adaptive"}
    assert request["params"]["max_tokens"] == 16384


@pytest.mark.parametrize("call_site", ["non_streaming", "streaming", "tools"])
def test_adaptive_thinking_omits_incompatible_temperature(call_site: str, caplog) -> None:
    """A configured temperature must not cause thinking-enabled requests to fail."""
    client, fake, events = make_client(streaming=call_site == "streaming")
    client.config.temperature = 0.7
    invoke(client, call_site)
    assert fake.calls[0]["thinking"] == {"type": "adaptive"}
    assert "temperature" not in fake.calls[0]
    assert "LLM_TEMPERATURE ignored for claude-opus-4-6" in caplog.text
    request = next(event for event in events if event["type"] == "llm_request")
    assert request["params"]["temperature"] is None


def test_proxy_outside_exact_thinking_roster_keeps_temperature() -> None:
    client, fake, _ = make_client("claude-opus-4-6-proxy")
    client.config.temperature = 0.7
    client.generate("system", "user")
    assert fake.calls[0]["temperature"] == 0.7
    assert "thinking" not in fake.calls[0]


def test_streamed_thinking_reaches_existing_reasoning_event() -> None:
    client, fake, events = make_client(streaming=True)
    result = client.generate_json(
        "system", "user", purpose="plan_core_questions", agent_override="planner",
    )
    assert fake.calls[0].get("thinking") == {"type": "adaptive"}
    assert result == {"ok": True}
    assert [event for event in events if event["type"] == "llm_reasoning_delta"] == [{
        "type": "llm_reasoning_delta", "purpose": "plan_core_questions",
        "agent": "planner", "text": "思考摘要",
    }]
    response = events[-1]
    assert response["content"] == '{"ok": true}'
    assert response["reasoning"] == "思考摘要"
    assert response["usage"]["output"] == 8


@pytest.mark.parametrize("attach_observer", [False, True])
def test_non_streaming_json_skips_thinking_and_redacted_blocks(attach_observer: bool) -> None:
    client, _, events = make_client(blocks=[
        SimpleNamespace(type="thinking", thinking="思考摘要", signature="signed"),
        SimpleNamespace(type="redacted_thinking", data="encrypted"),
        SimpleNamespace(type="text", text='{"ok":'),
        SimpleNamespace(type="text", text=" true}"),
    ])
    if not attach_observer:
        client.clear_observer()
    assert client.generate_json("system", "user") == {"ok": True}
    if attach_observer:
        assert events[-1]["content"] == '{"ok": true}'
        assert events[-1]["reasoning"] == "思考摘要"


def test_server_tool_continuation_preserves_thinking_blocks_and_policy() -> None:
    blocks = [SimpleNamespace(type="thinking", thinking="摘要", signature="signed")]
    client, fake, _ = make_client(blocks=blocks)
    fake.pause_once = True
    client.generate_with_tools("system", "user", tools=TOOLS, purpose="fact_check")
    assert len(fake.calls) == 2
    for call in fake.calls:
        assert call.get("thinking") == {"type": "adaptive"}
        assert call["max_tokens"] == 16384
    assert fake.calls[1]["messages"][-1] == {"role": "assistant", "content": blocks}


@pytest.mark.parametrize("purpose", ["generate", "verify", "correct", "plan"])
def test_effective_model_override_selects_thinking(purpose: str) -> None:
    client, fake, _ = make_client("claude-sonnet-4-6")
    if purpose == "plan":
        client.config.model_plan = OPUS
        client.plan("system", "user")
    else:
        client.generate("system", "user", model=OPUS, purpose=purpose)
    assert fake.calls[0].get("thinking") == {"type": "adaptive"}
    assert fake.calls[0]["max_tokens"] == 16384


@pytest.mark.parametrize("model, provider, token_key", [
    ("gemini-3.1-pro-preview", "gemini", "max_tokens"),
    ("gpt-5.2", "openai", "max_completion_tokens"),
])
@pytest.mark.parametrize("streaming", [False, True])
def test_compat_requests_never_receive_anthropic_thinking(
    model: str, provider: str, token_key: str, streaming: bool,
) -> None:
    client, _, _ = make_client(streaming=streaming)
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        if streaming:
            return iter([SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="{}"))], usage=None,
            )])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))], usage=None,
        )

    client._compat_clients[provider] = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    assert client.generate("system", "user", model=model) == "{}"
    assert len(calls) == 1
    assert "thinking" not in calls[0]
    assert "thinking" not in calls[0].get("extra_body", {})
    assert calls[0][token_key] == 8192
