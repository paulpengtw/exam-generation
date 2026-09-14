"""Issue #802: SDK options survive observer and exchange readback unchanged."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras")
# ruff: noqa: E402

from server.generate import persistence
from src.config import Config
from src.llm_client import LLMClient
from tests.server.test_exchange_persistence_integration import exchange_store

_EXPECTED_OPTIONS = {
    "anthropic": {
        "thinking": {"type": "adaptive"},
        "max_tokens": 16384,
        "extra_body": {"output_config": {"effort": "high"}},
    },
    "gemini": {
        "max_tokens": 8192,
        "reasoning_effort": "high",
    },
    "openai": {
        "max_completion_tokens": 8192,
        "reasoning_effort": "high",
    },
}


class _RecordingCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            usage=SimpleNamespace(
                prompt_tokens=2,
                completion_tokens=1,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
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
                            prompt_tokens=2,
                            completion_tokens=1,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
                        ),
                    ),
                ]
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            usage=SimpleNamespace(
                prompt_tokens=2,
                completion_tokens=1,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
        )


class _OpenAICompatSdk:
    def __init__(self, completions: _RecordingCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


class _RecordingAnthropicMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"ok": true}')],
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        )

    @contextmanager
    def stream(self, **kwargs):
        final = self.create(**kwargs)
        events = [
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text='{"ok": true}'),
            )
        ]

        class _Stream:
            def __iter__(self):
                return iter(events)

            def get_final_message(self):
                return final

        yield _Stream()


@pytest.mark.parametrize("provider", ["anthropic", "gemini", "openai"])
@pytest.mark.parametrize("streaming", [False, True])
def test_effective_sdk_options_survive_authenticated_exchange_readback(
    provider: str, streaming: bool, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            result = await asyncio.to_thread(
                _generate_and_record,
                provider,
                streaming,
                store.log_id,
                asyncio.get_running_loop(),
                store.sessions,
                monkeypatch,
            )
            rows = await store.exchanges()

            assert len(rows) == 1
            assert rows[0]["request_body"]["params"] == result["sdk_options"]
            assert result["request_event"]["params"] == result["sdk_options"]
            expected = dict(_EXPECTED_OPTIONS[provider])
            if streaming and provider in {"gemini", "openai"}:
                expected.update({
                    "stream": True,
                    "stream_options": {"include_usage": True},
                })
            assert result["sdk_options"] == expected

    asyncio.run(exercise())


def _generate_and_record(
    provider: str,
    streaming: bool,
    log_id,
    loop,
    sessions,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    events: list[dict] = []
    if provider == "gemini":
        completions = _StreamingCompletions() if streaming else _RecordingCompletions()
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
                llm_stream=streaming,
            )
        )
        sdk_calls = completions.calls
        sdk_messages = {"model", "messages"}
    elif provider == "openai":
        completions = _StreamingCompletions() if streaming else _RecordingCompletions()
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
                llm_stream=streaming,
            )
        )
        sdk_calls = completions.calls
        sdk_messages = {"model", "messages"}
    else:
        messages = _RecordingAnthropicMessages()
        client = LLMClient(
            Config(
                api_key="test-key",
                model_execute="claude-opus-4-6",
                effort_execute="high",
                llm_stream=streaming,
            )
        )
        client.client = SimpleNamespace(messages=messages)
        sdk_calls = messages.calls
        sdk_messages = {"model", "system", "messages"}

    recorder = persistence.make_exchange_recorder(
        generation_log_id=log_id,
        retention_days=30,
        loop=loop,
        session_factory=sessions,
        next_order=lambda: 1,
    )
    assert recorder is not None

    def observe(event: dict) -> None:
        events.append(event)
        recorder(event)

    client.set_observer(observe)
    assert client.generate("system", "user") == '{"ok": true}'
    sdk_options = {
        key: value for key, value in sdk_calls[0].items() if key not in sdk_messages
    }

    return {
        "sdk_options": sdk_options,
        "request_event": next(event for event in events if event["type"] == "llm_request"),
    }
