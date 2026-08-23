"""Correction pass for social studies questions."""

from __future__ import annotations

from src.common.corrector import correct_question_common, parse_rubric
from src.curriculum_context import CurriculumContext, build_curriculum_section
from src.llm_client import LLMClient
from src.social_studies.schemas import ExamQuestion, ImageSpec, VerificationResult

# Shared with the 人工審題修正 admission route.  Keep these fields here beside
# the subject corrector's reconstruction contract rather than duplicating them
# in an API module.
FROZEN_TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "核心問題",
        "情境",
        "題型種類",
        "題型",
        "閱讀歷程",
        "文本形式",
        "題目內容類型",
        "難度",
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
        "核心素養",
        "學習內容",
        "學習表現",
        "出題概念",
        "出題指示",
        "題型",
        "題目內容類型",
        "image_generation_mode",
        "圖片",
        "chart_spec",
    }
)

_CORRECTION_SYSTEM_PROMPT_CORE = """\
你是一位108課綱社會領域素養導向命題教師，剛收到審核老師對一道題組的意見回饋。
請根據審核意見「最小幅度」修正題目，保留所有正確的部分。

修正原則：
- **不要重寫整題**。只更正審核老師明確指出有問題的部分。
- 若問題在小題答案或評分規準 → 只修改 subquestions 中對應小題的 答案/答案解析/評分規準。
- 若問題在選項設計（答案不在選項中）→ 修正對應小題的題目文字與答案，同步修正 正確解題分析。
- 若問題在文本素材或小題敘述歧義 → 最小幅度澄清文本或小題題目，同步調整答案解析。
- 若 chart_verification 指出非連續文本素材錯誤 → 只修正 chart_spec 的 data/labels/description，
  保留 render_mode、chart_type 不變。
- 絕對不可修改：核心問題、情境、題型種類、題型、閱讀歷程、文本形式、難度、id、metadata、
  各小題的 學習內容/學習表現/核心素養/出題概念/出題指示/科目/年級。
- 若某小題的答案或選項有改動，該小題的 `誘答分析` 必須同步反映新的正解與誘答陷阱：正解鍵改為「正確答案：…」，其他鍵改為新的誤解描述。選項標籤必須與新題目一致；若題目沒有 (A)-(D) 標籤，可留空 `{}`。

請輸出修正後完整的題目 JSON，格式與原題目相同。只輸出 JSON，不要輸出其他文字。
"""

def _ss_rebuild_subquestion(sq_raw: dict, original: object | None, idx: int) -> object | None:
    """Rebuild one SS subquestion from corrected LLM output.

    Frozen fields (those that must not change across correction passes):
    ``id``, ``序號``, ``年級``, ``科目``, ``核心素養``, ``學習內容``,
    ``學習表現``, ``出題概念``, ``出題指示``, ``題型``, ``題目內容類型``,
    ``image_generation_mode``, ``圖片``, ``chart_spec``.

    The rubric is read tolerantly via :func:`parse_rubric`, accepting both
    ``評分規準`` and the alternate key ``評分標準``.
    """
    from src.social_studies.schemas import RubricEntry, SubQuestion

    try:
        rubric = parse_rubric(sq_raw, RubricEntry)
        sq = SubQuestion(
            id=original.id if original else sq_raw.get("id", ""),
            序號=original.序號 if original else sq_raw.get("序號", idx + 1),
            年級=original.年級 if original else sq_raw.get("年級", 0),
            科目=original.科目 if original else sq_raw.get("科目", []),
            核心素養=original.核心素養 if original else sq_raw.get("核心素養", []),
            學習內容=original.學習內容 if original else [],
            學習表現=original.學習表現 if original else [],
            出題概念=original.出題概念 if original else sq_raw.get("出題概念", ""),
            出題指示=original.出題指示 if original else sq_raw.get("出題指示"),
            題型=original.題型 if original else sq_raw.get("題型", ""),
            題目=sq_raw.get("題目", original.題目 if original else ""),
            答案=sq_raw.get("答案", original.答案 if original else ""),
            答案解析=sq_raw.get("答案解析", original.答案解析 if original else ""),
            評分規準=rubric if rubric else (original.評分規準 if original else []),
            題目內容類型=(
                original.題目內容類型 if original else sq_raw.get("題目內容類型")
            ),
            image_generation_mode=(
                original.image_generation_mode
                if original else sq_raw.get("image_generation_mode")
            ),
            圖片=original.圖片 if original else sq_raw.get("圖片"),
            chart_spec=original.chart_spec if original else None,
            誘答分析=(
                {str(k): str(v) for k, v in sq_raw.get("誘答分析", {}).items()}
                if isinstance(sq_raw.get("誘答分析"), dict)
                else (original.誘答分析 if original else {})
            ),
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
        rebuild_subquestion_fn=_ss_rebuild_subquestion,
        image_spec_cls=ImageSpec,
        annotations=annotations,
    )
