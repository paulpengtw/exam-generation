"""Subject-specific shim over src.common.planner for 社會領域."""

from __future__ import annotations

from src.common.generation_events import OperationScope
from src.common.planner import _parse_candidates
from src.common.planner import plan_context_angles as _base_plan_context_angles
from src.common.planner import plan_core_questions as _base_plan
from src.llm_client import LLMClient
from src.social_studies.schemas import CreativeBrief

_PLANNER_SYSTEM_PROMPT = """\
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

_PLANNER_USER_TEMPLATE = """\
議題/主題：{topic}{subject_hint}{grade_hint}

請提出 {n} 個核心問題候選。
"""


_SS_CREATIVE_PLANNER_SYSTEM_PROMPT = (
    "你是一位資深108課綱社會領域命題教師，正在為一批 {n} 道題組"
    "規劃彼此不同的「情境-題材」創意方向。\n"
    "每個題組的核心參數（年級、學習內容、學習表現、科目、題型）已由系統隨機決定；你只負責挑選情境與構思題材角度。\n"
    "本任務適用學習階段：{learning_stage}。\n"
    "\n"
    "規則：\n"
    "- 你會拿到本批次「可用的情境」清單；每個 brief 的 `selected_context` "
    "**必須從清單中挑選**，不得自創新情境。\n"
    "- 每個 brief 由三個欄位組成：\n"
    "  * `selected_context`：從可用情境挑選的一個值。\n"
    "  * `題材_angle`：1–2 句創意框架，將情境與可能的核心問題連結；避免教科書式描述。\n"
    "  * `framing_hooks`：1–2 個具體取材錨點，例如「病患日記」、「決策會議紀錄」、「田野筆記」。\n"
    "- {n} 個 brief 之間**彼此的題材必須互相不同**：情境可以重覆，"
    "但題材角度與 framing_hooks 不得雷同，避免只換名稱的變體。\n"
    "- 題材應能被 108課綱 指定學習內容支撐；不要引用學生程度以外的專業術語。\n"
    "- 你不決定學習內容、學習表現、核心素養、題目等其他參數，僅提供情境與題材創意。\n"
    "\n"
    "輸出格式為 JSON 陣列，共 {n} 筆，每筆為物件：\n"
    "\n"
    "```json\n"
    "[\n"
    "  {{\n"
    '    "selected_context": "個人",\n'
    '    "題材_angle": "以居家防疫日記串起個人與公共衛生決策",\n'
    '    "framing_hooks": ["病患日記", "家庭記事本"]\n'
    "  }}\n"
    "]\n"
    "```\n"
    "\n"
    "只輸出 JSON 陣列，不要其他說明文字。\n"
)

_SS_CREATIVE_PLANNER_USER_TEMPLATE = """\
本批次需要 {count} 個題組，請為它們規劃 {count} 個互相不同的情境-題材創意 brief：

- 可用情境（selected_context 必須從中挑選）：{contexts}
- 本批次共用的指定學習內容：{learning_content}
- 使用者指定核心問題（僅供參考，可為「（未指定）」）：{core_question}

請輸出恰好 {count} 個 brief 的 JSON 陣列。
"""


def plan_core_questions(
    client: LLMClient,
    topic: str,
    *,
    subject_filter: list[str] | None = None,
    grade: int | None = None,
    n: int = 3,
    learning_stage: str = "第四學習階段",
    scope: OperationScope | None = None,
) -> list[str]:
    """Call planning model, return n candidate 核心問題 for the given topic."""
    return _base_plan(
        client,
        topic,
        system_prompt=_PLANNER_SYSTEM_PROMPT,
        user_prompt_template=_PLANNER_USER_TEMPLATE,
        n=n,
        learning_stage=learning_stage,
        subject_filter=subject_filter,
        grade=grade,
        scope=scope,
    )


def plan_context_angles(
    client: LLMClient,
    count: int,
    sampled_contexts: list[str],
    learning_content_pool: list[str],
    core_question: str | None = None,
    *,
    learning_stage: str = "第四學習階段",
    scope: OperationScope | None = None,
) -> list[CreativeBrief]:
    """Call the planning model and return `count` distinct 社會領域 briefs.

    Returns `[]` when Opus is unavailable or every brief was out-of-set;
    raises `ValueError` when the LLM response could not be parsed as JSON.
    Callers (batch loops) must handle both to fall back to briefless prompts.
    """
    return _base_plan_context_angles(
        client,
        count=count,
        sampled_contexts=sampled_contexts,
        learning_content_pool=learning_content_pool,
        core_question=core_question,
        system_prompt=_SS_CREATIVE_PLANNER_SYSTEM_PROMPT,
        user_prompt_template=_SS_CREATIVE_PLANNER_USER_TEMPLATE,
        learning_stage=learning_stage,
        scope=scope,
    )


__all__ = ["plan_core_questions", "plan_context_angles", "_parse_candidates"]
