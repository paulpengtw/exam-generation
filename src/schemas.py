"""Pydantic data models for exam question generation."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class QuestionContext(str, Enum):
    """情境 options."""
    PERSONAL = "個人"
    SOCIAL = "社會時事"
    SCIENCE = "科學"
    CAREER = "職業"
    ARCHITECTURE_ART = "建築與藝術"
    MATH_TEXT = "數學文字情境"


class QuestionSetType(str, Enum):
    """題型種類 options."""
    SINGLE = "單一題"
    GROUP = "題組題"


class QuestionType(str, Enum):
    """題型 options."""
    MULTIPLE_CHOICE = "選擇題"
    TRUE_FALSE = "是非題"
    CLOSED_CONSTRUCTED = "封閉式建構反應題"
    OPEN_CONSTRUCTED = "開放式建構反應題"


class MathThinking(str, Enum):
    """數學思考 options."""
    FORMULATE = "形成"
    APPLY = "運用"
    INTERPRET_EVALUATE = "詮釋評估"


class QuestionStyle(str, Enum):
    """Question visual style."""
    TEXT_ONLY = "text_only"
    WITH_CHART = "with_chart"
    WITH_IMAGE = "with_image"
    CREATIVE_SCENARIO = "creative_scenario"


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
    style: QuestionStyle
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
    seed: int | None = None


class ExamQuestion(BaseModel):
    """A complete generated exam question."""
    id: str = ""
    情境: QuestionContext
    題型種類: QuestionSetType
    題型: QuestionType
    數學思考: list[MathThinking]
    學習內容: list[LearningContentItem]
    題目: list[str]
    正確解題分析: list[str]
    圖片: str | None = None
    chart_spec: ChartSpec | None = None
    verification: VerificationResult | None = None
    metadata: QuestionMetadata | None = None


class SampledParams(BaseModel):
    """Parameters selected by the sampler for question generation."""
    grade: int = Field(ge=7, le=9)
    情境: QuestionContext
    題型種類: QuestionSetType
    題型: QuestionType
    數學思考: list[MathThinking]
    學習內容: list[LearningContentItem]
    style: QuestionStyle
