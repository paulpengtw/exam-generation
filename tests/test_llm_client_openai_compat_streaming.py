"""Tests for LLMClient._openai_compat_streaming (issue #341)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config import Config
from src.llm_client import LLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_streaming_client(
    llm_stream: bool = True,
    attach_observer: bool = True,
) -> tuple[LLMClient, list[dict]]:
    """Return (client, events) with observer optionally attached."""
    cfg = Config(
        api_key="x",
        gemini_api_key="g",
        llm_stream=llm_stream,
        model_execute="gemini-3.1-pro-preview",
    )
    client = LLMClient(cfg)
    events: list[dict] = []
    if attach_observer:
        client.set_observer(events.append)
    return client, events


def _inject_fake(client: LLMClient, fake_create):
    """Inject fake completions object into the gemini compat slot."""
    client._compat_clients["gemini"] = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        )
    )


def _make_canonical_chunks():
    """Build the four-chunk sequence used by the main streaming test.

    Chunk 1 — reasoning only (delta.reasoning_content="思考中", content=None)
    Chunk 2 — content "前半"  (reasoning_content=None)
    Chunk 3 — content "後半"  (reasoning_content=None)
    Chunk 4 — usage-only (choices=[], usage with tokens)
    """
    delta1 = SimpleNamespace(reasoning_content="思考中", content=None)
    chunk1 = SimpleNamespace(choices=[SimpleNamespace(delta=delta1)], usage=None)

    delta2 = SimpleNamespace(reasoning_content=None, content="前半")
    chunk2 = SimpleNamespace(choices=[SimpleNamespace(delta=delta2)], usage=None)

    delta3 = SimpleNamespace(reasoning_content=None, content="後半")
    chunk3 = SimpleNamespace(choices=[SimpleNamespace(delta=delta3)], usage=None)

    chunk4 = SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=20,
            completion_tokens=7,
            prompt_tokens_details=SimpleNamespace(cached_tokens=4),
        ),
    )
    return [chunk1, chunk2, chunk3, chunk4]


# ---------------------------------------------------------------------------
# 1. Main streaming test
# ---------------------------------------------------------------------------


def test_streaming_return_value() -> None:
    """Return value is the concatenated content text."""
    client, events = _make_streaming_client(llm_stream=True)
    chunks = _make_canonical_chunks()

    def fake_create(**kwargs):
        return iter(chunks)

    _inject_fake(client, fake_create)
    result = client.generate("sys", "user", model="gemini-3.1-pro-preview")
    assert result == "前半後半"


def test_streaming_asserts_stream_kwargs() -> None:
    """fake_create must receive stream=True and stream_options."""
    client, _ = _make_streaming_client(llm_stream=True)
    chunks = _make_canonical_chunks()
    received: list[dict] = []

    def fake_create(**kwargs):
        received.append(kwargs)
        assert kwargs.get("stream") is True
        assert kwargs.get("stream_options") == {"include_usage": True}
        return iter(chunks)

    _inject_fake(client, fake_create)
    client.generate("sys", "user", model="gemini-3.1-pro-preview")
    assert received, "fake_create was not called"


def test_streaming_event_sequence_types() -> None:
    """Events: llm_request, llm_reasoning_delta, llm_content_delta x2, llm_response."""
    client, events = _make_streaming_client(llm_stream=True)
    chunks = _make_canonical_chunks()

    def fake_create(**kwargs):
        return iter(chunks)

    _inject_fake(client, fake_create)
    client.generate("sys", "user", model="gemini-3.1-pro-preview")

    types = [e["type"] for e in events]
    assert types == [
        "llm_request",
        "llm_reasoning_delta",
        "llm_content_delta",
        "llm_content_delta",
        "llm_response",
    ]


def test_streaming_reasoning_delta_text() -> None:
    """Reasoning delta event carries text == '思考中'."""
    client, events = _make_streaming_client(llm_stream=True)
    chunks = _make_canonical_chunks()

    def fake_create(**kwargs):
        return iter(chunks)

    _inject_fake(client, fake_create)
    client.generate("sys", "user", model="gemini-3.1-pro-preview")

    reasoning_events = [e for e in events if e["type"] == "llm_reasoning_delta"]
    assert len(reasoning_events) == 1
    assert reasoning_events[0]["text"] == "思考中"
    assert reasoning_events[0]["purpose"] == "generate"
    assert reasoning_events[0]["agent"] == "generator"


def test_streaming_content_delta_texts_in_order() -> None:
    """Content delta events carry '前半' then '後半' in order."""
    client, events = _make_streaming_client(llm_stream=True)
    chunks = _make_canonical_chunks()

    def fake_create(**kwargs):
        return iter(chunks)

    _inject_fake(client, fake_create)
    client.generate("sys", "user", model="gemini-3.1-pro-preview")

    content_events = [e for e in events if e["type"] == "llm_content_delta"]
    assert [e["text"] for e in content_events] == ["前半", "後半"]


def test_streaming_final_llm_response_fields() -> None:
    """llm_response: content assembled, reasoning set, usage mapped correctly."""
    client, events = _make_streaming_client(llm_stream=True)
    chunks = _make_canonical_chunks()

    def fake_create(**kwargs):
        return iter(chunks)

    _inject_fake(client, fake_create)
    client.generate("sys", "user", model="gemini-3.1-pro-preview")

    resp = next(e for e in events if e["type"] == "llm_response")
    assert resp["content"] == "前半後半"
    assert resp["reasoning"] == "思考中"
    assert resp["usage"] == {
        "input": 20,
        "output": 7,
        "cache_read": 4,
        "cache_creation": 0,
    }
    assert resp["model"] == "gemini-3.1-pro-preview"
    assert resp["purpose"] == "generate"
    assert resp["agent"] == "generator"


# ---------------------------------------------------------------------------
# 2. No usage chunk → all-zero usage, all four keys present
# ---------------------------------------------------------------------------


def test_streaming_no_usage_chunk_yields_zeroed_usage() -> None:
    client, events = _make_streaming_client(llm_stream=True)

    delta = SimpleNamespace(reasoning_content=None, content="hi")
    chunk = SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

    def fake_create(**kwargs):
        return iter([chunk])

    _inject_fake(client, fake_create)
    client.generate("sys", "user", model="gemini-3.1-pro-preview")

    resp = next(e for e in events if e["type"] == "llm_response")
    assert resp["usage"] == {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_creation": 0,
    }
    # all four keys present
    assert set(resp["usage"].keys()) == {"input", "output", "cache_read", "cache_creation"}


def test_streaming_no_usage_chunk_result_still_correct() -> None:
    client, _ = _make_streaming_client(llm_stream=True)

    delta = SimpleNamespace(reasoning_content=None, content="hi")
    chunk = SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

    def fake_create(**kwargs):
        return iter([chunk])

    _inject_fake(client, fake_create)
    result = client.generate("sys", "user", model="gemini-3.1-pro-preview")
    assert result == "hi"


# ---------------------------------------------------------------------------
# 3. llm_stream=False with observer → non-streaming (no stream kwarg)
# ---------------------------------------------------------------------------


def test_non_streaming_when_llm_stream_false_observer_attached() -> None:
    """With llm_stream=False, create() is called WITHOUT stream kwarg."""
    client, events = _make_streaming_client(llm_stream=False, attach_observer=True)
    create_calls: list[dict] = []

    def fake_create(**kwargs):
        create_calls.append(kwargs)
        msg = SimpleNamespace(content="non-stream")
        choice = SimpleNamespace(message=msg)
        usage = SimpleNamespace(
            prompt_tokens=5,
            completion_tokens=2,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )
        return SimpleNamespace(choices=[choice], usage=usage)

    _inject_fake(client, fake_create)
    result = client.generate("sys", "user", model="gemini-3.1-pro-preview")

    assert result == "non-stream"
    assert len(create_calls) == 1
    assert "stream" not in create_calls[0]
    assert "stream_options" not in create_calls[0]


# ---------------------------------------------------------------------------
# 4. No observer + llm_stream=True → non-streaming path
# ---------------------------------------------------------------------------


def test_non_streaming_when_no_observer() -> None:
    """Without an observer, create() is called WITHOUT stream kwarg even if llm_stream=True."""
    client, _ = _make_streaming_client(llm_stream=True, attach_observer=False)
    create_calls: list[dict] = []

    def fake_create(**kwargs):
        create_calls.append(kwargs)
        msg = SimpleNamespace(content="no-obs")
        choice = SimpleNamespace(message=msg)
        usage = SimpleNamespace(
            prompt_tokens=5,
            completion_tokens=2,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )
        return SimpleNamespace(choices=[choice], usage=usage)

    _inject_fake(client, fake_create)
    result = client.generate("sys", "user", model="gemini-3.1-pro-preview")

    assert result == "no-obs"
    assert len(create_calls) == 1
    assert "stream" not in create_calls[0]
    assert "stream_options" not in create_calls[0]
