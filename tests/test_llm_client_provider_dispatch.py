"""Tests for per-call LLM provider dispatch (issue #337)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config import Config
from src.llm_client import LLMClient, resolve_provider


# ---------------------------------------------------------------------------
# 1. resolve_provider table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model,expected", [
    ("claude-sonnet-4-6", "anthropic"),
    ("claude-opus-5", "anthropic"),
    ("gemini-3.1-pro-preview", "gemini"),
    ("gemini-2.5-flash", "gemini"),
    ("gpt-4o", "openai"),
    ("gpt-5.2", "openai"),
    ("o3-mini", "openai"),
    ("o4-mini", "openai"),
    ("my-proxy-model", "anthropic"),
    ("", "anthropic"),
])
def test_resolve_provider(model: str, expected: str) -> None:
    assert resolve_provider(model) == expected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_anthropic_messages(text: str = '{"ok": true}'):
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        content_block = SimpleNamespace(text=text)
        usage = SimpleNamespace(
            input_tokens=5,
            output_tokens=3,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return SimpleNamespace(content=[content_block], usage=usage)

    ns = SimpleNamespace(create=create)
    ns._calls = calls
    return ns


def _fake_compat_completions(text: str = '{"ok": true}'):
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        msg = SimpleNamespace(content=text)
        choice = SimpleNamespace(message=msg)
        usage = SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )
        return SimpleNamespace(choices=[choice], usage=usage)

    ns = SimpleNamespace(create=create)
    ns._calls = calls
    return ns


# ---------------------------------------------------------------------------
# 2. Mixed instance: plan→anthropic, generate→gemini
# ---------------------------------------------------------------------------

def test_mixed_instance_routes_per_call() -> None:
    cfg = Config(
        api_key="x",
        gemini_api_key="g",
        llm_stream=False,
        model_plan="claude-opus-5",
        model_execute="gemini-3.1-pro-preview",
    )
    client = LLMClient(cfg)

    anthropic_msgs = _fake_anthropic_messages()
    client.client = SimpleNamespace(messages=anthropic_msgs)

    compat_fake = _fake_compat_completions()
    client._compat_clients["gemini"] = SimpleNamespace(
        chat=SimpleNamespace(completions=compat_fake)
    )

    plan_result = client.plan("sys", "user")
    assert plan_result == '{"ok": true}'
    assert len(anthropic_msgs._calls) == 1

    gen_result = client.generate("sys", "user")
    assert gen_result == '{"ok": true}'
    assert len(compat_fake._calls) == 1
    assert compat_fake._calls[0]["model"] == "gemini-3.1-pro-preview"
    # Anthropic fake was not called for the generate call
    assert len(anthropic_msgs._calls) == 1


# ---------------------------------------------------------------------------
# 3. _openai_compat_client caching and validation
# ---------------------------------------------------------------------------

def test_compat_client_returns_same_object() -> None:
    cfg = Config(api_key="x", gemini_api_key="g-key")
    client = LLMClient(cfg)
    c1 = client._openai_compat_client("gemini")
    c2 = client._openai_compat_client("gemini")
    assert c1 is c2


def test_compat_client_raises_for_missing_gemini_key() -> None:
    cfg = Config(api_key="x", gemini_api_key="")
    client = LLMClient(cfg)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        client._openai_compat_client("gemini")


def test_compat_client_raises_for_missing_openai_key() -> None:
    cfg = Config(api_key="x", openai_api_key="")
    client = LLMClient(cfg)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        client._openai_compat_client("openai")
