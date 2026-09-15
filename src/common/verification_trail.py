"""Typed, non-persistent verification-trail entries emitted during generation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from src.common.correction_decision import CorrectionRejection


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


class VerificationTrailInitialEntry(BaseModel):
    """The question snapshot captured immediately before its first verify pass."""

    code: Literal["verification_trail"] = "verification_trail"
    kind: Literal["initial"] = "initial"
    question_id: str
    timestamp: datetime
    snapshot: dict[str, Any]


class VerificationTrailCorrectionEntry(BaseModel):
    """The question snapshot captured after one corrector pass."""

    code: Literal["verification_trail"] = "verification_trail"
    kind: Literal["correction"] = "correction"
    question_id: str
    retry_index: int
    model: str
    timestamp: datetime
    snapshot: dict[str, Any]
    outcome: Literal["accepted", "rejected"] | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    reason: CorrectionRejection | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


VerificationTrailEvent = Annotated[
    VerificationTrailEntry | VerificationTrailInitialEntry | VerificationTrailCorrectionEntry,
    Field(discriminator="kind"),
]


_OMIT = object()


def _is_image_payload_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower().replace("-", "_")
    return any(
        marker in normalized
        for marker in ("base64", "image_bytes", "image_data", "image_b64", "b64_json")
    )


def _strip_image_payloads(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_image_payload_key(key):
                continue
            stripped = _strip_image_payloads(item)
            if stripped is not _OMIT:
                cleaned[key] = stripped
        return cleaned
    if isinstance(value, list):
        return [
            stripped
            for item in value
            if (stripped := _strip_image_payloads(item)) is not _OMIT
        ]
    if isinstance(value, tuple):
        return [
            stripped
            for item in value
            if (stripped := _strip_image_payloads(item)) is not _OMIT
        ]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _OMIT
    return value


def make_question_snapshot(question: Any) -> dict[str, Any]:
    """Serialize a question for the trail without verdicts or image payloads."""
    if hasattr(question, "model_dump"):
        payload = question.model_dump(mode="json", exclude={"verification"})
    elif hasattr(question, "model_dump_json"):
        payload = json.loads(question.model_dump_json(exclude={"verification"}))
    elif isinstance(question, Mapping):
        payload = dict(question)
        payload.pop("verification", None)
    else:
        payload = vars(question).copy()
        payload.pop("verification", None)

    cleaned = _strip_image_payloads(payload)
    return cleaned if isinstance(cleaned, dict) else {}


def make_initial_trail_entry(
    question_id: str,
    question: Any,
) -> VerificationTrailInitialEntry:
    """Build the initial snapshot entry for a question."""
    return VerificationTrailInitialEntry(
        question_id=question_id,
        timestamp=datetime.now(timezone.utc),
        snapshot=make_question_snapshot(question),
    )


def make_correction_trail_entry(
    question_id: str,
    question: Any,
    retry_index: int,
    model: str,
    *,
    outcome: Literal["accepted", "rejected"] | None = None,
    reason: CorrectionRejection | None = None,
) -> VerificationTrailCorrectionEntry:
    """Build a correction snapshot entry for a completed retry pass."""
    return VerificationTrailCorrectionEntry(
        question_id=question_id,
        retry_index=retry_index,
        model=model,
        timestamp=datetime.now(timezone.utc),
        snapshot=make_question_snapshot(question),
        outcome=outcome,
        reason=reason,
    )


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
