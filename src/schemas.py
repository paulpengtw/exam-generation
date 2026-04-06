"""Pydantic data models for exam question generation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.schema_loader import build_enums, load_grades, load_schemas

# Load enum values from question_schemas.json at import time
_schemas = load_schemas()
QuestionContext, QuestionSetType, QuestionType, MathThinking, QuestionStyle = build_enums(_schemas)
_GRADES: list[int] = load_grades(_schemas)


class LearningContentItem(BaseModel):
    """A single curriculum learning content entry."""
    編碼: str
    說明: str


class ChartSpec(BaseModel):
    """Specification for generating a chart image."""
    chart_type: Literal["histogram", "boxplot", "line_chart", "pie_chart", "geometry"]
    title: str = ""
    data: dict = Field(default_factory=dict)
    labels: dict = Field(default_factory=dict)
    description: str = ""


class VerificationResult(BaseModel):
    """Result of the two-pass verification."""
    passed: bool
    answer_match: bool
    details: str


class QuestionMetadata(BaseModel):
    """Metadata about the generation process."""
    grade: int
    style: QuestionStyle  # type: ignore[valid-type]
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
    seed: int | None = None


class ExamQuestion(BaseModel):
    """A complete generated exam question."""
    id: str = ""
    情境: list[QuestionContext]  # type: ignore[valid-type]
    題型種類: QuestionSetType  # type: ignore[valid-type]
    題型: QuestionType  # type: ignore[valid-type]
    數學思考: list[MathThinking]  # type: ignore[valid-type]
    學習內容: list[LearningContentItem]
    題目: list[str]
    正確解題分析: list[str]
    圖片: str | None = None
    chart_spec: ChartSpec | None = None
    verification: VerificationResult | None = None
    metadata: QuestionMetadata | None = None


class SampledParams(BaseModel):
    """Parameters selected by the sampler for question generation."""
    grade: int

    @field_validator("grade")
    @classmethod
    def grade_must_be_allowed(cls, v: int) -> int:
        if v not in _GRADES:
            raise ValueError(f"grade must be one of {_GRADES}, got {v}")
        return v
    情境: list[QuestionContext]  # type: ignore[valid-type]
    題型種類: QuestionSetType  # type: ignore[valid-type]
    題型: QuestionType  # type: ignore[valid-type]
    數學思考: list[MathThinking]  # type: ignore[valid-type]
    學習內容: list[LearningContentItem]
    style: QuestionStyle  # type: ignore[valid-type]
