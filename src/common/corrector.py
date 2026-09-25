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

import inspect
import json
from copy import deepcopy
from typing import Any, Callable

from src.common.correction_decision import CorrectionDecision, CorrectionRejection
from src.common.generation_events import OperationScope
from src.llm_client import LLMClient, emit_stage, extract_json

# Callable: (sq_raw, original_sq, idx) -> SubQuestion | None
RebuildSubquestionFn = Callable[[dict, Any, int], Any]
DecisionCallback = Callable[[CorrectionDecision], None]


def _call_client_with_optional_scope(
    method: Callable,
    *args: Any,
    scope: OperationScope | None,
    **kwargs: Any,
) -> Any:
    """Pass scope to real clients without breaking legacy correction fakes."""
    if scope is not None:
        try:
            parameters = inspect.signature(method).parameters
            accepts_scope = "scope" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):
            accepts_scope = False
        if accepts_scope:
            kwargs["scope"] = scope
    return method(*args, **kwargs)


class CorrectionStructureError(ValueError):
    """A candidate failed the public correction structure contract."""

    def __init__(self, reason: CorrectionRejection):
        self.reason = reason
        super().__init__(reason.message)


def _rejection(code: str, path: str, message: str) -> CorrectionRejection:
    return CorrectionRejection(code=code, path=path, message=message)

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


def validate_correction_structure(
    candidate: object,
    originals: list[Any],
    *,
    program_owned_subquestion_identity: bool = False,
) -> None:
    """Require a complete, ordered list with unambiguous original identities.

    An explicit id or 序號 can identify a row. If both are supplied they must
    agree; array position alone never establishes identity. Compare against
    the surviving input rows, without padding gaps from generation.

    For generation pipelines with program-owned fixed slots, the array
    position is already the identity.  Model-supplied ids and ordinals are
    deliberately ignored there; the subject rebuilder restores the original
    slot metadata after validating the row's editable content.
    """
    if not isinstance(candidate, dict):
        raise CorrectionStructureError(
            _rejection("response_shape", "$", "correction must be an object")
        )
    # The list is optional.  Omitting it means that the corrector made no
    # subquestion edit; an explicitly supplied list still has to account for
    # every entering row exactly.
    if "subquestions" not in candidate:
        return
    rows = candidate["subquestions"]
    if not isinstance(rows, list):
        raise CorrectionStructureError(
            _rejection("subquestions_type", "subquestions", "subquestions must be a list")
        )
    if len(rows) != len(originals):
        raise CorrectionStructureError(
            _rejection("subquestions_count", "subquestions", "subquestions count changed")
        )
    for index, (raw, original) in enumerate(zip(rows, originals)):
        path = f"subquestions[{index}]"
        if not isinstance(raw, dict):
            raise CorrectionStructureError(
                _rejection("subquestion_row_type", path, "subquestion row must be an object")
            )
        if program_owned_subquestion_identity:
            continue
        identity = {}
        if "id" in raw:
            if not isinstance(raw["id"], str) or raw["id"] != getattr(original, "id", None):
                raise CorrectionStructureError(
                    _rejection(
                        "subquestion_identity_mismatch",
                        path,
                        "subquestion id changed or reordered",
                    )
                )
            if raw["id"]:
                identity["id"] = raw["id"]
        if "序號" in raw:
            if type(raw["序號"]) is not int or raw["序號"] != getattr(original, "序號", None):
                raise CorrectionStructureError(
                    _rejection(
                        "subquestion_identity_mismatch",
                        path,
                        "subquestion ordinal changed or reordered",
                    )
                )
            identity["序號"] = raw["序號"]
        matches = [
            row for row in originals
            if identity and all(getattr(row, key) == value for key, value in identity.items())
        ]
        if len(matches) != 1:
            raise CorrectionStructureError(
                _rejection(
                    "subquestion_identity_ambiguous",
                    path,
                    "subquestion identity is missing or ambiguous",
                )
            )


