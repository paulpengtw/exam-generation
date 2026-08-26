"""Typed events for the shared 圖像種類 policy trail."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from src.common.figure_policy import effective_figure_kind


class FigurePolicySpecEntry(BaseModel):
    """The effective 圖像種類 observed for one 題幹 or 小題 visual spec."""

    code: Literal["figure_policy"] = "figure_policy"
    kind: Literal["spec"] = "spec"
    question_id: str
    label: str
    effective_figure_kind: str
    timestamp: datetime


class FigurePolicyCollisionEntry(BaseModel):
    """One pair of specs that currently shares a normalized kind."""

    code: Literal["figure_policy"] = "figure_policy"
    kind: Literal["collision"] = "collision"
    question_id: str
    left: str
    right: str
    effective_figure_kind: str
    timestamp: datetime


class FigurePolicyRepairEntry(BaseModel):
    """The result of one targeted, one-budget figure-kind repair attempt."""

    code: Literal["figure_policy"] = "figure_policy"
    kind: Literal["repair"] = "repair"
    question_id: str
    target: str
    before_effective_figure_kind: str
    after_effective_figure_kind: str
    forbidden_kinds: list[str]
    succeeded: bool
    error: str | None = None
    timestamp: datetime


class FigurePolicyWarningEntry(BaseModel):
    """A final degrade-never-block warning about a shipped duplicate."""

    code: Literal["figure_policy"] = "figure_policy"
    kind: Literal["warning"] = "warning"
    question_id: str
    message: str
    duplicate_image_shipped: bool = True
    left: str | None = None
    right: str | None = None
    effective_figure_kind: str | None = None
    timestamp: datetime


FigurePolicyTrailEvent = Annotated[
    FigurePolicySpecEntry
    | FigurePolicyCollisionEntry
    | FigurePolicyRepairEntry
    | FigurePolicyWarningEntry,
    Field(discriminator="kind"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_spec_entry(question_id: str, label: str, spec: Any) -> FigurePolicySpecEntry:
    return FigurePolicySpecEntry(
        question_id=question_id,
        label=label,
        effective_figure_kind=effective_figure_kind(spec),
        timestamp=_now(),
    )


def make_collision_entry(
    question_id: str,
    left: str,
    right: str,
    effective_kind: str,
) -> FigurePolicyCollisionEntry:
    return FigurePolicyCollisionEntry(
        question_id=question_id,
        left=left,
        right=right,
        effective_figure_kind=effective_kind,
        timestamp=_now(),
    )


def make_repair_entry(
    question_id: str,
    target: str,
    before_kind: str,
    after_kind: str,
    forbidden_kinds: list[str],
    succeeded: bool,
    error: str | None = None,
) -> FigurePolicyRepairEntry:
    return FigurePolicyRepairEntry(
        question_id=question_id,
        target=target,
        before_effective_figure_kind=before_kind,
        after_effective_figure_kind=after_kind,
        forbidden_kinds=forbidden_kinds,
        succeeded=succeeded,
        error=error,
        timestamp=_now(),
    )


def make_warning_entry(
    question_id: str,
    message: str,
    *,
    duplicate_image_shipped: bool = True,
    left: str | None = None,
    right: str | None = None,
    effective_kind: str | None = None,
) -> FigurePolicyWarningEntry:
    return FigurePolicyWarningEntry(
        question_id=question_id,
        message=message,
        duplicate_image_shipped=duplicate_image_shipped,
        left=left,
        right=right,
        effective_figure_kind=effective_kind,
        timestamp=_now(),
    )
