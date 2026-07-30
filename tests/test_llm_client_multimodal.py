"""Regression tests: chart image reaches the Anthropic SDK payload.

Covers GitHub issue #106 part (a): programmatic assertions that
`_to_anthropic_content` preserves image blocks and that
`generate_with_image` sends them to `Anthropic.messages.create`.
"""

from __future__ import annotations

import base64

from src.llm_client import _to_anthropic_content

# 1×1 transparent PNG (67 bytes) — built in-test, no binary fixture file.
_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
_TINY_PNG_B64 = base64.b64encode(_TINY_PNG_BYTES).decode("ascii")
_TINY_PNG_DATA_URL = f"data:image/png;base64,{_TINY_PNG_B64}"


def test_to_anthropic_content_preserves_text_then_image_block() -> None:
    """A mixed [text, image_url] list must yield [text, image(base64)] in order."""
    openai_style = [
        {"type": "text", "text": "請根據圖表判斷趨勢。"},
        {"type": "image_url", "image_url": {"url": _TINY_PNG_DATA_URL}},
    ]

    result = _to_anthropic_content(openai_style)

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0] == {"type": "text", "text": "請根據圖表判斷趨勢。"}
    assert result[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": _TINY_PNG_B64,
        },
    }


def test_to_anthropic_content_silently_drops_unknown_part_types() -> None:
    """Current behaviour: unknown content-part shapes are dropped silently.

    This test documents that today's implementation drops any part whose
    `type` is not "text" or "image_url" (see src/llm_client.py:128-140).
    If someone changes that behaviour, this assertion will fail and force
    a deliberate update — that's the guard.
    """
    openai_style = [
        {"type": "text", "text": "before"},
        {"type": "tool_use", "id": "call_1", "name": "x", "input": {}},
        {"type": "image_url", "image_url": {"url": _TINY_PNG_DATA_URL}},
    ]

    result = _to_anthropic_content(openai_style)

    # tool_use dropped; text and image survive.
    assert [p["type"] for p in result] == ["text", "image"]
    assert result[0]["text"] == "before"
    assert result[1]["source"]["data"] == _TINY_PNG_B64


class _FakeAnthropicUsage:
    input_tokens = 10
    output_tokens = 5
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _FakeAnthropicTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAnthropicResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeAnthropicTextBlock(text)]
        self.usage = _FakeAnthropicUsage()


class _RecorderMessages:
    """Stands in for `Anthropic.messages`; records `create` kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs) -> _FakeAnthropicResponse:
        self.calls.append(kwargs)
        return _FakeAnthropicResponse('{"ok": true}')


def test_generate_with_image_sends_base64_image_block_to_sdk(tmp_path) -> None:
    """End-to-end: `generate_with_image` must place a base64 image block into
    the `messages` array reaching `Anthropic.messages.create`."""
    from src.config import Config
    from src.llm_client import LLMClient

    png_path = tmp_path / "chart.png"
    png_path.write_bytes(_TINY_PNG_BYTES)

    # Non-streaming path: no observer + llm_stream=False -> messages.create is used.
    # Pin an Anthropic model so the test targets the Anthropic SDK path (client.client).
    client = LLMClient(Config(api_key="test-key", llm_stream=False, model_execute="claude-sonnet-4-6"))
    recorder = _RecorderMessages()
    client.client.messages = recorder  # type: ignore[assignment]

    client.generate_with_image(
        system="you are a verifier",
        user="請看下方圖表並回答。",
        image_path=png_path,
        purpose="verify",
    )

    assert len(recorder.calls) == 1
    call = recorder.calls[0]

    # System is a cache-controlled block, not part of `messages`.
    assert call["system"] == [
        {
            "type": "text",
            "text": "you are a verifier",
            "cache_control": {"type": "ephemeral"},
        }
    ]

    messages = call["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"

    user_content = messages[0]["content"]
    assert isinstance(user_content, list)
    image_blocks = [p for p in user_content if p.get("type") == "image"]
    text_blocks = [p for p in user_content if p.get("type") == "text"]

    assert len(image_blocks) == 1, "exactly one image block must reach the SDK"
    assert len(text_blocks) == 1
    assert text_blocks[0]["text"] == "請看下方圖表並回答。"

    source = image_blocks[0]["source"]
    assert source["type"] == "base64"
    assert source["media_type"] == "image/png"
    assert source["data"] == _TINY_PNG_B64
    assert len(source["data"]) > 0
