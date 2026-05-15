"""Pydantic data models for social studies (PISA reading literacy) question generation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.social_studies.schema_loader import build_enums, load_grades, load_schemas

_schemas = load_schemas()
QuestionContext, QuestionSetType, QuestionType, ReadingProcess, TextForm, QuestionStyle = build_enums(_schemas)
_GRADES: list[int] = load_grades(_schemas)


class ImageSpec(BaseModel):
    render_mode: Literal["chart", "html"] = "chart"
    chart_type: Literal["histogram", "boxplot", "line_chart", "pie_chart"] | None = None
    title: str = ""
    data: dict = Field(default_factory=dict)
    labels: dict = Field(default_factory=dict)
    html: str = ""
    description: str = ""


ChartSpec = ImageSpec


class ChartVerificationResult(BaseModel):
    chart_data_match: bool
    chart_labels_correct: bool
    chart_details: str


class VerificationResult(BaseModel):
    passed: bool
    answer_match: bool
    details: str
    my_answer: str = ""
    provided_answer: str = ""
    chart_verification: ChartVerificationResult | None = None


class QuestionMetadata(BaseModel):
    grade: int
    style: QuestionStyle  # type: ignore[valid-type]
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
    seed: int | None = None


class ExamQuestion(BaseModel):
    """A complete generated PISA-reading exam question."""
    id: str = ""
    情境: list[QuestionContext]  # type: ignore[valid-type]
    題型種類: QuestionSetType  # type: ignore[valid-type]
    題型: QuestionType  # type: ignore[valid-type]
    閱讀歷程: list[ReadingProcess]  # type: ignore[valid-type]
    文本形式: TextForm  # type: ignore[valid-type]
    題目: list[str]
    正確解題分析: list[str]
    圖片: str | None = None
    chart_spec: ChartSpec | None = None
    verification: VerificationResult | None = None
    metadata: QuestionMetadata | None = None


class SampledParams(BaseModel):
    """Parameters selected by the sampler for social-studies question generation."""
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
    閱讀歷程: list[ReadingProcess]  # type: ignore[valid-type]
    文本形式: TextForm  # type: ignore[valid-type]
    style: QuestionStyle  # type: ignore[valid-type]
