"""Shared normalization and admission rules for fixed subquestion slots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.common.open_response_rubric import (
    check_open_response_rubric_shape,
    is_open_response,
)


def normalize_rubric_student_examples(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Copy rubric rows and wrap a scalar student example in a one-item list.

    Only strings are safely normalizable. Other shapes are retained so the
    subject's Pydantic schema rejects them through the existing diagnostic path.
    """
    normalized: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        examples = copied.get("學生作答實例")
        if isinstance(examples, str):
            copied["學生作答實例"] = [examples]
        normalized.append(copied)
    return normalized


def apply_fixed_subquestion_contract(
    subquestion: Any,
    *,
    question_id: str,
    plan_position: int,
    slot_config: Any | None,
    fixed_identity: bool,
) -> str | None:
    """Apply program-owned fixed-slot fields and return a safe shape issue."""
    if not fixed_identity:
        return None

    slot_number = plan_position + 1
    subquestion.id = f"{question_id}-sq{slot_number:03d}"
    subquestion.序號 = slot_number
    if hasattr(subquestion, "_plan_index"):
        subquestion._plan_index = slot_number

    if slot_config is not None:
        configured_type = getattr(slot_config, "question_type", None)
        if configured_type is not None:
            subquestion.題型 = configured_type
        configured_content_type = getattr(slot_config, "content_type", None)
        if configured_content_type is not None:
            subquestion.題目內容類型 = configured_content_type

    if not is_open_response(getattr(subquestion, "題型", None)):
        return None
    issues = check_open_response_rubric_shape([subquestion])
    return issues[0] if issues else None
