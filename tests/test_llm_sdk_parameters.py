"""Public LLMClient SDK and exchange-parameter contracts for issue #802."""

from __future__ import annotations

from types import SimpleNamespace

from src.config import Config
from src.llm_client import LLMClient


class _RecordingCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            usage=None,
        )


class _GroundingCompletions(_RecordingCompletions):
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"verified": true}'))],
            usage=None,
        )


class _StreamingCompletions(_RecordingCompletions):
    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    reasoning_content=None,
                                    content='{"ok": true}',
                                )
                            )
                        ],
                        usage=None,
                    ),
                    SimpleNamespace(
                        choices=[],
                        usage=SimpleNamespace(
                            prompt_tokens=1,
                            completion_tokens=1,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
                        ),
                    ),
                ]
            )
        return super().create(**kwargs)


class _OpenAICompatSdk:
    def __init__(self, completions: _RecordingCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


class _AnthropicMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"verified": true}')],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


def test_gemini_exchange_params_match_non_streaming_sdk_options(monkeypatch) -> None:
    """The observed params are the effective options sent to Gemini."""
    completions = _RecordingCompletions()
    monkeypatch.setattr(
        "src.llm_client.OpenAI",
        lambda **_kwargs: _OpenAICompatSdk(completions),
    )
    client = LLMClient(
        Config(
            api_key="test-key",
            gemini_api_key="gemini-key",
            model_execute="gemini-3.1-pro-preview",
            effort_execute="high",
            temperature=None,
            llm_stream=False,
        )
    )
    events: list[dict] = []
    client.set_observer(events.append)

    assert client.generate("system", "user") == '{"ok": true}'

    sdk_call = completions.calls[0]
    sdk_options = {
        key: value for key, value in sdk_call.items() if key not in {"model", "messages"}
    }
    request = next(event for event in events if event["type"] == "llm_request")
    assert request["params"] == sdk_options


def test_anthropic_tool_exchange_params_match_sdk_options() -> None:
    """Tool-enabled Anthropic calls observe effort and adaptive thinking exactly."""
    messages = _AnthropicMessages()
    client = LLMClient(
        Config(
            api_key="test-key",
            model_execute="claude-opus-4-6",
            model_verify="claude-opus-4-6",
            effort_execute="medium",
            effort_verify="high",
            temperature=0.7,
            llm_stream=False,
        )
    )
    client.client = SimpleNamespace(messages=messages)
    events: list[dict] = []
    client.set_observer(events.append)
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]

    assert client.generate_with_tools("system", "user", tools, purpose="fact_check")[0]

    sdk_call = messages.calls[0]
    sdk_options = {
        key: value
        for key, value in sdk_call.items()
        if key not in {"model", "system", "messages"}
    }
    request = next(event for event in events if event["type"] == "llm_request")
    assert request["params"] == sdk_options


def test_gemini_grounding_exchange_params_match_sdk_options(monkeypatch) -> None:
    """Gemini grounding observes reasoning effort and omitted temperature."""
    completions = _GroundingCompletions()
    monkeypatch.setattr(
        "src.llm_client.OpenAI",
        lambda **_kwargs: _OpenAICompatSdk(completions),
    )
    client = LLMClient(
        Config(
            api_key="test-key",
            gemini_api_key="gemini-key",
            model_execute="claude-sonnet-4-6",
            model_verify="gemini-3.1-pro-preview",
            effort_execute="low",
            effort_verify="high",
            temperature=0.7,
            llm_stream=False,
        )
    )
    events: list[dict] = []
    client.set_observer(events.append)

    assert client.generate_with_google_search("system", "user")[0]

    sdk_call = completions.calls[0]
    sdk_options = {
        key: value for key, value in sdk_call.items() if key not in {"model", "messages"}
    }
    request = next(event for event in events if event["type"] == "llm_request")
    assert request["params"] == sdk_options


