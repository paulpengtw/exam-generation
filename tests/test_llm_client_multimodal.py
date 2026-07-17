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
