"""Pydantic request models for the generation API."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
REQUEST_LEVEL_FIELDS: frozenset[str] = frozenset(
    {
        "subject",
        "count",
        "per_question_params",
        "predrawn_fields",
        "max_retries",
        "allow_duplicate_figure_kinds",
        "core_question_callback",
    }
)
# Backend-only request fields are valid on the API route but intentionally have
# no web form control or generated client forwarding.
SERVER_ONLY_GENERATE_FIELDS: frozenset[str] = frozenset(
    {"allow_duplicate_figure_kinds"}
)


def decode_per_question_params(raw: str | None) -> list[dict[str, Any]] | None:
    """Decode the strictly validated per-question parameter array."""
    if raw is None:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("per_question_params must be valid JSON") from exc
    if not isinstance(decoded, list):
        raise ValueError("per_question_params must be a JSON array")
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise ValueError(f"per_question_params[{index}] must be an object")
    return decoded


def decode_predrawn_fields(raw: str | None) -> list[str] | None:
    """Decode the optional client-side pre-draw provenance list."""
    if raw is None:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("predrawn_fields must be valid JSON") from exc
    if not isinstance(decoded, list):
        raise ValueError("predrawn_fields must be a JSON array")
    for index, item in enumerate(decoded):
        if not isinstance(item, str):
            raise ValueError(f"predrawn_fields[{index}] must be a string")
    return decoded


class SubQuestionConfig(BaseModel):
    """Wire shape for a per-小題 config used by social studies.

    The server accepts the config array as JSON so that subject adapters can
    own the complete config schema.  Keeping extra fields here preserves that
    existing boundary while making the SS figure-kind pin an explicit server
    model field.
    """

    figure_kind: str | None = None

    model_config = ConfigDict(extra="allow")


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
    count: int = Field(default=1, ge=1, le=10)
    skip_verify: bool = False
    disable_reference_fewshot: bool = False
    seed: int | None = None
    max_retries: int = 3
    image_generation_mode: ImageGenerationMode = "html"
    difficulty: Literal["easy", "medium", "hard"] | None = None
    coverage_mode: CoverageMode = "balanced"
    core_question_callback: bool = True
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
    # SS-only request-level kill-switch; intentionally not exposed by the web UI.
    allow_duplicate_figure_kinds: bool = False
    per_question_params: str | None = None
    # #408: client-side pre-draw provenance; inert to sampling and generation.
    predrawn_fields: str | None = None
    # #105: per-request model overrides (validated against ServerConfig.llm_models_allowed
    # at the route level).
    model_plan: str | None = None
    model_execute: str | None = None
    # #375: per-request tier model overrides; resolution order is
    # request param → env var (config.model_verify/correct) → effective execute model.
    model_verify: str | None = None
    model_correct: str | None = None
    # #254: per-request effort tier overrides (validated against per-model roster
    # at the route level; basic format validated here).
    effort_plan: str | None = None
    effort_execute: str | None = None
    # #377: per-request tier effort overrides; resolution order is
    # request param → env var (config.effort_verify/correct) → effective execute effort.
    effort_verify: str | None = None
    effort_correct: str | None = None
    # #279: 題組-level Reporting Scale (natural_sciences only; other subjects accept and ignore).
    reporting_scale: str | None = None

    @field_validator(
        "set_type",
        "sub_context",
        "style",
        "q_type",
        "context",
        "subject_filter",
        "science_competency",
        "reporting_scale",
        mode="before",
    )
    @classmethod
    def enum_values_must_not_be_empty(cls, value: object) -> object:
        values = value if isinstance(value, list) else [value]
        if any(item == "" for item in values):
            raise ValueError("must not contain an empty value")
        return value

    @field_validator("per_question_params")
    @classmethod
    def per_question_params_must_be_well_formed(cls, value: str | None) -> str | None:
        decode_per_question_params(value)
        return value

    @field_validator("predrawn_fields")
    @classmethod
    def predrawn_fields_must_be_well_formed(cls, value: str | None) -> str | None:
        decode_predrawn_fields(value)
        return value

    @field_validator("effort_plan", "effort_execute", "effort_verify", "effort_correct")
    @classmethod
    def effort_level_must_be_valid(cls, value: str | None) -> str | None:
        _VALID_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}
        if value is not None and value not in _VALID_EFFORT_LEVELS:
            raise ValueError(
                f"must be one of {sorted(_VALID_EFFORT_LEVELS)}, got '{value}'"
            )
        return value

    @model_validator(mode="after")
    def context_must_match_sub_context(self) -> GenerateParams:
        from server.generate.subjects import SUBJECTS  # noqa: PLC0415

        spec = SUBJECTS.get(self.subject)
        if spec is not None and spec.validate_params is not None:
            spec.validate_params(self)
        decoded = decode_per_question_params(self.per_question_params)
        if decoded is not None and len(decoded) != self.count:
            raise ValueError(
                f"per_question_params array length {len(decoded)} must equal count {self.count}"
            )
        if decoded is not None:
            base = self.model_dump()
            base["per_question_params"] = None
            for index, item in enumerate(decoded):
                unknown = set(item) - PER_QUESTION_FIELDS
                if unknown:
                    names = ", ".join(sorted(unknown))
                    raise ValueError(
                        f"per_question_params[{index}] has unknown parameter(s): {names}"
                    )
                try:
                    type(self).model_validate({**base, **item})
                except ValueError as exc:
                    raise ValueError(
                        f"per_question_params[{index}] is invalid: {exc}"
                    ) from exc
        return self

    model_config = {"populate_by_name": True}


# Explicit allowlist of GenerateParams fields that may be overridden on a
# per-question basis via per_question_params[i].  Any new field added to
# GenerateParams MUST be deliberately classified here or in REQUEST_LEVEL_FIELDS
# above; the partition test in tests/server/test_per_question_params.py enforces
# this so that a new field cannot silently become per-question-allowed.
PER_QUESTION_FIELDS: frozenset[str] = frozenset(
    {
        "grade",
        "style",
        "context",
        "set_type",
        "q_type",
        "skip_verify",
        "disable_reference_fewshot",
        "seed",
        "image_generation_mode",
        "difficulty",
        "coverage_mode",
        "subject_filter",
        "content_type",
        "passage",
        "options",
        "topic",
        "core_question",
        "sub_context",
        "science_competency",
        "learning_performance",
        "core_competency",
        "learning_content",
        "sub_question_count",
        "question_word_limit",
        "option_word_limit",
        "text_word_limit",
        "subquestion_configs",
        "model_plan",
        "model_execute",
        "model_verify",   # #375: per-request tier model override
        "model_correct",  # #375: per-request tier model override
        "effort_plan",
        "effort_execute",
        "effort_verify",   # #377: per-request tier effort override
        "effort_correct",  # #377: per-request tier effort override
        "reporting_scale",
    }
)


_VALID_EFFORT_LEVELS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})


class PlanCoreQuestionsRequest(BaseModel):
    topic: str
    subject_filter: list[str] | None = None
    grade: int | None = None
    subject: Literal["math", "social_studies", "natural_sciences"] = "social_studies"
    model_plan: str | None = None
    model_execute: str | None = None
    effort_plan: str | None = None

    @field_validator("effort_plan")
    @classmethod
    def effort_plan_must_be_valid(cls, value: str | None) -> str | None:
        if value is not None and value not in _VALID_EFFORT_LEVELS:
            raise ValueError(
                f"effort_plan must be one of {sorted(_VALID_EFFORT_LEVELS)}, got '{value}'"
            )
        return value


class PlanCoreQuestionsResponse(BaseModel):
    candidates: list[str]
