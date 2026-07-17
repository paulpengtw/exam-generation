"""Pydantic data models for social studies (108課綱 社會領域素養導向) question generation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.social_studies.core_competency_loader import build_core_competency_enum, load_core_competencies
from src.social_studies.schema_loader import build_enums, load_grades, load_schemas

_schemas = load_schemas()
QuestionContext, QuestionSetType, QuestionType, ReadingProcess, TextForm, QuestionSubject = build_enums(_schemas)
CoreCompetency = build_core_competency_enum(load_core_competencies())
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


class LearningContentRef(BaseModel):
    """A 108課綱 learning content or performance standard code with description."""
    編碼: str
    說明: str = ""


class RubricEntry(BaseModel):
    """One row of a 評分規準 table (scoring rubric).

    Codes follow ODT convention: 2=滿分, 1=部分得分, 0=零分, 0X=未作答.
    """
    code: str  # "2" | "1" | "0" | "0X"
    規準說明: str
    學生作答實例: list[str] = Field(default_factory=list)


class SubQuestionConfig(BaseModel):
    """Per-subquestion generation configuration overrides (issues #100 and #101)."""
    question_type: QuestionType | None = None  # type: ignore[valid-type]
    instruction: str | None = None
    content_type: str | None = None
    image_generation_mode: Literal["html", "gpt_image"] | None = None
    question_word_limit: int | None = None
    option_word_limit: int | None = None
    text_word_limit: int | None = None
    learning_content: list[str] = Field(default_factory=list)
    learning_performance: list[str] = Field(default_factory=list)


class SubQuestion(BaseModel):
    """One subquestion within a 題組, tagged with 108課綱 curriculum metadata."""
    id: str = ""
    序號: int = 1
    年級: int = 0
    科目: list[str] = Field(default_factory=list)   # 歷史 / 地理 / 公民與社會
    核心素養: list[str] = Field(default_factory=list)  # e.g. ["社-J-A2"]
    學習內容: list[LearningContentRef] = Field(default_factory=list)
    學習表現: list[LearningContentRef] = Field(default_factory=list)
    出題概念: str = ""
    出題指示: str | None = None
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


class QuestionMetadata(BaseModel):
    grade: int
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
    seed: int | None = None


class ExamQuestion(BaseModel):
    """A complete 108課綱 社會領域素養導向 exam question set (題組)."""
    id: str = ""

    # 108課綱 top-level 題組 fields
    核心問題: str = ""
    文本: str = ""
    取材來源: list[str] = Field(default_factory=list)
    subquestions: list[SubQuestion] = Field(default_factory=list)

    # PISA framing tags (kept for compatibility and question diversity)
    情境: list[QuestionContext]  # type: ignore[valid-type]
    題型種類: QuestionSetType  # type: ignore[valid-type]
    題型: QuestionType  # type: ignore[valid-type]
    閱讀歷程: list[ReadingProcess]  # type: ignore[valid-type]
    文本形式: TextForm  # type: ignore[valid-type]
    題目內容類型: str | None = None

    # Legacy flat arrays retained for backward compatibility with verifier / corrector
    題目: list[str] = Field(default_factory=list)
    正確解題分析: list[str] = Field(default_factory=list)

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
    題型: list[QuestionType]  # allowed pool of types; each 子題 picks its own  # type: ignore[valid-type]
    閱讀歷程: list[ReadingProcess]  # type: ignore[valid-type]
    文本形式: TextForm  # type: ignore[valid-type]
    題目內容類型: str = ""  # top-level 文本素材類型 (renamed in UI for #101)
    科目: QuestionSubject  # type: ignore[valid-type]
    核心素養: list[CoreCompetency] = Field(default_factory=list)  # type: ignore[valid-type]
    學習內容_pool: list[str] = Field(default_factory=list)  # sampler-picked 編碼 codes (1-3)
    學習表現_pool: list[str] = Field(default_factory=list)  # sampler-picked 編碼 codes (1-2)
    # #100: 子題 count and word limits
    sub_question_count: int | None = None
    question_word_limit: int | None = None
    option_word_limit: int | None = None
    text_word_limit: int | None = None
    # #101: per-子題 content_type and image_generation_mode
    subquestion_configs: list[SubQuestionConfig] = Field(default_factory=list)
