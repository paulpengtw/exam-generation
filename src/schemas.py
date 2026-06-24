"""Pydantic data models for exam question generation."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.common.core_competency_loader import (
    build_core_competency_enum,
    load_core_competencies,
)
from src.schema_loader import build_enums, load_grades, load_schemas

# Load enum values from question_schemas.json at import time
_schemas = load_schemas()
QuestionContext, QuestionSetType, QuestionType, MathThinking, QuestionStyle = build_enums(_schemas)
_GRADES: list[int] = load_grades(_schemas)

# Math 核心素養 enum, built from data/math/curriculum/core_competencies.json.
_MATH_CC_PATH = (
    Path(__file__).parent.parent / "data" / "math" / "curriculum" / "core_competencies.json"
)
_MATH_CC_DATA = load_core_competencies(_MATH_CC_PATH)
CoreCompetency = build_core_competency_enum(
    _MATH_CC_DATA, subject_prefix="數", enum_name="CoreCompetency"
)


class QuestionSubject(str, Enum):
    """Math subject focus categories (科目)."""
    數與量 = "數與量"
    代數 = "代數"
    幾何 = "幾何"
    統計與機率 = "統計與機率"
    跨領域 = "跨領域"


class LearningContentItem(BaseModel):
    """A single curriculum learning content entry."""
    編碼: str
    說明: str


class ImageSpec(BaseModel):
    """Specification for generating a question image.

    Two render modes:
    - render_mode="chart": structured data rendered by matplotlib (histogram, boxplot, etc.)
    - render_mode="html": LLM generates HTML/CSS/SVG, rendered to PNG via Playwright
    """
    render_mode: Literal["chart", "html"] = "chart"
    # chart mode fields
    chart_type: Literal["histogram", "boxplot", "line_chart", "pie_chart"] | None = None
    title: str = ""
    data: dict = Field(default_factory=dict)
    labels: dict = Field(default_factory=dict)
    # html mode fields
    html: str = ""
    description: str = ""


# Backward-compatible alias
ChartSpec = ImageSpec


class ChartVerificationResult(BaseModel):
    """Result of chart/diagram verification."""
    chart_data_match: bool
    chart_labels_correct: bool
    chart_details: str


class VerificationResult(BaseModel):
    """Result of the two-pass verification."""
    passed: bool
    answer_match: bool
    details: str
    my_answer: str = ""
    provided_answer: str = ""
    chart_verification: ChartVerificationResult | None = None


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
    # Phase 3: optional curriculum-aware metadata (flat-question structure preserved)
    核心素養: list[str] = Field(default_factory=list)
    學習表現: list[LearningContentItem] = Field(default_factory=list)
    題目內容類型: str | None = None
    出題概念: str = ""


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
    # Phase 3: curriculum-aware fields
    核心素養: list[str] = Field(default_factory=list)
    學習表現: list[LearningContentItem] = Field(default_factory=list)
    題目內容類型: str | None = None
    出題概念: str = ""
    subject_filter: str | None = None
