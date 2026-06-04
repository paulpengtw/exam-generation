"""Pydantic request models for the generation API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ImageGenerationMode = Literal["html", "gpt_image"]


class GenerateParams(BaseModel):
    """Optional overrides for a generation request.

    Mirrors the CLI flags on `src.cli` `generate` subcommand. All fields are
    optional; missing fields fall back to random sampling in `sample_params()`.
    """

    subject: str = "math"
    grade: int | None = None
    style: list[str] | None = None
    context: list[str] | None = None
    set_type: str | None = Field(default=None, alias="set_type")
    q_type: list[str] | None = None
    count: int = 1
    skip_verify: bool = False
    seed: int | None = None
    max_retries: int = 3
    image_generation_mode: ImageGenerationMode = "html"
    subject_filter: list[str] | None = None
    content_type: str | None = None
    passage: str | None = None
    options: list[str] | None = None
    topic: str | None = None
    core_question: str | None = None
    learning_performance: list[str] | None = None
    core_competency: list[str] | None = None
    learning_content: list[str] | None = None

    model_config = {"populate_by_name": True}


class PlanCoreQuestionsRequest(BaseModel):
    topic: str
    subject_filter: list[str] | None = None
    grade: int | None = None
    subject: Literal["math", "social_studies"] = "social_studies"


class PlanCoreQuestionsResponse(BaseModel):
    candidates: list[str]
