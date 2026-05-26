"""Generate candidate 核心問題 for a given topic using the planning model."""

from __future__ import annotations

import json
import re

from src.llm_client import LLMClient

_SYSTEM = """\
你是一位資深108課綱社會領域命題教師。
使用者會提供一個議題或主題，請你根據108課綱社會領域（歷史、地理、公民與社會）的素養導向命題精神，
提出 {n} 個不同角度的「核心問題」候選。

核心問題的要求：
- 一句話，以「如何」、「為什麼」、「什麼」等開放性問法引導探究
- 跨科或深度連結社會領域學習內容
- 適合{learning_stage}學生作答
- 彼此角度明顯不同（歷史脈絡、空間地理、公民社會各至少一個面向）

請直接輸出 JSON 陣列，不要其他說明文字：
["核心問題一", "核心問題二", "核心問題三"]
"""

_USER = """\
議題/主題：{topic}{subject_hint}{grade_hint}

請提出 {n} 個核心問題候選。
"""


def plan_core_questions(
    client: LLMClient,
    topic: str,
    *,
    subject_filter: list[str] | None = None,
    grade: int | None = None,
    n: int = 3,
    learning_stage: str = "第四學習階段",
) -> list[str]:
    """Call planning model, return n candidate 核心問題 for the given topic."""
    subject_hint = f"\n科目偏好：{'、'.join(subject_filter)}" if subject_filter else ""
    grade_hint = f"\n目標年級：{grade}年級" if grade else ""

    system = _SYSTEM.format(n=n, learning_stage=learning_stage)
    user = _USER.format(
        topic=topic,
        subject_hint=subject_hint,
        grade_hint=grade_hint,
        n=n,
    )

    raw = client.plan(system, user, purpose="plan_core_questions")
    candidates = _parse_candidates(raw, n)
    return candidates


def _parse_candidates(raw: str, n: int) -> list[str]:
    """Extract list[str] from LLM output; retry-tolerant."""
    # Try code block first
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    text = code_block.group(1).strip() if code_block else raw.strip()

    # Find the JSON array
    arr_match = re.search(r"\[.*\]", text, re.DOTALL)
    if arr_match:
        text = arr_match.group(0)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to line-by-line extraction
        lines = [line.strip().strip('",') for line in raw.splitlines() if line.strip().strip('",')]
        result = [line for line in lines if len(line) > 5][:n]

    if not isinstance(result, list):
        raise ValueError(f"Expected JSON array from planner, got: {type(result)}")

    candidates = [str(x) for x in result if x]
    if len(candidates) < n:
        raise ValueError(f"Planner returned {len(candidates)} candidates, expected {n}")

    return candidates[:n]
