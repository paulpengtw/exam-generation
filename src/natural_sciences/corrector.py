# ruff: noqa: E501
"""Correction pass for natural-sciences questions."""

from __future__ import annotations

from collections.abc import Callable

from src.common.correction_decision import CorrectionDecision
from src.common.corrector import correct_question_common, parse_rubric
from src.common.generation_events import OperationScope
from src.curriculum_context import CurriculumContext, build_curriculum_section
from src.llm_client import LLMClient
from src.natural_sciences.curriculum_codes import repair_lc_refs, repair_lp_refs
from src.natural_sciences.schemas import (
    ExamQuestion,
    ImageSpec,
    LearningContentRef,
    VerificationResult,
)

# Shared with the 人工審題修正 admission route.  The route must reject
# annotations aimed at fields this corrector restores from the original.
FROZEN_TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "核心問題",
        "情境",
        "情境子類別",
        "題型種類",
        "題型",
        "科學能力",
        "題目內容類型",
        "取材來源",
        "圖片",
        "verification",
        "metadata",
    }
)
FROZEN_SUBQUESTION_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "序號",
        "年級",
        "科目",
        "科學能力",
        "核心素養",
        "學習內容",
        "學習表現",
        "出題概念",
        "出題指示",
        "Reporting Scale",
        "reporting_scale",
        "題型",
        "題目內容類型",
        "image_generation_mode",
        "圖片",
        "chart_spec",
    }
)

_CORRECTION_SYSTEM_PROMPT_CORE = """\
你是一位 PISA Science 與108課綱自然科學領域命題教師，剛收到審核老師對一道題組的意見回饋。
請根據審核意見「最小幅度」修正題目，保留所有正確的部分。

修正原則：
- 不要重寫整題，只更正審核老師明確指出有問題的部分。
- 若問題在小題答案或評分規準，請只修改對應小題的 答案/答案解析/評分規準。
- 若問題在選項設計，請修正對應小題題目文字與答案，同步修正 正確解題分析。
- 若問題在文本素材或小題敘述歧義，請最小幅度澄清文本或小題題目，同步調整答案解析。
- 若 chart_verification 指出素材錯誤，請只修正 chart_spec 的 data/labels/description，保留 render_mode。
- 絕對不可修改：核心問題、情境、情境子類別、題型種類、題型、科學能力、id、metadata，
  以及各小題的 學習內容/學習表現/科學能力/出題概念/出題指示/Reporting Scale/科目/年級。
- 若某小題的答案或選項有改動，該小題的 `誘答分析` 必須同步反映新的正解與誘答陷阱：正解鍵改為「正確答案：…」，其他鍵改為新的科學迷思描述。選項標籤必須與新題目一致；若題目為 Constructed-response 或沒有 (A)-(D) 標籤，可留空 `{}`。
- `subquestions` 可以省略，表示不修改小題；若輸出此欄位，必須輸出與原題完全相同數量的清單。
  每列的 `id`/`序號` 必須仍指向原列，且順序不可改變；不可新增、刪除、複製或重新排序小題。

請輸出修正後完整的題目 JSON，格式與原題目相同。只輸出 JSON，不要輸出其他文字。
"""

def _refs_from_raw(raw: object) -> list[LearningContentRef]:
    """Best-effort parse of a raw LLM 學習內容/學習表現 list into refs."""
    if not isinstance(raw, list):
        return []
    return [
        LearningContentRef(編碼=r.get("編碼", ""), 說明=r.get("說明", ""))
        for r in raw
        if isinstance(r, dict) and r.get("編碼")
    ]


