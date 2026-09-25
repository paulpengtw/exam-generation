"""Pydantic data models for exam question generation."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr, field_validator

from src.common.core_competency_loader import (
    build_core_competency_enum,
    load_core_competencies,
)
from src.common.difficulty import DEFAULT_DIFFICULTY, Difficulty
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


class SubQuestion(BaseModel):
    """One 小題 within an opt-in math 題組."""

    id: str = ""
    序號: int = 1
    年級: int = 0
    題型: QuestionType  # type: ignore[valid-type]
    題目: str
    答案: str = ""
    答案解析: str = ""
    誘答分析: dict[str, str] = Field(default_factory=dict)
    學習內容: list[LearningContentItem] = Field(default_factory=list)
    學習表現: list[LearningContentItem] = Field(default_factory=list)
    出題概念: str = ""

    # One-based program slot used by grouped math's shared core.  It is
    # intentionally private so transport/history JSON keeps the legacy shape.
    _plan_index: int | None = PrivateAttr(default=None)


class ImageSpec(BaseModel):
    """Specification for generating a question image.

    Three render modes (see docs/figure-rendering-policy.md):
    - render_mode="chart": structured data rendered by matplotlib (histogram, boxplot, etc.)
    - render_mode="html": LLM generates HTML/CSS/SVG, rendered to PNG via Playwright
    - render_mode="gpt_image": OpenAI image API renders the spec directly (realistic diagrams)
    """
    render_mode: Literal["chart", "html", "gpt_image"] = "chart"
    # chart mode fields
    chart_type: Literal["histogram", "boxplot", "line_chart", "pie_chart"] | None = None
    title: str = ""
    data: dict = Field(default_factory=dict)
    labels: dict = Field(default_factory=dict)
    # html mode fields
    html: str = ""
    description: str = ""

    @field_validator("data", "labels", mode="before")
    @classmethod
    def coerce_dict_fields(cls, value: object) -> object:
        """Issue #632: tolerate mistyped LLM dict fields (non-dict → {})."""
        return value if isinstance(value, dict) else {}

    @field_validator("title", "description", mode="before")
    @classmethod
    def coerce_string_fields(cls, value: object) -> object:
        """Issue #632: tolerate mistyped LLM string fields (non-str → '')."""
        return value if isinstance(value, str) else ""


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
    difficulty: Difficulty = DEFAULT_DIFFICULTY


class ExamQuestion(BaseModel):
    """A complete generated exam question."""
    id: str = ""
    文本: str = Field(default="", exclude_if=lambda value: value == "")
    核心問題: str = Field(default="", exclude_if=lambda value: value == "")
    取材來源: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    subquestions: list[SubQuestion] = Field(
        default_factory=list,
        exclude_if=lambda value: not value,
    )
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
    誘答分析: dict[str, str] = Field(default_factory=dict)


class SampledParams(BaseModel):
    """Parameters selected by the sampler for question generation."""
    grade: int
    seed: int | None = None

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
    sub_question_count: int | None = None
    text_word_limit: int | None = None
    # Issue #116: explicit difficulty (pure passthrough — never randomized).
    difficulty: Difficulty = DEFAULT_DIFFICULTY
