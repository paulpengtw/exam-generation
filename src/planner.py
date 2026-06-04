"""Subject-specific shim over src.common.planner for math."""

from __future__ import annotations

from src.common.planner import plan_core_questions as _base_plan
from src.llm_client import LLMClient

_PLANNER_SYSTEM_PROMPT = """\
你是一位資深108課綱數學領域命題教師。
使用者會提供一個議題或主題，請你根據108課綱數學領域素養導向命題精神，
提出 {n} 個不同角度的「核心問題」候選。

核心問題的要求：
- 一句話，以「如何」、「為什麼」、「什麼」等開放性問法引導探究
- 連結數學素養與真實情境
- 適合{learning_stage}學生作答
- 彼此角度明顯不同（代數運算、幾何空間、統計與機率／資料解讀至少各一個面向）

請直接輸出 JSON 陣列，不要其他說明文字：
["核心問題一", "核心問題二", "核心問題三"]
"""

_PLANNER_USER_TEMPLATE = """\
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
    """Return n candidate 核心問題 for a math topic."""
    return _base_plan(
        client,
        topic,
        system_prompt=_PLANNER_SYSTEM_PROMPT,
        user_prompt_template=_PLANNER_USER_TEMPLATE,
        n=n,
        learning_stage=learning_stage,
        subject_filter=subject_filter,
        grade=grade,
    )


__all__ = ["plan_core_questions"]
