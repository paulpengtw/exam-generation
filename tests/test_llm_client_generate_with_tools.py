"""Tests for LLMClient.generate_with_tools (issue #104, Anthropic web_search)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config import Config
from src.llm_client import Citation, LLMClient


class _FakeMessagesAPI:
    """Records calls and replays scripted responses to messages.create."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN001 — mimic SDK signature
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _make_client(responses: list[object]) -> tuple[LLMClient, _FakeMessagesAPI]:
    cfg = Config(api_key="x")
    client = LLMClient(cfg)
    fake = _FakeMessagesAPI(responses)
    client.client = SimpleNamespace(messages=fake)
    return client, fake


def _text_block(text: str, citations: list[dict] | None = None):
    return SimpleNamespace(type="text", text=text, citations=citations or [])


def _web_search_result_block(url: str, title: str):
    result = SimpleNamespace(url=url, title=title)
    return SimpleNamespace(type="web_search_tool_result", content=[result])


def _response(stop_reason: str, blocks: list) -> object:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=blocks,
        usage=SimpleNamespace(
            input_tokens=1,
            output_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def test_generate_with_tools_end_turn_returns_text_and_citations() -> None:
    citation_dict = {"url": "https://example.org/a", "title": "Source A"}
    response = _response(
        "end_turn",
        [
            _web_search_result_block("https://example.org/a", "Source A"),
            _text_block("最終回覆", citations=[citation_dict]),
        ],
    )
    client, fake = _make_client([response])
    text, citations = client.generate_with_tools(
        system="sys",
        user="usr",
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        purpose="fact_check",
    )
    assert text == "最終回覆"
    assert citations == [Citation(url="https://example.org/a", title="Source A")]
    assert len(fake.calls) == 1
    assert fake.calls[0]["tools"][0]["type"] == "web_search_20250305"


def test_generate_with_tools_handles_pause_turn_continuation() -> None:
    first = _response("pause_turn", [_text_block("查詢中…")])
    second = _response(
        "end_turn",
        [_text_block("完整答案", citations=[{"url": "https://example.org/b", "title": "B"}])],
    )
    client, fake = _make_client([first, second])
    text, citations = client.generate_with_tools(
        system="sys",
        user="usr",
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        purpose="fact_check",
    )
    assert "完整答案" in text
    assert Citation(url="https://example.org/b", title="B") in citations
    assert len(fake.calls) == 2
    # Second call carries the assistant turn produced by the first response.
    assert fake.calls[1]["messages"][-1]["role"] == "assistant"


def test_generate_with_tools_stops_at_max_iterations() -> None:
    pause_forever = [
        _response("pause_turn", [_text_block(f"step {i}")]) for i in range(5)
    ]
    client, fake = _make_client(pause_forever)
    text, citations = client.generate_with_tools(
        system="sys",
        user="usr",
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        purpose="fact_check",
        max_iterations=3,
    )
    assert len(fake.calls) == 3
    assert citations == []
    assert "step 0" in text  # Partial text is returned so callers can log it.


def test_generate_with_tools_deduplicates_citations_by_url() -> None:
    response = _response(
        "end_turn",
        [
            _text_block(
                "回覆",
                citations=[
                    {"url": "https://example.org/a", "title": "Source A"},
                    {"url": "https://example.org/a", "title": "Source A (dup)"},
                    {"url": "https://example.org/b", "title": "Source B"},
                ],
            ),
        ],
    )
    client, _ = _make_client([response])
    _, citations = client.generate_with_tools(
        system="sys",
        user="usr",
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        purpose="fact_check",
    )
    urls = [c.url for c in citations]
    assert urls == ["https://example.org/a", "https://example.org/b"]


class _FakeGeminiCompletions:
    """Record Gemini OpenAI-compat completion calls."""

    def __init__(self, response: object | None = None, raises: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.response = response
        self.raises = raises

    def create(self, **kwargs):  # noqa: ANN001 — mimic SDK signature
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.response


def _gemini_response(text: str = "Gemini response") -> object:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3),
        model_extra={
            "candidates": [{
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://example.org/gemini", "title": "Gemini source"}}
                    ]
                }
            }]
        },
    )


def _make_gemini_client(
    fake_completions: _FakeGeminiCompletions,
    *,
    rate_limit_delay: float = 0.0,
) -> LLMClient:
    cfg = Config(
        api_key="x",
        llm_stream=False,
        model_execute="claude-sonnet-4-6",
        model_verify="gemini-3.1-pro-preview",
        effort_execute="medium",
        effort_verify="high",
        rate_limit_delay=rate_limit_delay,
    )
    client = LLMClient(cfg)
    client._openai_compat_client = lambda provider: SimpleNamespace(  # type: ignore[method-assign]
        chat=SimpleNamespace(completions=fake_completions)
    )
    return client


def test_generate_with_google_search_uses_gemini_grounding_and_verify_tier() -> None:
    """Gemini grounding uses the verify model, effort, and native extra_body tools."""
    fake = _FakeGeminiCompletions(_gemini_response())
    client = _make_gemini_client(fake)

    text, citations = client.generate_with_google_search(
        system="system prompt",
        user="user prompt",
        purpose="fact_check",
        max_uses=99,
    )

    assert text == "Gemini response"
    assert citations == [Citation(url="https://example.org/gemini", title="Gemini source")]
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["model"] == "gemini-3.1-pro-preview"
    assert call["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    assert call["extra_body"] == {"tools": [{"google_search": {}}]}
    assert call["reasoning_effort"] == "high"
    assert "max_uses" not in call


def test_generate_with_google_search_emits_observer_events_and_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini grounding emits fact-check lifecycle events and honors rate limiting."""
    fake = _FakeGeminiCompletions(_gemini_response())
    client = _make_gemini_client(fake, rate_limit_delay=0.25)
    events: list[dict] = []
    sleeps: list[float] = []
    client.set_observer(events.append)
    monkeypatch.setattr("src.llm_client.time.sleep", sleeps.append)

    client.generate_with_google_search("sys", "usr")

    assert sleeps == [0.25]
    assert [event["type"] for event in events] == ["llm_request", "llm_response"]
    assert all(event["purpose"] == "fact_check" for event in events)
    assert all(event["agent"] == "fact_checker" for event in events)
    assert all(event["model"] == "gemini-3.1-pro-preview" for event in events)


def test_generate_with_google_search_propagates_api_errors() -> None:
    """Gemini API exceptions propagate to the fact-check caller."""
    fake = _FakeGeminiCompletions(raises=RuntimeError("gemini unavailable"))
    client = _make_gemini_client(fake)

    with pytest.raises(RuntimeError, match="gemini unavailable"):
        client.generate_with_google_search("sys", "usr")
