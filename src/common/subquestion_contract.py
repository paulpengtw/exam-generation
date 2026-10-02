"""Shared normalization and admission rules for fixed subquestion slots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


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
