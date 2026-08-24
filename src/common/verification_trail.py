"""Typed, non-persistent verification-trail entries emitted during generation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel


class ChartVerificationTrail(BaseModel):
    """The chart verdict fields copied from a parsed verification result."""

    chart_data_match: bool
    chart_labels_correct: bool
    chart_details: str


class VerificationTrailEntry(BaseModel):
    """One verification verdict in a question's future-persisted trail."""

    code: Literal["verification_trail"] = "verification_trail"
    kind: Literal["verification"] = "verification"
    question_id: str
    passed: bool
    details: str
    my_answer: str
    provided_answer: str
    answer_match: bool
    chart_verification: ChartVerificationTrail | None = None
    model: str
    timestamp: datetime


def make_verification_trail_entry(
    question_id: str,
    verification: Any,
    model: str,
) -> VerificationTrailEntry:
    """Copy a parsed subject verifier result into the shared trail shape."""
    chart_verification = getattr(verification, "chart_verification", None)
    if chart_verification is not None:
        chart_verification = ChartVerificationTrail.model_validate(
            chart_verification.model_dump()
            if hasattr(chart_verification, "model_dump")
            else chart_verification
        )

    return VerificationTrailEntry(
        question_id=question_id,
        passed=verification.passed,
        details=verification.details,
        my_answer=verification.my_answer,
        provided_answer=verification.provided_answer,
        answer_match=verification.answer_match,
        chart_verification=chart_verification,
        model=model,
        timestamp=datetime.now(timezone.utc),
    )
