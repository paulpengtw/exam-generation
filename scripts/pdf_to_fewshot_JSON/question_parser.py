"""Parse individual questions from raw page text + images using LLM vision."""

from __future__ import annotations

import json
from pathlib import Path


def parse_questions_from_batch(
    llm_client,
    pages: list[dict],
    prompts_dir: Path,
) -> list[dict]:
    """
    Send a batch of pages (text + images) to the LLM and extract individual questions.

    Returns a list of parsed question dicts:
        {
            "question_number": "Q1",
            "raw_text": "...",
            "figure_description": "..." or None,
            "has_figure": bool,
            "question_type_hint": "選擇題" or "非選擇題",
            "page_numbers": [...]
        }
    """
    system_prompt = (prompts_dir / "parse_questions.md").read_text(encoding="utf-8")

    # Build a user message combining text from all pages in the batch
    user_parts = []
    image_contents = []

    for page in pages:
        user_parts.append(f"=== 第 {page['page_number']} 頁文字 ===\n{page['text']}")
        if page.get("image_b64"):
            image_contents.append({
                "page_number": page["page_number"],
                "image_b64": page["image_b64"],
            })

    user_text = "\n\n".join(user_parts)
    user_text += "\n\nPlease identify and extract all questions on these pages. Return a JSON array."

    # If we have images, use the vision-capable generate call
    if image_contents:
        result = _generate_with_images(
            llm_client,
            system_prompt,
            user_text,
            image_contents,
        )
    else:
        raw = llm_client.generate(system_prompt, user_text)
        result = _extract_json_array(raw)

    return result


def _generate_with_images(llm_client, system: str, user_text: str, image_contents: list[dict]) -> list[dict]:
    """Call LLM with both text and base64 images in the user message."""
    # Build a multimodal message with text + images
    content_blocks = []

    # Add images first, labeled by page number
    for img in image_contents:
        content_blocks.append({
            "type": "text",
            "text": f"[頁面 {img['page_number']} 圖片如下：]"
        })
        content_blocks.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img['image_b64']}"
            }
        })

    # Add the text content at the end
    content_blocks.append({"type": "text", "text": user_text})

    # Use the raw OpenAI client for multimodal messages
    response = llm_client.client.chat.completions.create(
        model=llm_client.config.model_execute,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content_blocks},
        ],
        max_tokens=8192,
        temperature=0.2,
    )
    raw = response.choices[0].message.content
    return _extract_json_array(raw)


def _extract_json_array(text: str) -> list[dict]:
    """Extract a JSON array from LLM response text."""
    import re

    # Try code blocks first
    code_block = re.search(r"```(?:json)?\s*\n(\[.*?\])\s*\n```", text, re.DOTALL)
    if code_block:
        return json.loads(code_block.group(1))

    # Try finding a JSON array directly
    text = text.strip()
    if text.startswith("["):
        return json.loads(text)

    # Find the first [...] block
    array_match = re.search(r"\[.*\]", text, re.DOTALL)
    if array_match:
        return json.loads(array_match.group(0))

    raise ValueError(f"Could not extract JSON array from:\n{text[:500]}")
