"""Shared correction implementation for NS and SS subjects.

Both the social-studies and natural-sciences correctors delegate the outer
LLM-call + top-level field update logic here.  Subject-specific subquestion
reconstruction is expressed as a ``rebuild_subquestion_fn`` callable so each
subject can freeze the right metadata fields and canonicalize codes as needed.

Rubric key tolerance
--------------------
Both subjects now read rubric entries tolerating the alternate key
``評分標準`` (in addition to the canonical ``評分規準``), via
:func:`parse_rubric`.  This converges the previously divergent behaviour
where SS was already tolerant and NS was not (issue #158 AC3).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from src.llm_client import LLMClient, extract_json

# Callable: (sq_raw, original_sq_or_None, idx) -> SubQuestion | None
RebuildSubquestionFn = Callable[[dict, Any, int], Any]

_CORRECTION_USER_TEMPLATE = """\
## 原始題目（JSON）

```json
{question_json}
```

## 審核意見

{verification_details}
{answer_block}{chart_details_block}{annotations_block}
請輸出修正後的題目 JSON。
"""


def build_annotations_block(annotations: str | None) -> str:
    """Render user 修改指示 as constraints the correction must preserve."""
    if not annotations:
        return ""
    return (
        "\n## 修改指示（必須保留）\n"
        "以下是使用者明確要求的修改指示。修正時必須保留使用者明確要求的內容，"
        "不得悄悄恢復或撤銷使用者明確要求的內容。\n\n"
        f"{annotations}\n"
    )


def parse_rubric(sq_raw: dict, rubric_entry_cls: type) -> list:
    """Parse rubric entries from *sq_raw*, tolerating both key spellings.

    Reads ``評分規準`` first; falls back to ``評分標準`` when the canonical
    key is absent or empty.  Returns an empty list when neither key is present
    or their values are not lists.
    """
    return [
        rubric_entry_cls(
            code=str(r.get("code", "")),
            規準說明=r.get("規準說明", ""),
            學生作答實例=r.get("學生作答實例", []),
        )
        for r in (sq_raw.get("評分規準") or sq_raw.get("評分標準") or [])
        if isinstance(r, dict)
    ]


def correct_question_common(
    client: LLMClient,
    question: Any,
    verification: Any,
    chart_image_path: str | None = None,
    system_prompt: str = "",
    rebuild_subquestion_fn: RebuildSubquestionFn | None = None,
    image_spec_cls: type | None = None,
    annotations: str | None = None,
    editable_paths: set[str] | None = None,
) -> Any:
    """Shared corrector core for questions with subquestions.

    Handles the LLM call, extraction of the corrected JSON, and updating of
    top-level mutable fields (``題目``, ``正確解題分析``, ``文本``,
    ``chart_spec``, ``verification``, ``metadata``).  Subquestion
    reconstruction is delegated to *rebuild_subquestion_fn*, which the
    subject module supplies.

    Args:
        client: LLM client.
        question: Subject exam-question object.
        verification: ``VerificationResult`` from the previous verify pass.
        chart_image_path: Path to a rendered chart PNG, if any.
        system_prompt: Full system prompt (curriculum prefix already
            prepended by the caller when required).
        rebuild_subquestion_fn: ``(sq_raw, original, idx) -> SubQuestion | None``.
            Called for each subquestion in the LLM response.  When ``original``
            is ``None`` the subquestion was added by the LLM.  Returning
            ``None`` drops the row.
        image_spec_cls: ``ImageSpec`` class for the subject (used to
            deserialise the top-level ``chart_spec``).
        annotations: Optional user 修改指示 that the correction must preserve.
        editable_paths: Optional field paths for a 人工審題修正 call.  The
            server remains the authoritative scope enforcer; this parameter
            lets subject rebuilders admit an explicitly selected chart_spec.

    Returns:
        The corrected question (a ``model_copy`` of *question* with updated
        fields), or the original *question* on LLM/parse failure.
    """
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
            f"\n## 素材審核意見\n"
            f"數據正確：{'是' if cv.chart_data_match else '否'}\n"
            f"標籤正確：{'是' if cv.chart_labels_correct else '否'}\n"
            f"說明：{cv.chart_details}\n"
        )

    user_prompt = _CORRECTION_USER_TEMPLATE.format(
        question_json=question_json,
        verification_details=verification.details,
        answer_block=answer_block,
        chart_details_block=chart_details_block,
        annotations_block=build_annotations_block(annotations),
    )

    try:
        if verification.chart_verification and chart_image_path:
            raw_text = client.generate_with_image(
                system_prompt, user_prompt, image_path=chart_image_path, purpose="correct"
            )
            corrected_data = extract_json(raw_text)
        else:
            corrected_data = client.generate_json(system_prompt, user_prompt, purpose="correct")
    except Exception:
        return question

    update: dict = {}

    if "題目" in corrected_data and isinstance(corrected_data["題目"], list):
        update["題目"] = corrected_data["題目"]

    if "正確解題分析" in corrected_data and isinstance(corrected_data["正確解題分析"], list):
        update["正確解題分析"] = corrected_data["正確解題分析"]

    if "文本" in corrected_data and isinstance(corrected_data["文本"], str):
        update["文本"] = corrected_data["文本"]

    if (
        rebuild_subquestion_fn is not None
        and "subquestions" in corrected_data
        and isinstance(corrected_data["subquestions"], list)
    ):
        new_sqs = []
        for idx, sq_raw in enumerate(corrected_data["subquestions"]):
            if not isinstance(sq_raw, dict):
                continue
            original = question.subquestions[idx] if idx < len(question.subquestions) else None
            rebuilt = rebuild_subquestion_fn(sq_raw, original, idx)
            if rebuilt is not None:
                new_sqs.append(rebuilt)
            elif original is not None:
                new_sqs.append(original)
        if new_sqs:
            update["subquestions"] = new_sqs

    raw_spec = corrected_data.get("image_spec") or corrected_data.get("chart_spec")
    chart_is_editable = editable_paths is None or any(
        path == "chart_spec" or path.startswith("chart_spec.")
        for path in editable_paths
    )
    if (
        raw_spec
        and isinstance(raw_spec, dict)
        and image_spec_cls is not None
        and chart_is_editable
    ):
        try:
            update["chart_spec"] = image_spec_cls(**raw_spec)
        except Exception:
            pass

    update["verification"] = None
    # Difficulty is frozen — force the original metadata (and thus difficulty) through.
    update["metadata"] = question.metadata

    return question.model_copy(update=update)
