"""Pydantic data models for PISA Science + 108課綱自然科學 question generation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from src.natural_sciences.schema_loader import build_enums, load_grades, load_schemas

_schemas = load_schemas()
QuestionContext, QuestionSubContext, QuestionSetType, QuestionType, ScienceCompetency = build_enums(
    _schemas
)
_GRADES: list[int] = load_grades(_schemas)


class ImageSpec(BaseModel):
    render_mode: Literal["chart", "html", "gpt_image"] = "chart"
    chart_type: (
        Literal["histogram", "boxplot", "line_chart", "pie_chart", "scatter_plot"] | None
    ) = None
    title: str = ""
    data: dict = Field(default_factory=dict)
    labels: dict = Field(default_factory=dict)
    html: str = ""
    description: str = ""
    figure_kind: str = ""

    @field_validator("data", "labels", mode="before")
    @classmethod
    def coerce_dict_fields(cls, value: object) -> object:
        """Issue #631: tolerate mistyped LLM dict fields (non-dict → {})."""
        return value if isinstance(value, dict) else {}

    @field_validator("figure_kind", "title", "description", mode="before")
    @classmethod
    def coerce_string_fields(cls, value: object) -> object:
        """Issue #631: tolerate mistyped LLM string fields (non-str → '')."""
        return value if isinstance(value, str) else ""


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


class LearningContentRef(BaseModel):
    """A 108課綱 learning content or performance standard code with description."""

    編碼: str
    說明: str = ""


class RubricEntry(BaseModel):
    """One row of a 評分規準 table."""

    code: str
    規準說明: str
    學生作答實例: list[str] = Field(default_factory=list)


class SubQuestionConfig(BaseModel):
    """Per-subquestion generation configuration overrides for natural sciences."""

    model_config = ConfigDict(extra="forbid")

    question_type: QuestionType | None = None  # type: ignore[valid-type]
    instruction: str | None = None
    content_type: str | None = None
    image_generation_mode: Literal["html", "gpt_image"] | None = None
    figure_kind: str | None = None
    question_word_limit: int | None = None
    option_word_limit: int | None = None
    reporting_scale: str | None = None
    learning_content: list[str] = Field(default_factory=list)
    learning_performance: list[str] = Field(default_factory=list)


class SubQuestion(BaseModel):
    """One subquestion within a PISA Science 題組."""

    id: str = ""
    序號: int = 1
    年級: int = 0
    科目: list[str] = Field(default_factory=list)
    科學能力: list[str] = Field(default_factory=list)
    核心素養: list[str] = Field(default_factory=list)
    學習內容: list[LearningContentRef] = Field(default_factory=list)
    學習表現: list[LearningContentRef] = Field(default_factory=list)
    出題概念: str = ""
    出題指示: str | None = None
    reporting_scale: str | None = None
    題型: QuestionType  # type: ignore[valid-type]
    題目: str
    答案: str = ""
    答案解析: str = ""
    評分規準: list[RubricEntry] = Field(default_factory=list)
    誘答分析: dict[str, str] = Field(default_factory=dict)
    題目內容類型: str | None = None
    image_generation_mode: Literal["html", "gpt_image"] | None = None
    圖片: str | None = None
    chart_spec: ChartSpec | None = None

    # 建構這一小題時所用的 各小題配置 索引（PLAN 索引，1 起算，不進 JSON）。
    # `序號` 是模型自報的，可能錯位或重複；下游圖片渲染必須沿用同一格配置。
    _plan_index: int | None = PrivateAttr(default=None)


class QuestionMetadata(BaseModel):
    """Metadata recorded once when the 題組 is finalised.

    ``reporting_scales`` lists the resolved Reporting Scale for each
    surviving 小題 in 序號 order — one entry per shipped 小題, no entry for
    slots that were dropped after exhausting retries.  The list is frozen
    through any subsequent correction passes.
    """

    model_config = ConfigDict(extra="ignore")

    grade: int
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
    seed: int | None = None
    reporting_scales: list[str] = Field(default_factory=list)
    coverage_mode_used: Literal["balanced", "random"] | None = None


class ExamQuestion(BaseModel):
    """A complete PISA Science + 108課綱自然科學 exam question set."""

    id: str = ""
    核心問題: str = ""
    文本: str = ""
    取材來源: list[str] = Field(default_factory=list)
    subquestions: list[SubQuestion] = Field(default_factory=list)

    情境: list[QuestionContext]  # type: ignore[valid-type]
    情境子類別: QuestionSubContext | None = None  # type: ignore[valid-type]
    題型種類: QuestionSetType  # type: ignore[valid-type]
    題型: QuestionType  # type: ignore[valid-type]
    科學能力: list[ScienceCompetency] = Field(default_factory=list)  # type: ignore[valid-type]
    題目內容類型: str | None = None

    題目: list[str] = Field(default_factory=list)
    正確解題分析: list[str] = Field(default_factory=list)

    圖片: str | None = None
    chart_spec: ChartSpec | None = None
    verification: VerificationResult | None = None
    metadata: QuestionMetadata | None = None

    # One shared missing-spec/declaration repair budget per visual slot;
    # collision repairs remain one targeted call per detected collision under
    # ADR 0015. Private so it is not persisted in the generated question JSON.
    _figure_kind_repair_attempted: set[str] = PrivateAttr(default_factory=set)


class SampledParams(BaseModel):
    """Parameters selected by the sampler for natural-sciences generation."""

    grade: int
    seed: int | None = None

    @field_validator("grade")
    @classmethod
    def grade_must_be_allowed(cls, v: int) -> int:
        if v not in _GRADES:
            raise ValueError(f"grade must be one of {_GRADES}, got {v}")
        return v

    情境: list[QuestionContext]  # type: ignore[valid-type]
    情境子類別: QuestionSubContext  # type: ignore[valid-type]
    題型種類: QuestionSetType  # type: ignore[valid-type]
    題型: QuestionType  # type: ignore[valid-type]
    科學能力: list[ScienceCompetency] = Field(default_factory=list)  # type: ignore[valid-type]
    題目內容類型: str = ""
    學習內容_pool: list[str] = Field(default_factory=list)
    學習表現_pool: list[str] = Field(default_factory=list)
    sub_question_count: int | None = None
    question_word_limit: int | None = None
    option_word_limit: int | None = None
    text_word_limit: int | None = None
    subquestion_configs: list[SubQuestionConfig] = Field(default_factory=list)
    # Issue #280: 題組-level Reporting Scale (None → not specified; never randomised here).
    reporting_scale: str | None = None
    # Request-level kill switch shared by all subjects' figure policy.
    allow_duplicate_figure_kinds: bool = False