def _ns_rebuild_subquestion(sq_raw: dict, original: object | None, idx: int) -> object | None:
    """Rebuild one NS subquestion from corrected LLM output.

    Frozen fields (those that must not change across correction passes):
    ``id``, ``序號``, ``年級``, ``科目``, ``科學能力``, ``核心素養``,
    ``學習內容``, ``學習表現``, ``出題概念``, ``題型``, ``題目內容類型``,
    ``image_generation_mode``, ``圖片`` and ``chart_spec``.

    The shared acceptance guard supplies an existing original for every row;
    added rows are rejected before reconstruction.

    The rubric is read tolerantly via :func:`parse_rubric`, accepting both
    ``評分規準`` and the alternate key ``評分標準`` (AC3 fix).
    """
    from src.natural_sciences.schemas import RubricEntry, SubQuestion

    try:
        rubric = parse_rubric(sq_raw, RubricEntry)
        chart_spec = original.chart_spec if original else None
        if original is None:
            raw_chart_spec = sq_raw.get("image_spec") or sq_raw.get("chart_spec")
            if isinstance(raw_chart_spec, dict):
                try:
                    chart_spec = ImageSpec(**raw_chart_spec)
                except Exception:
                    chart_spec = None
        sq = SubQuestion(
            id=original.id if original else sq_raw.get("id", ""),
            序號=original.序號 if original else sq_raw.get("序號", idx + 1),
            年級=original.年級 if original else sq_raw.get("年級", 0),
            科目=original.科目 if original else sq_raw.get("科目", []),
            科學能力=original.科學能力 if original else sq_raw.get("科學能力", []),
            核心素養=original.核心素養 if original else sq_raw.get("核心素養", []),
            # Frozen when an original exists (post issue-#92 parse
            # repair the originals are always valid); LLM-added rows
            # get deterministic canonicalization instead (no pool
            # here, so unknown codes are dropped, not replaced).
            學習內容=(
                original.學習內容
                if original
                else repair_lc_refs(_refs_from_raw(sq_raw.get("學習內容")), [])
            ),
            學習表現=(
                original.學習表現
                if original
                else repair_lp_refs(_refs_from_raw(sq_raw.get("學習表現")), [])
            ),
            出題概念=original.出題概念 if original else sq_raw.get("出題概念", ""),
            出題指示=original.出題指示 if original else sq_raw.get("出題指示"),
            # reporting_scale is frozen: the resolved level is a fact about the
            # generated question, not something the corrector should alter.
            reporting_scale=(
                original.reporting_scale
                if original
                else sq_raw.get("reporting_scale")
            ),
            題型=original.題型 if original else sq_raw.get("題型", ""),
            題目=sq_raw.get("題目", original.題目 if original else ""),
            答案=sq_raw.get("答案", original.答案 if original else ""),
            答案解析=sq_raw.get("答案解析", original.答案解析 if original else ""),
            評分規準=rubric if rubric else (original.評分規準 if original else []),
            誘答分析=(
                sq_raw.get("誘答分析", original.誘答分析 if original else {})
            ),
            題目內容類型=(
                original.題目內容類型 if original else sq_raw.get("題目內容類型")
            ),
            image_generation_mode=(
                original.image_generation_mode
                if original else sq_raw.get("image_generation_mode")
            ),
            圖片=original.圖片 if original else sq_raw.get("圖片"),
            chart_spec=chart_spec,
        )
        return sq
    except Exception:
        return None


def correct_question(
    client: LLMClient,
    question: ExamQuestion,
    verification: VerificationResult,
    chart_image_path: str | None = None,
    curriculum_context: CurriculumContext | None = None,
    annotations: str | None = None,
    editable_paths: set[str] | None = None,
    on_rejected: Callable[[str], None] | None = None,
    on_decision: Callable[[CorrectionDecision], None] | None = None,
    *,
    program_owned_subquestion_identity: bool = False,
    scope: OperationScope | None = None,
) -> ExamQuestion:
    if curriculum_context is not None:
        curriculum_prefix = build_curriculum_section(curriculum_context)
        system_prompt = (
            f"{curriculum_prefix}\n\n---\n\n{_CORRECTION_SYSTEM_PROMPT_CORE}"
            if curriculum_prefix
            else _CORRECTION_SYSTEM_PROMPT_CORE
        )
    else:
        system_prompt = _CORRECTION_SYSTEM_PROMPT_CORE
    return correct_question_common(
        client=client,
        question=question,
        verification=verification,
        chart_image_path=chart_image_path,
        system_prompt=system_prompt,
        rebuild_subquestion_fn=_ns_rebuild_subquestion,
        image_spec_cls=ImageSpec,
        annotations=annotations,
        editable_paths=editable_paths,
        on_rejected=on_rejected,
        on_decision=on_decision,
        program_owned_subquestion_identity=program_owned_subquestion_identity,
        scope=scope,
    )