def reject_correction(
    client: LLMClient,
    question: Any,
    reason: CorrectionRejection | str,
    on_rejected: Callable[[str], None] | None = None,
    *,
    on_decision: DecisionCallback | None = None,
    scope: OperationScope | None = None,
) -> Any:
    """Retain the entire snapshot and report why this attempt was rejected."""
    if isinstance(reason, str):
        # Keep the old helper callable for integrations that still pass a
        # concise string.  All internal rejection paths use a structured
        # reason before reaching this compatibility branch.
        reason = _rejection("correction_rejected", "$", reason)
    decision = CorrectionDecision(outcome="rejected", reason=reason)
    if on_decision is not None:
        on_decision(decision)
    if on_rejected is not None:
        on_rejected(reason.message)
    elif on_decision is None:
        observer = client.get_observer() if hasattr(client, "get_observer") else None
        emit_stage(
            observer, "corrector", "correct", "error",
            scope=scope,
            code="correction_rejected", message=reason.message,
            reason=reason.model_dump(),
        )
    return question


def apply_correction(
    client: LLMClient,
    question: Any,
    update: dict,
    on_rejected: Callable[[str], None] | None = None,
    *,
    on_decision: DecisionCallback | None = None,
    scope: OperationScope | None = None,
) -> Any:
    """Validate the full merged snapshot before accepting any of its edits."""
    try:
        type(question).model_validate({**question.model_dump(), **update})
    except Exception:
        return reject_correction(
            client,
            question,
            _rejection("merged_question_invalid", "$", "correction contains invalid data"),
            on_rejected,
            on_decision=on_decision,
            scope=scope,
        )

    # model_copy(deep=True) detaches both public nested fields and Pydantic
    # PrivateAttr values such as generation slot/visual associations.  The
    # callback is emitted only after this complete candidate exists.
    try:
        accepted = question.model_copy(deep=True, update=deepcopy(update))
    except Exception:
        return reject_correction(
            client,
            question,
            _rejection("detached_candidate_invalid", "$", "correction could not be detached"),
            on_rejected,
            on_decision=on_decision,
            scope=scope,
        )
    if on_decision is not None:
        on_decision(CorrectionDecision(outcome="accepted"))
    return accepted


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
    on_decision: DecisionCallback | None = None,
    program_owned_subquestion_identity: bool = False,
    scope: OperationScope | None = None,
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
        on_rejected: Legacy callback receiving a concise rejection message.
            New generation callers should use ``on_decision`` so they can
            distinguish rejection from acceptance while retaining the input
            snapshot.
        on_decision: Receives exactly one immutable accepted/rejected decision
            after the complete candidate has been validated.

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
            raw_text = _call_client_with_optional_scope(
                client.generate_with_image,
                system_prompt,
                user_prompt,
                image_path=chart_image_path,
                purpose="correct",
                scope=scope,
            )
            corrected_data = extract_json(raw_text)
        else:
            corrected_data = _call_client_with_optional_scope(
                client.generate_json,
                system_prompt,
                user_prompt,
                purpose="correct",
                scope=scope,
            )
    except Exception:
        return reject_correction(
            client,
            question,
            _rejection("response_unreadable", "$", "correction response could not be read"),
            on_rejected,
            on_decision=on_decision,
            scope=scope,
        )

    try:
        validate_correction_structure(
            corrected_data,
            question.subquestions,
            program_owned_subquestion_identity=program_owned_subquestion_identity,
        )
    except CorrectionStructureError as exc:
        return reject_correction(
            client, question, exc.reason, on_rejected, on_decision=on_decision,
            scope=scope,
        )

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
            try:
                rebuilt = rebuild_subquestion_fn(sq_raw, original, idx)
            except Exception:
                rebuilt = None
            if rebuilt is None:
                return reject_correction(
                    client,
                    question,
                    _rejection(
                        "subquestion_invalid",
                        f"subquestions[{idx}]",
                        "subquestion contains invalid data",
                    ),
                    on_rejected,
                    on_decision=on_decision,
                    scope=scope,
                )
            # Keep generation-owned slot metadata (notably _plan_index) so
            # later image rendering uses the original 各小題配置, even when
            # the model-reported 序號 differs from its generation slot.
            new_sqs.append(original.model_copy(deep=True, update={
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
                except Exception:
                    return reject_correction(
                        client,
                        question,
                        _rejection("image_spec_invalid", key, "image specification is invalid"),
                        on_rejected,
                        on_decision=on_decision,
                        scope=scope,
                    )

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
