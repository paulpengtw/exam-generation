"""Tests for LLMClient._openai_compat_call (issue #337)."""

from __future__ import annotations

import base64
from types import SimpleNamespace

from src.config import Config
from src.llm_client import LLMClient, _openai_usage_to_internal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


class _RecordingCompletions:
    """Stands in for OpenAI.chat.completions; records create(**kwargs) calls."""

    def __init__(self, content: str | None = '{"ok": true}', usage=None) -> None:
        self.calls: list[dict] = []
        self._content = content
        self._usage = usage or SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            prompt_tokens_details=SimpleNamespace(cached_tokens=3),
        )

    def create(self, **kwargs):
        self.calls.append(kwargs)
        msg = SimpleNamespace(content=self._content)
        choice = SimpleNamespace(message=msg)
        return SimpleNamespace(choices=[choice], usage=self._usage)


def _make_compat_client(
    model: str = "gemini-3.1-pro-preview",
    content: str | None = '{"ok": true}',
    usage=None,
    temperature: float | None = None,
) -> tuple[LLMClient, _RecordingCompletions]:
    cfg = Config(
        api_key="x",
        gemini_api_key="g-key",
        openai_api_key="o-key",
        llm_stream=False,
        model_execute=model,
        temperature=temperature,
    )
    client = LLMClient(cfg)
    fake = _RecordingCompletions(content=content, usage=usage)
    provider = "gemini" if model.startswith("gemini-") else "openai"
    client._compat_clients[provider] = SimpleNamespace(
        chat=SimpleNamespace(completions=fake)
    )
    return client, fake


# ---------------------------------------------------------------------------
# 1. System message forwarded as role="system"; no separate "system" kwarg;
#    no cache_control in serialized payload
# ---------------------------------------------------------------------------

def test_system_message_forwarded_as_role_system() -> None:
    client, fake = _make_compat_client()
    client.generate("system-text", "user-text")
    assert len(fake.calls) == 1
    messages = fake.calls[0]["messages"]
    system_msgs = [m for m in messages if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0]["content"] == "system-text"


def test_no_separate_system_kwarg_in_compat_call() -> None:
    client, fake = _make_compat_client()
    client.generate("system-text", "user-text")
    assert "system" not in fake.calls[0]


def test_no_cache_control_in_compat_payload() -> None:
    client, fake = _make_compat_client()
    client.generate("system-text", "user-text")
    payload_str = str(fake.calls[0])
    assert "cache_control" not in payload_str


# ---------------------------------------------------------------------------
# 2. generate_with_image: image_url block untouched (no Anthropic-style block)
# ---------------------------------------------------------------------------

def test_generate_with_image_image_url_block_untouched(tmp_path) -> None:
    png_path = tmp_path / "img.png"
    png_path.write_bytes(_TINY_PNG_BYTES)

    client, fake = _make_compat_client()
    client.generate_with_image(
        "system-text", "user-text",
        image_path=png_path,
        model="gemini-3.1-pro-preview",
    )

    assert len(fake.calls) == 1
    messages = fake.calls[0]["messages"]
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert len(user_msgs) == 1
    content = user_msgs[0]["content"]
    assert isinstance(content, list)
    image_parts = [p for p in content if p.get("type") == "image_url"]
    assert len(image_parts) == 1
    url = image_parts[0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


# ---------------------------------------------------------------------------
# 3. Observer + llm_stream=False → correct usage, reasoning=None,
#    llm_request params == {"max_tokens": 8192, "temperature": None}
# ---------------------------------------------------------------------------

def test_observer_receives_correct_usage_and_reasoning() -> None:
    client, _ = _make_compat_client(temperature=None)

    events: list[dict] = []
    client.set_observer(events.append)

    client.generate("sys", "user")

    request_events = [e for e in events if e["type"] == "llm_request"]
    response_events = [e for e in events if e["type"] == "llm_response"]

    assert len(request_events) == 1
    assert len(response_events) == 1

    req = request_events[0]
    assert req["params"] == {"max_tokens": 8192, "temperature": None}

    resp = response_events[0]
    assert resp["usage"] == {"input": 10, "output": 5, "cache_read": 3, "cache_creation": 0}
    assert resp["reasoning"] is None


# ---------------------------------------------------------------------------
# 4. content=None → method returns ""
# ---------------------------------------------------------------------------

def test_content_none_returns_empty_string() -> None:
    client, _ = _make_compat_client(content=None)
    result = client.generate("sys", "user")
    assert result == ""


# ---------------------------------------------------------------------------
# 5. usage=None → zeroed usage dict (all four keys present)
# ---------------------------------------------------------------------------

def test_usage_none_returns_zeroed_dict() -> None:
    cfg = Config(
        api_key="x",
        gemini_api_key="g-key",
        llm_stream=False,
        model_execute="gemini-3.1-pro-preview",
    )
    c = LLMClient(cfg)

    class _NullUsageFake:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
                usage=None,
            )

    null_fake = _NullUsageFake()
    c._compat_clients["gemini"] = SimpleNamespace(
        chat=SimpleNamespace(completions=null_fake)
    )

    events: list[dict] = []
    c.set_observer(events.append)

    result = c.generate("sys", "user")
    assert result == "{}"

    response_events = [e for e in events if e["type"] == "llm_response"]
    assert len(response_events) == 1
    usage = response_events[0]["usage"]
    assert usage == {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


# ---------------------------------------------------------------------------
# 6. _openai_usage_to_internal unit tests
# ---------------------------------------------------------------------------

def test_openai_usage_to_internal_none() -> None:
    result = _openai_usage_to_internal(None)
    assert result == {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


def test_openai_usage_to_internal_normal() -> None:
    u = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=50,
        prompt_tokens_details=SimpleNamespace(cached_tokens=25),
    )
    result = _openai_usage_to_internal(u)
    assert result == {"input": 100, "output": 50, "cache_read": 25, "cache_creation": 0}


def test_openai_usage_to_internal_no_details() -> None:
    u = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=50,
        prompt_tokens_details=None,
    )
    result = _openai_usage_to_internal(u)
    assert result == {"input": 100, "output": 50, "cache_read": 0, "cache_creation": 0}
