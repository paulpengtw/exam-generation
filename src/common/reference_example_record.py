"""Pydantic models for 參考範例紀錄."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class ReferenceExampleExampleEntry(BaseModel):
    """One few-shot example drawn during generation."""

    code: Literal["reference_example"] = "reference_example"
    kind: Literal["example"] = "example"
    question_id: str
    stage: str  # "generator" | "text_generator" | "subquestion_generator"
    slot: int | None = None
    description: str
    source: str
    content: Any = None
    images: list[dict[str, str]] = Field(default_factory=list)
    timestamp: datetime


class ReferenceExampleProcessExemplarEntry(BaseModel):
    """One process exemplar drawn during generation."""

    code: Literal["reference_example"] = "reference_example"
    kind: Literal["process_exemplar"] = "process_exemplar"
    question_id: str
    stage: str
    slot: int | None = None
    cognitive_process: str
    source: str
    content: Any = None
    timestamp: datetime


ReferenceExampleEntry = Annotated[
    ReferenceExampleExampleEntry | ReferenceExampleProcessExemplarEntry,
    Field(discriminator="kind"),
]


class ReferenceExampleRecord(BaseModel):
    """The complete 參考範例紀錄 for one question generation."""

    disabled: bool
    entries: list[
        ReferenceExampleExampleEntry | ReferenceExampleProcessExemplarEntry
    ] = Field(default_factory=list)
