"""Correction pass: apply verifier feedback to minimally fix a failed question."""

from __future__ import annotations

import json
from collections.abc import Callable

from src.common.correction_decision import CorrectionDecision, CorrectionRejection
from src.common.corrector import (
    CorrectionStructureError,
    _call_client_with_optional_scope,
    apply_correction,
    build_annotations_block,
    reject_correction,
    validate_correction_structure,
)
from src.common.generation_events import OperationScope
from src.curriculum_context import CurriculumContext, build_curriculum_section
from src.llm_client import LLMClient, extract_json
from src.schemas import ExamQuestion, ImageSpec, SubQuestion, VerificationResult

# The manual-modification admission route imports these sets so the route and
# the correction implementation share one source of truth for immutable fields.
FROZEN_TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "情境",
        "題型種類",
        "題型",
        "數學思考",
        "學習內容",
        "學習表現",
        "核心素養",
        "出題概念",
        "題目內容類型",
        "難度",
        "取材來源",
        "文本",
        "核心問題",
        "圖片",
        "verification",
        "metadata",
    }
)
FROZEN_SUBQUESTION_FIELDS: frozenset[str] = frozenset(
    {"id", "序號", "年級", "題型", "學習內容", "學習表現", "出題概念"}
)

_CORRECTION_SYSTEM_PROMPT_CORE = (
    "你是一位數學教師，剛剛收到審核老師對一道考試題目的意見回饋。\n"
    "請根據審核意見「最小幅度」修正題目，保留所有正確的部分。\n"
    "\n"
    "修正原則：\n"
    "- **不要重寫整題**。只更正審核老師明確指出有問題的部分。\n"
    "- 若問題在「正確解題分析」（計算或推理錯誤）→ 只修改 正確解題分析。\n"
    "- 若問題在「選項設計」或「答案不在選項中」→ 修正對應選項，必要時同步修正 正確解題分析。\n"
    "- 若問題在「題目敘述歧義」→ 最小幅度澄清 題目，並同步調整 正確解題分析。\n"
    "- 若 chart_verification 指出圖表錯誤 → 只修正 image_spec/chart_spec 的 data/labels，\n"
    "  保留 description、title、render_mode、chart_type 不變（除非審核明確要求）。\n"
    "- 絕對不可修改：情境、題型種類、題型、數學思考、學習內容、"
    "學習表現、核心素養、出題概念、題目內容類型、難度、id、metadata。\n"
    "- 題組的 `subquestions` 若需要修正，必須保留並輸出完整的小題清單；不得刪除未涉及的小題。\n"
    "- `subquestions` 可以省略，表示不修改小題；若輸出此欄位，必須輸出與原題完全相同數量的清單。\n"
    "  每列的 `id`/`序號` 必須仍指向原列，且順序不可改變；不可新增、刪除、複製或重新排序小題。\n"
    "- 若答案或選項有改動，`誘答分析` 必須同步反映新的正解與誘答陷阱："
    "正解鍵改為「正確答案：…」，其他鍵改為對應新誘答的錯誤概念。"
    "選項標籤必須與新的題目一致；若題目沒有 (A)-(D) 標籤，可留空 `{}`。\n"
    "\n"
    "請輸出修正後完整的題目 JSON，格式與原題目相同（含所有原欄位）。"
    "只輸出 JSON，不要輸出其他文字。\n"
)

CORRECTION_SYSTEM_PROMPT = _CORRECTION_SYSTEM_PROMPT_CORE

CORRECTION_USER_TEMPLATE = """\
## 原始題目（JSON）

```json
{question_json}
```

## 審核意見

{verification_details}
{answer_block}{chart_details_block}{annotations_block}
請輸出修正後的題目 JSON。
"""


def _rebuild_math_subquestion(
    raw: object,
    original: SubQuestion | None,
    index: int,
) -> SubQuestion | None:
    """Merge one corrected 小題 onto its original schema-valid value."""
    if not isinstance(raw, dict):
        return None
    data = original.model_dump() if original is not None else {}
    data.update(raw)
    if original is not None:
        for field in FROZEN_SUBQUESTION_FIELDS:
            data[field] = getattr(original, field)
    data.setdefault("id", f"subquestion-{index:02d}")
    data.setdefault("序號", index)
    try:
        parsed = SubQuestion.model_validate(data)
        if original is not None:
            return original.model_copy(
                deep=True,
                update={
                    field: getattr(parsed, field)
                    for field in type(parsed).model_fields
                },
            )
        return parsed
    except Exception:
        return None


