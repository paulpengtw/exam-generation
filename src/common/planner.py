"""Generate candidate 核心問題 for a given topic using the planning model.

Subject-agnostic: callers supply the system/user prompt templates.
"""

from __future__ import annotations

import json
import re

from src.llm_client import LLMClient


def plan_core_questions(
    client: LLMClient,
    topic: str,
    *,
    system_prompt: str,
    user_prompt_template: str,
    n: int = 3,
    learning_stage: str = "第四學習階段",
    subject_filter: list[str] | None = None,
    grade: int | None = None,
) -> list[str]:
    """Call planning model, return n candidate 核心問題 for the given topic.

    `system_prompt` is formatted with {n, learning_stage}.
    `user_prompt_template` is formatted with {topic, n, subject_hint, grade_hint}.
    """
    subject_hint = f"\n科目偏好：{'、'.join(subject_filter)}" if subject_filter else ""
    grade_hint = f"\n目標年級：{grade}年級" if grade else ""

    system = system_prompt.format(n=n, learning_stage=learning_stage)
    user = user_prompt_template.format(
        topic=topic,
        n=n,
        subject_hint=subject_hint,
        grade_hint=grade_hint,
    )

    for attempt in range(2):
        raw = client.plan(system, user, purpose="plan_core_questions")
        try:
            return _parse_candidates(raw, n)
        except ValueError:
            if attempt == 0:
                user += f"\n注意：請務必輸出剛好 {n} 個候選的 JSON 陣列。"
            else:
                raise


def _parse_candidates(raw: str, n: int) -> list[str]:
    """Extract list[str] from LLM output; retry-tolerant."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    text = code_block.group(1).strip() if code_block else raw.strip()

    arr_match = re.search(r"\[.*\]", text, re.DOTALL)
    if arr_match:
        text = arr_match.group(0)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        lines = [line.strip().strip('",') for line in raw.splitlines() if line.strip().strip('",')]
        result = [line for line in lines if len(line) > 5][:n]

    if not isinstance(result, list):
        raise ValueError(f"Expected JSON array from planner, got: {type(result)}")

    candidates = [str(x) for x in result if x]
    if len(candidates) < n:
        raise ValueError(f"Planner returned {len(candidates)} candidates, expected {n}")

    return candidates[:n]
