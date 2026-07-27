"""Pydantic request models for the generation API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ImageGenerationMode = Literal["html", "gpt_image"]
CoverageMode = Literal["balanced", "random"]


def build_sse_error(code: str, message: str) -> dict[str, Any]:
    """Return a structured SSE error payload dict.

    Both raise sites (per-question worker and outer stream) call this helper so
    the shape is defined in exactly one place.  The payload is serialised to JSON
    by ``_serialize_event`` in routes.py (non-str data is json.dumps'd there).

    Codes in use:
    - ``generation_failed``: the per-question worker ``except Exception`` block.
    - ``stream_failed``:     the outer ``event_generator`` ``except Exception`` block.

    The *message* must never contain ``traceback.format_exc()`` output; callers
    must pass a short human-readable sentence (optionally with the exception class
    name, which is safe) and log the full traceback separately via
    ``logger.exception``.
    """
    return {"code": code, "message": message}

# Canonical set of valid subject values — derived from the SubjectSpec registry so
# there is exactly ONE declaration point.  Import is deferred to avoid a heavy
# src.* import cascade in modules that only need ALLOWED_SUBJECTS.
def _build_allowed_subjects() -> frozenset[str]:
    from server.generate.subjects import SUBJECTS  # noqa: PLC0415
    return frozenset(SUBJECTS)


ALLOWED_SUBJECTS: frozenset[str] = _build_allowed_subjects()


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
    disable_reference_fewshot: bool = False
    seed: int | None = None
    max_retries: int = 3
    image_generation_mode: ImageGenerationMode = "html"
    difficulty: Literal["easy", "medium", "hard"] | None = None
    coverage_mode: CoverageMode = "balanced"
    subject_filter: list[str] | None = None
    content_type: str | None = None
    passage: str | None = None
    options: list[str] | None = None
    topic: str | None = None
    core_question: str | None = None
    sub_context: str | None = None
    science_competency: list[str] | None = None
    learning_performance: list[str] | None = None
    core_competency: list[str] | None = None
    learning_content: list[str] | None = None
    # #100: 子題 count and word limits
    sub_question_count: int | None = Field(default=None, ge=3, le=7)
    question_word_limit: int | None = Field(default=None, ge=1)
    option_word_limit: int | None = Field(default=None, ge=1)
    text_word_limit: int | None = Field(default=None, ge=1)
    # #101: per-子題 configs as JSON string (array of {content_type, image_generation_mode, ...})
    subquestion_configs: str | None = None
    # #105: per-request model overrides (validated against ServerConfig.llm_models_allowed
    # at the route level).
    model_plan: str | None = None
    model_execute: str | None = None

    model_config = {"populate_by_name": True}


class PlanCoreQuestionsRequest(BaseModel):
    topic: str
    subject_filter: list[str] | None = None
    grade: int | None = None
    subject: Literal["math", "social_studies", "natural_sciences"] = "social_studies"
    model_plan: str | None = None
    model_execute: str | None = None


class PlanCoreQuestionsResponse(BaseModel):
    candidates: list[str]
