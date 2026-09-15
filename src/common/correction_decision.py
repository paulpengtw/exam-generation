"""Structured result information emitted by a correction attempt.

The correction pass can reject an LLM response after inspecting the complete
candidate.  Keeping that outcome in a small immutable model gives callers a
safe diagnostic without exposing provider output or answer text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class CorrectionRejection(BaseModel):
    """Safe, stable diagnostic information for a rejected correction."""

    model_config = ConfigDict(frozen=True)

    code: str
    path: str
    message: str


class CorrectionDecision(BaseModel):
    """The final outcome of one correction call.

    An accepted correction has no rejection reason.  A rejected correction
    always carries structured evidence so callers cannot mistake it for a
    successful pass.
    """

    model_config = ConfigDict(frozen=True)

    outcome: Literal["accepted", "rejected"]
    reason: CorrectionRejection | None = None

    @model_validator(mode="after")
    def _require_reason_for_rejection(self) -> "CorrectionDecision":
        if self.outcome == "rejected" and self.reason is None:
            raise ValueError("a rejected correction requires a reason")
        if self.outcome == "accepted" and self.reason is not None:
            raise ValueError("an accepted correction cannot carry a rejection reason")
        return self
