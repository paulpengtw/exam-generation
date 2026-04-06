"""Map solved questions to curriculum learning content codes."""

from __future__ import annotations

import json
from pathlib import Path


def map_curriculum(
    llm_client,
    solved_question: dict,
    curriculum_items: list[dict],
    prompts_dir: Path,
) -> list[dict]:
    """
    Given a solved question and the grades 7-9 curriculum items, select the most
    relevant 學習內容 codes.

    Returns a list of {"編碼": ..., "說明": ...} dicts.
    """
    system_prompt = (prompts_dir / "map_curriculum.md").read_text(encoding="utf-8")

    # Format curriculum items for the prompt
    curriculum_text = json.dumps(curriculum_items, ensure_ascii=False, indent=2)

    question_text = "\n".join(solved_question.get("題目", []))
    solution_text = "\n".join(solved_question.get("正確解題分析", []))

    user_text = f"""Question:
{question_text}

Solution:
{solution_text}

## Available Curriculum Codes (grades 7-9)

{curriculum_text}

Select 1-3 curriculum codes that best match the mathematical content of this question.
Return a JSON array of objects with "編碼" and "說明" fields.
"""

    raw = llm_client.generate(system_prompt, user_text)
    result = _extract_json_array(raw)

    # Validate: ensure each item has 編碼 and 說明
    validated = []
    for item in result:
        if isinstance(item, dict) and "編碼" in item and "說明" in item:
            validated.append({"編碼": item["編碼"], "說明": item["說明"]})

    return validated if validated else [{"編碼": "N-7-1", "說明": "（需手動確認課程編碼）"}]


def _extract_json_array(text: str) -> list[dict]:
    """Extract a JSON array from LLM response text."""
    import re

    code_block = re.search(r"```(?:json)?\s*\n(\[.*?\])\s*\n```", text, re.DOTALL)
    if code_block:
        return json.loads(code_block.group(1))

    text = text.strip()
    if text.startswith("["):
        return json.loads(text)

    array_match = re.search(r"\[.*\]", text, re.DOTALL)
    if array_match:
        return json.loads(array_match.group(0))

    raise ValueError(f"Could not extract JSON array from:\n{text[:500]}")