def _parse_corrected_math_subquestions(
    corrected_data: dict,
    original: list[SubQuestion],
) -> list[SubQuestion] | None:
    """Parse a non-empty corrected 小題 list, or preserve it on bad output."""
    raw_subquestions = corrected_data.get("subquestions")
    if not isinstance(raw_subquestions, list) or not raw_subquestions:
        return None

    parsed: list[SubQuestion] = []
    for index, raw in enumerate(raw_subquestions, start=1):
        previous = original[index - 1] if index <= len(original) else None
        subquestion = _rebuild_math_subquestion(raw, previous, index)
        if subquestion is None:
            return None
        parsed.append(subquestion)
    return parsed


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
    scope: OperationScope | None = None,
) -> ExamQuestion:
    """Apply verification feedback to produce a minimally corrected question.

    Only 題目, 正確解題分析, chart_spec, and a complete math 題組
    ``subquestions`` list may be updated; all other fields are restored from the
    original regardless of LLM output.
    Returns the original question unchanged if the LLM output cannot be parsed.

    Args:
        curriculum_context: When supplied, the curriculum section is prepended
            to the system prompt so the corrector is grounded in the same corpus
            as the generator.  Pass ``None`` to omit the curriculum prefix.
        annotations: Optional user 修改指示 that the correction must preserve.
        on_rejected: Receives the reason when the complete previous snapshot is
            retained, so callers can distinguish a rejection from an accepted edit.
        on_decision: Receives exactly one immutable accepted/rejected decision
            after the complete candidate has been validated.
    """
    # Serialize without ephemeral fields so the corrector sees clean source
    question_data = json.loads(
        question.model_dump_json(exclude_none=True, exclude={"verification", "圖片"})
    )
    question_json = json.dumps(question_data, ensure_ascii=False, indent=2)

    answer_block = ""
    if verification.my_answer or verification.provided_answer:
        answer_block = (
            f"\n## 審核老師獨立解題答案\n{verification.my_answer}\n\n"
            f"## 題目目前提供的答案\n{verification.provided_answer}\n"
        )

    chart_details_block = ""
    if verification.chart_verification:
        cv = verification.chart_verification
        chart_details_block = (
            f"\n## 圖表審核意見\n"
            f"數據正確：{'是' if cv.chart_data_match else '否'}\n"
            f"標籤正確：{'是' if cv.chart_labels_correct else '否'}\n"
            f"說明：{cv.chart_details}\n"
        )

    user_prompt = CORRECTION_USER_TEMPLATE.format(
        question_json=question_json,
        verification_details=verification.details,
        answer_block=answer_block,
        chart_details_block=chart_details_block,
        annotations_block=build_annotations_block(annotations),
    )

    if curriculum_context is not None:
        curriculum_prefix = build_curriculum_section(curriculum_context)
        system = (
            f"{curriculum_prefix}\n\n---\n\n{CORRECTION_SYSTEM_PROMPT}"
            if curriculum_prefix
            else CORRECTION_SYSTEM_PROMPT
        )
    else:
        system = CORRECTION_SYSTEM_PROMPT

    try:
        # Use multimodal when chart has issues and PNG exists
        if verification.chart_verification and chart_image_path:
            raw_text = _call_client_with_optional_scope(
                client.generate_with_image,
                system,
                user_prompt,
                image_path=chart_image_path,
                purpose="correct",
                scope=scope,
            )
            corrected_data = extract_json(raw_text)
        else:
            corrected_data = _call_client_with_optional_scope(
                client.generate_json,
                system,
                user_prompt,
                purpose="correct",
                scope=scope,
            )
    except Exception:
        return reject_correction(
            client,
            question,
            CorrectionRejection(
                code="response_unreadable",
                path="$",
                message="correction response could not be read",
            ),
            on_rejected,
            on_decision=on_decision,
            scope=scope,
        )

    try:
        validate_correction_structure(corrected_data, question.subquestions)
    except CorrectionStructureError as exc:
        return reject_correction(
            client,
            question,
            exc.reason,
            on_rejected,
            on_decision=on_decision,
            scope=scope,
        )

    # Safely merge: only update fields the corrector is allowed to change
    update: dict = {}

    if "題目" in corrected_data:
        update["題目"] = corrected_data["題目"]

    if "正確解題分析" in corrected_data:
        update["正確解題分析"] = corrected_data["正確解題分析"]

    for key in ("chart_spec", "image_spec"):
        raw_spec = corrected_data.get(key)
        if raw_spec is not None:
            try:
                update["chart_spec"] = ImageSpec.model_validate(raw_spec)
            except Exception:
                return reject_correction(
                    client,
                    question,
                    CorrectionRejection(
                        code="image_spec_invalid",
                        path=key,
                        message="image specification is invalid",
                    ),
                    on_rejected,
                    on_decision=on_decision,
                    scope=scope,
                )

    if "誘答分析" in corrected_data:
        update["誘答分析"] = corrected_data["誘答分析"]

    corrected_subquestions = _parse_corrected_math_subquestions(
        corrected_data,
        question.subquestions,
    )
    if "subquestions" in corrected_data and corrected_subquestions is None:
        # An explicit empty list is a valid no-op for a genuinely empty
        # group (including a zero-survivor 題組).  Any non-empty original has
        # already failed the exact-list guard above.
        if corrected_data["subquestions"] == [] and not question.subquestions:
            update["subquestions"] = []
        else:
            return reject_correction(
                client,
                question,
                CorrectionRejection(
                    code="subquestion_invalid",
                    path="subquestions",
                    message="subquestion contains invalid data",
                ),
                on_rejected,
                on_decision=on_decision,
                scope=scope,
            )
    if corrected_subquestions is not None:
        update["subquestions"] = corrected_subquestions

    # Restore all frozen fields from original and clear stale verification
    update["verification"] = None

    # Difficulty is frozen — force the original metadata (and thus difficulty) through.
    update["metadata"] = question.metadata

    return apply_correction(
        client,
        question,
        update,
        on_rejected,
        on_decision=on_decision,
        scope=scope,
    )
