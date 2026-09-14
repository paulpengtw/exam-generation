"""Shared correction implementation for NS and SS subjects.

Both the social-studies and natural-sciences correctors delegate the outer
LLM-call + top-level field update logic here.  Subject-specific subquestion
reconstruction is expressed as a ``rebuild_subquestion_fn`` callable so each
subject can freeze the right metadata fields. A candidate is accepted only
when its complete 小題 structure and editable content validate together.

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

from pydantic import ValidationError

from src.llm_client import LLMClient, emit_stage, extract_json

# Callable: (sq_raw, original_sq, idx) -> SubQuestion | None
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
    key is absent or empty. Returns an empty list when neither key is present.
    Malformed entries reject the correction instead of being silently skipped.
    """
    for key in ("評分規準", "評分標準"):
        if key in sq_raw:
            rows = sq_raw[key]
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError(f"{key} must be a list of objects")
            if any(type(row.get("code")) not in (str, int) for row in rows):
                raise ValueError(f"{key} contains an invalid code")
    return [
        rubric_entry_cls(
            code=str(r.get("code", "")),
            規準說明=r.get("規準說明", ""),
            學生作答實例=r.get("學生作答實例", []),
        )
        for r in (sq_raw.get("評分規準") or sq_raw.get("評分標準") or [])
    ]


def validate_correction_structure(candidate: object, originals: list[Any]) -> None:
    """Require a complete, ordered list with unambiguous original identities.

    An explicit id or 序號 can identify a row. If both are supplied they must
    agree; array position alone never establishes identity. Compare against
    the surviving input rows, without padding gaps from generation.
    """
    if not isinstance(candidate, dict):
        raise ValueError("correction must be an object")
    if not originals and "subquestions" not in candidate:
        return
    rows = candidate.get("subquestions")
    if not isinstance(rows, list):
        raise ValueError("subquestions must be a complete list")
    if len(rows) != len(originals):
        raise ValueError(f"小題 count changed: expected {len(originals)}, received {len(rows)}")
    for index, (raw, original) in enumerate(zip(rows, originals)):
        if not isinstance(raw, dict):
            raise ValueError(f"小題 {index + 1} must be an object")
        identity = {}
        if "id" in raw:
            if not isinstance(raw["id"], str) or raw["id"] != original.id:
                raise ValueError(f"小題 {index + 1} id changed or reordered")
            if raw["id"]:
                identity["id"] = raw["id"]
        if "序號" in raw:
            if type(raw["序號"]) is not int or raw["序號"] != original.序號:
                raise ValueError(f"小題 {index + 1} 序號 changed or reordered")
            identity["序號"] = raw["序號"]
        matches = [
            row for row in originals
            if identity and all(getattr(row, key) == value for key, value in identity.items())
        ]
        if len(matches) != 1:
            raise ValueError(f"小題 {index + 1} identity is missing or ambiguous")


def reject_correction(
    client: LLMClient,
    question: Any,
    reason: str,
    on_rejected: Callable[[str], None] | None,
) -> Any:
    """Retain the entire snapshot and report why this attempt was rejected."""
    if on_rejected is not None:
        on_rejected(reason)
    else:
        observer = client.get_observer() if hasattr(client, "get_observer") else None
        emit_stage(
            observer, "corrector", "correct", "error",
            code="correction_rejected", message=reason,
        )
    return question


def apply_correction(
    client: LLMClient,
    question: Any,
    update: dict,
    on_rejected: Callable[[str], None] | None,
) -> Any:
    """Validate the full merged snapshot before accepting any of its edits."""
    try:
        type(question).model_validate({**question.model_dump(), **update})
    except ValidationError:
        return reject_correction(client, question, "correction contains invalid data", on_rejected)
    return question.model_copy(update=update)


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
    on_rejected: Callable[[str], None] | None = None,
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
            Called only after the full candidate's identities and order match
            the originals. Returning ``None`` rejects the entire correction.
        image_spec_cls: ``ImageSpec`` class for the subject (used to
            deserialise the top-level ``chart_spec``).
        annotations: Optional user 修改指示 that the correction must preserve.
        editable_paths: Optional field paths for a 人工審題修正 call.  The
            server remains the authoritative scope enforcer; this parameter
            lets subject rebuilders admit an explicitly selected chart_spec.
        on_rejected: Receives a concise rejection reason. The generation loop
            uses it to retain the snapshot, record the failed attempt, and
            skip publication and re-verification until a correction is accepted.

    Returns:
        The corrected question (a ``model_copy`` of *question* with updated
        fields), or the complete original *question* on rejection or failure.
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
        return reject_correction(
            client, question, "correction response could not be read", on_rejected,
        )

    try:
        validate_correction_structure(corrected_data, question.subquestions)
    except ValueError as exc:
        return reject_correction(client, question, str(exc), on_rejected)

    update: dict = {}

    if "題目" in corrected_data:
        update["題目"] = corrected_data["題目"]

    if "正確解題分析" in corrected_data:
        update["正確解題分析"] = corrected_data["正確解題分析"]

    if "文本" in corrected_data:
        update["文本"] = corrected_data["文本"]

    if (
        rebuild_subquestion_fn is not None
        and "subquestions" in corrected_data
        and isinstance(corrected_data["subquestions"], list)
    ):
        new_sqs = []
        for idx, sq_raw in enumerate(corrected_data["subquestions"]):
            original = question.subquestions[idx]
            rebuilt = rebuild_subquestion_fn(sq_raw, original, idx)
            if rebuilt is None:
                return reject_correction(
                    client, question, f"小題 {idx + 1} contains invalid row data", on_rejected,
                )
            # Keep generation-owned slot metadata (notably _plan_index) so
            # later image rendering uses the original 各小題配置, even when
            # the model-reported 序號 differs from its generation slot.
            new_sqs.append(original.model_copy(update={
                field: getattr(rebuilt, field) for field in type(rebuilt).model_fields
            }))
        if new_sqs:
            update["subquestions"] = new_sqs

    chart_is_editable = editable_paths is None or any(
        path == "chart_spec" or path.startswith("chart_spec.")
        for path in editable_paths
    )
    if image_spec_cls is not None and chart_is_editable:
        for key in ("chart_spec", "image_spec"):
            raw_spec = corrected_data.get(key)
            if raw_spec is not None:
                try:
                    update["chart_spec"] = image_spec_cls.model_validate(raw_spec)
                except ValidationError:
                    return reject_correction(
                        client, question, f"{key} contains invalid data", on_rejected,
                    )

    update["verification"] = None
    # Difficulty is frozen — force the original metadata (and thus difficulty) through.
    update["metadata"] = question.metadata

    return apply_correction(client, question, update, on_rejected)
