"""Generation stream v2 event protocol — contract types and helpers."""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, field_validator, model_validator

# Version of the in-process v2 event bus envelopes (started / result / ...).
PROTOCOL_VERSION = 2
# Submission protocol accepted by POST /api/generate: 3 = detached-run 受理
# (openspec detached-generation-runs D8). Streaming version 2 is refused with 426.
SUPPORTED_STREAM_VERSIONS: tuple[int, ...] = (3,)
CLIENT_UPDATE_REQUIRED_DETAIL = "介面版本已更新，請重新整理頁面後再生成。"


def client_update_required_body() -> dict[str, Any]:
    """Return the 426 response body dict."""
    return {
        "detail": CLIENT_UPDATE_REQUIRED_DETAIL,
        "code": "CLIENT_UPDATE_REQUIRED",
        "supported_stream_versions": list(SUPPORTED_STREAM_VERSIONS),
    }


class EventContext(BaseModel):
    """Immutable context attached to every generated event envelope."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str
    event_seq: int
    question_id: str | None = None
    index: int | None = None
    subquestion_index: int | None = None
    operation_id: str | None = None
    call_id: str | None = None
    content_revision: int | None = None

    @field_validator("event_seq")
    @classmethod
    def _seq_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("event_seq must be >= 1")
        return v


class SlotRef(BaseModel):
    """Reference to a content slot (subquestion or image)."""

    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["subquestion", "image"]
    question_id: str
    subquestion_id: str | None = None
    subquestion_index: StrictInt | None = None
    reason: str | None = None

    @field_validator("question_id")
    @classmethod
    def _question_id_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("question_id must not be empty")
        return value

    @field_validator("subquestion_index")
    @classmethod
    def _subquestion_index_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("subquestion_index must be >= 0")
        return value


class StartedPayload(BaseModel):
    """Payload for the 'started' event."""

    model_config = ConfigDict(populate_by_name=True)

    protocol_version: Literal[2]
    total: int
    questions: list[dict]
    generation_log_id: str | None = None

    @model_validator(mode="after")
    def _validate_questions(self) -> "StartedPayload":
        total = self.total
        questions = self.questions
        if len(questions) != total:
            raise ValueError(
                f"questions length {len(questions)} does not match total {total}"
            )
        for i, q in enumerate(questions):
            if q.get("index") != i:
                raise ValueError(
                    f"questions[{i}].index is {q.get('index')!r}, expected {i}"
                )
        ids = [q.get("question_id") for q in questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question_id values must be unique")
        return self


class QuestionTerminalPayload(BaseModel):
    """Terminal evidence for one question's generation lifecycle."""

    model_config = ConfigDict(populate_by_name=True)

    termination_reason: Literal["normal", "failed", "cancelled"]
    has_final: bool
    final_revision: StrictInt | None = None
    delivery_status: Literal["complete", "partial", "none", "unknown"]
    expected: list[SlotRef]
    delivered: list[SlotRef]
    missing: list[SlotRef]
    review: dict
    unknown_reason: str | None = None

    @model_validator(mode="after")
    def _validate_terminal(self) -> "QuestionTerminalPayload":
        def slot_key(slot: SlotRef) -> tuple[str, str, str | None, int | None]:
            # ``reason`` is explanatory evidence, not slot identity.  The
            # identity tuple is deliberately the same across expected,
            # delivered and missing so a sender cannot silently change the
            # delivery partition by adding a reason string.
            return (
                slot.kind,
                slot.question_id,
                slot.subquestion_id,
                slot.subquestion_index,
            )

        def unique_keys(
            name: str,
            slots: list[SlotRef],
        ) -> set[tuple[str, str, str | None, int | None]]:
            keys = [slot_key(slot) for slot in slots]
            if len(keys) != len(set(keys)):
                raise ValueError(f"{name} contains duplicate slot identities")
            return set(keys)

        expected_keys = unique_keys("expected", self.expected)
        delivered_keys = unique_keys("delivered", self.delivered)
        missing_keys = unique_keys("missing", self.missing)
        if delivered_keys & missing_keys:
            raise ValueError("delivered and missing slots must be disjoint")
        if not delivered_keys <= expected_keys:
            raise ValueError("delivered slots must be present in expected")
        if not missing_keys <= expected_keys:
            raise ValueError("missing slots must be present in expected")
        if delivered_keys | missing_keys != expected_keys:
            raise ValueError("expected slots must be partitioned by delivered and missing")

        if self.has_final:
            if self.final_revision is None or self.final_revision < 1:
                raise ValueError("has_final=True requires final_revision >= 1")
            if self.delivery_status == "none":
                raise ValueError("has_final=True cannot have delivery_status='none'")
        else:
            if self.final_revision is not None:
                raise ValueError("has_final=False requires final_revision=None")
            if self.delivery_status not in ("none", "unknown"):
                raise ValueError(
                    "has_final=False requires delivery_status in ('none', 'unknown')"
                )

        if self.termination_reason == "cancelled" and self.has_final:
            raise ValueError("termination_reason='cancelled' cannot have final content")

        if self.delivery_status == "complete" and self.missing:
            raise ValueError("delivery_status='complete' requires missing == []")

        if self.delivery_status == "complete" and not self.has_final:
            raise ValueError("delivery_status='complete' requires has_final=True")

        if self.delivery_status == "none" and self.delivered:
            raise ValueError("delivery_status='none' cannot contain delivered slots")

        if (
            self.delivery_status == "none"
            and set(slot_key(slot) for slot in self.missing) != expected_keys
        ):
            raise ValueError("delivery_status='none' requires every expected slot to be missing")

        if self.delivery_status == "partial":
            if not self.has_final:
                raise ValueError("delivery_status='partial' requires has_final=True")
            if not self.missing:
                raise ValueError("delivery_status='partial' requires missing non-empty")

        if self.delivery_status == "unknown" and not self.unknown_reason:
            raise ValueError("delivery_status='unknown' requires unknown_reason")

        review_status = self.review.get("status")
        if review_status not in ("passed", "failed", "skipped", "unknown"):
            raise ValueError("review.status must be passed, failed, skipped, or unknown")
        if not self.has_final and review_status != "unknown":
            raise ValueError("has_final=False requires review.status='unknown'")
        if self.has_final and review_status == "unknown":
            reason = self.review.get("reason") or self.review.get("unknown_reason")
            if not reason:
                raise ValueError("unknown review requires a reason")
        if review_status in ("passed", "failed", "skipped"):
            if not self.has_final:
                raise ValueError("definitive review requires final content")
            review_revision = self.review.get("content_revision")
            if (
                not isinstance(review_revision, int)
                or isinstance(review_revision, bool)
                or review_revision != self.final_revision
            ):
                raise ValueError(
                    f"review.content_revision must equal final_revision "
                    f"({review_revision!r} != {self.final_revision!r})"
                )

        return self


def envelope_dict(context: EventContext, payload: Any) -> dict[str, Any]:
    """Build an envelope dict with a deep-copied payload.

    Returns {'context': {...}, 'payload': <deep copy of payload>}.
    No envelope keys are inside the payload.
    """
    return {
        "context": context.model_dump(exclude_none=True),
        "payload": copy.deepcopy(payload),
    }