def test_gemini_streaming_exchange_params_match_sdk_options(monkeypatch) -> None:
    """Streaming observes the same provider and transport options sent to the SDK."""
    completions = _StreamingCompletions()
    monkeypatch.setattr(
        "src.llm_client.OpenAI",
        lambda **_kwargs: _OpenAICompatSdk(completions),
    )
    client = LLMClient(
        Config(
            api_key="test-key",
            gemini_api_key="gemini-key",
            model_execute="gemini-3.1-pro-preview",
            effort_execute="high",
            temperature=None,
            llm_stream=True,
        )
    )
    events: list[dict] = []
    client.set_observer(events.append)

    assert client.generate("system", "user") == '{"ok": true}'

    sdk_call = completions.calls[0]
    sdk_options = {
        key: value
        for key, value in sdk_call.items()
        if key not in {"model", "messages"}
    }
    request = next(event for event in events if event["type"] == "llm_request")
    assert request["params"] == sdk_options
    assert sdk_options == {
        "max_tokens": 8192,
        "reasoning_effort": "high",
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def test_openai_exchange_params_use_completion_token_name_and_omit_temperature(
    monkeypatch,
) -> None:
    """OpenAI reasoning calls expose max_completion_tokens exactly as dispatched."""
    completions = _RecordingCompletions()
    monkeypatch.setattr(
        "src.llm_client.OpenAI",
        lambda **_kwargs: _OpenAICompatSdk(completions),
    )
    client = LLMClient(
        Config(
            api_key="test-key",
            openai_api_key="openai-key",
            model_execute="gpt-5.2",
            effort_execute="high",
            temperature=0.7,
            llm_stream=False,
        )
    )
    events: list[dict] = []
    client.set_observer(events.append)

    assert client.generate("system", "user") == '{"ok": true}'

    sdk_call = completions.calls[0]
    sdk_options = {
        key: value for key, value in sdk_call.items() if key not in {"model", "messages"}
    }
    request = next(event for event in events if event["type"] == "llm_request")
    assert request["params"] == sdk_options
    assert sdk_options == {
        "max_completion_tokens": 8192,
        "reasoning_effort": "high",
    }


def test_verify_tier_empty_overrides_inherit_execute_options(monkeypatch) -> None:
    """An empty verify tier follows the effective execute model and effort."""
    completions = _RecordingCompletions()
    monkeypatch.setattr(
        "src.llm_client.OpenAI",
        lambda **_kwargs: _OpenAICompatSdk(completions),
    )
    client = LLMClient(
        Config(
            api_key="test-key",
            gemini_api_key="gemini-key",
            model_execute="gemini-3.1-pro-preview",
            model_verify="",
            effort_execute="medium",
            effort_verify="",
            llm_stream=False,
        )
    )
    events: list[dict] = []
    client.set_observer(events.append)

    assert client.generate("system", "user", purpose="verify") == '{"ok": true}'

    request = next(event for event in events if event["type"] == "llm_request")
    assert request["model"] == "gemini-3.1-pro-preview"
    assert request["params"] == {
        "max_tokens": 8192,
        "reasoning_effort": "medium",
    }


def test_verify_tier_explicit_effort_override_reaches_sdk_and_observer(monkeypatch) -> None:
    """A non-empty verify effort overrides the execute tier in both surfaces."""
    completions = _RecordingCompletions()
    monkeypatch.setattr(
        "src.llm_client.OpenAI",
        lambda **_kwargs: _OpenAICompatSdk(completions),
    )
    client = LLMClient(
        Config(
            api_key="test-key",
            gemini_api_key="gemini-key",
            model_execute="gemini-3.1-pro-preview",
            model_verify="gemini-3.1-pro-preview",
            effort_execute="low",
            effort_verify="high",
            llm_stream=False,
        )
    )
    events: list[dict] = []
    client.set_observer(events.append)

    assert client.generate("system", "user", purpose="verify") == '{"ok": true}'

    request = next(event for event in events if event["type"] == "llm_request")
    assert request["params"] == {
        "max_tokens": 8192,
        "reasoning_effort": "high",
    }
    assert {
        key: value
        for key, value in completions.calls[0].items()
        if key not in {"model", "messages"}
    } == request["params"]


def test_unsupported_gemini_effort_is_dropped_with_temperature_omitted(monkeypatch) -> None:
    """Unsupported effort and sampling options are both absent from the request."""
    completions = _RecordingCompletions()
    monkeypatch.setattr(
        "src.llm_client.OpenAI",
        lambda **_kwargs: _OpenAICompatSdk(completions),
    )
    client = LLMClient(
        Config(
            api_key="test-key",
            gemini_api_key="gemini-key",
            model_execute="gemini-3.1-pro-preview",
            effort_execute="max",
            temperature=0.7,
            llm_stream=False,
        )
    )
    events: list[dict] = []
    client.set_observer(events.append)

    assert client.generate("system", "user") == '{"ok": true}'

    expected = {"max_tokens": 8192}
    request = next(event for event in events if event["type"] == "llm_request")
    assert request["params"] == expected
    assert {
        key: value
        for key, value in completions.calls[0].items()
        if key not in {"model", "messages"}
    } == expected
