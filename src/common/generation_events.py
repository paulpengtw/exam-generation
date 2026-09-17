"""Immutable generation identity types shared by CLI, core, and server."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    run_id: str


@dataclass(frozen=True)
class QuestionContext:
    run_id: str
    question_id: str
    index: int


def new_run_id() -> str:
    """Return a new UUID4 as a hex string (no dashes)."""
    return uuid.uuid4().hex


def allocate_manifest(
    subject_prefix: str,
    run_id: str,
    count: int,
) -> tuple[QuestionContext, ...]:
    """Allocate a fixed manifest of QuestionContext for a batch.

    question_id format: f'{subject_prefix}{run_id}_{index+1:03d}'
    where index is 0-based and the ordinal is zero-padded to 3 digits minimum.
    """
    return tuple(
        QuestionContext(
            run_id=run_id,
            question_id=f"{subject_prefix}{run_id}_{i + 1:03d}",
            index=i,
        )
        for i in range(count)
    )
