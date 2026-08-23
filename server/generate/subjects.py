"""SubjectSpec registry — single declaration point for all per-subject dispatch.

This module is the ONLY place in server/ where subject strings appear as keys.
Every dispatch site in service.py, routes.py, and utility/routes.py must resolve
behaviour through SUBJECTS[subject_key] rather than if/elif chains.

Adapters for do_generate / do_sample_params use a lazy import of
``server.generate.service`` at call time so that test monkeypatches applied to
module-level names in service.py (e.g. ``service.ss_generate_with_corrections``)
are still intercepted correctly.  The lazy import resolves at first call, after
all modules are fully loaded, so there is no circular-import issue at load time.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Callable

from src.cli import build_generation_prompts as _math_build_prompts_impl
from src.cli import generate_with_corrections as _math_generate_with_corrections
from src.common.batch_dedup import (
    extract_math_prior_scope,
    extract_ns_prior_scope,
    extract_ss_prior_scope,
)
from src.common.curriculum_loader import (
    load_learning_content as load_common_lc,
)
from src.common.curriculum_loader import load_learning_performance as load_common_lp
from src.corrector import correct_question as _math_correct_question
from src.natural_sciences.cli import (
    build_generation_prompts as _ns_build_prompts_impl,
)
from src.natural_sciences.cli import (
    build_subquestion_prompt_previews as _ns_build_sub_prompts_impl,
)
from src.natural_sciences.cli import (
    generate_with_corrections as _ns_generate_with_corrections,
)
from src.natural_sciences.corrector import correct_question as _ns_correct_question
from src.natural_sciences.curriculum_loader import (
    load_learning_content as load_ns_learning_content,
)
from src.natural_sciences.curriculum_loader import (
    load_learning_performance as load_ns_learning_performance,
)
from src.natural_sciences.sampler import sample_params as _ns_sample_params
from src.natural_sciences.schema_loader import (
    load_learning_stage as ns_load_learning_stage,
)
from src.natural_sciences.schema_loader import (
    load_schemas as ns_load_schemas,
)
from src.natural_sciences.schemas import (
    ExamQuestion as NSExamQuestion,
)
from src.natural_sciences.schemas import (
    QuestionContext as NSQuestionContext,
)
from src.natural_sciences.schemas import (
    QuestionSetType as NSQuestionSetType,
)
from src.natural_sciences.schemas import (
    QuestionSubContext as NSQuestionSubContext,
)
from src.natural_sciences.schemas import (
    QuestionType as NSQuestionType,
)
from src.natural_sciences.schemas import (
    ScienceCompetency as NSScienceCompetency,
)
from src.natural_sciences.verifier import verify_question as _ns_verify_question
from src.sampler import grade_to_learning_stage
from src.sampler import sample_params as _math_sample_params
from src.schemas import (
    ExamQuestion as MathExamQuestion,
)
from src.schemas import (
    QuestionContext as MathQuestionContext,
)
from src.schemas import (
    QuestionSetType as MathQuestionSetType,
)
from src.schemas import (
    QuestionStyle as MathQuestionStyle,
)
from src.schemas import (
    QuestionType as MathQuestionType,
)
from src.social_studies.cli import _plan_batch_briefs as _ss_plan_batch_briefs
from src.social_studies.cli import (
    build_generation_prompts as _ss_build_prompts_impl,
)
from src.social_studies.cli import (
    build_subquestion_prompt_previews as _ss_build_sub_prompts_impl,
)
from src.social_studies.cli import (
    generate_with_corrections as _ss_generate_with_corrections,
)
from src.social_studies.corrector import correct_question as _ss_correct_question
from src.social_studies.curriculum_loader import (
    load_learning_content as load_ss_learning_content,
)
from src.social_studies.curriculum_loader import (
    load_learning_performance as load_ss_learning_performance,
)
from src.social_studies.sampler import sample_params as _ss_sample_params_direct
from src.social_studies.schema_loader import (
    load_learning_stage as ss_load_learning_stage,
)
from src.social_studies.schema_loader import (
    load_schemas as ss_load_schemas,
)
from src.social_studies.schemas import (
    CoreCompetency as SSCoreCompetency,
)
from src.social_studies.schemas import (
    ExamQuestion as SSExamQuestion,
)
from src.social_studies.schemas import (
    QuestionContext as SSQuestionContext,
)
from src.social_studies.schemas import (
    QuestionSetType as SSQuestionSetType,
)
from src.social_studies.schemas import (
    QuestionSubject as SSQuestionSubject,
)
from src.social_studies.schemas import (
    QuestionType as SSQuestionType,
)
from src.social_studies.verifier import verify_question as _ss_verify_question
from src.verifier import verify_question as _math_verify_question

# ── utility used by coerce_overrides ─────────────────────────────────────────

def _resolve_enum(value: str | None, enum_cls: type) -> Any:
    if value is None:
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    raise ValueError(f"Invalid value '{value}' for {enum_cls.__name__}")


# ─────────────────────────────────────────────────────────────────────────────
# SubjectSpec dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class SubjectSpec:
    """Encapsulates all per-subject dispatch logic.

    Fields
    ------
    key                     Subject string key, e.g. ``"social_studies"``.
    question_id_prefix      Prefix for generated question IDs (``"ss_"`` etc.).
    exam_question_cls       The ExamQuestion class for this subject.
    coerce_overrides        ``(params, app_state) -> dict`` of coerced enum values
                            and subject-specific state drawn from app_state.
    plan_all_batch_briefs   ``(params, count, base_seed, overrides, config,
                            creative_planning, decoded_subquestion_configs)
                            -> list[brief|None]``
                            Returns a list of creative briefs for each question
                            index (None means no brief).  Returns ``[]`` for
                            subjects that don't support creative planning so
                            ``i < len([])`` is always False.
    do_sample_params        ``(params, overrides, *, seed,
                            subquestion_configs_decoded)
                            -> SampledParams``
    do_generate             ``(rng_params, overrides, **common_kwargs)
                            -> ExamQuestion``
                            Adapters use a lazy import of service.py so that
                            test monkeypatches are intercepted.
    build_generation_prompts
                            ``(rng_params, overrides, **common_kwargs)
                            -> (system_prompt, user_prompt, image_paths)``
                            Builds the same first-call prompts as do_generate.
    extract_prior_scope     ``(question) -> PriorScope | None``
    patch_metadata          Optional ``(question, coverage_mode) -> question``
                            for SS metadata patching.
    plan_core_questions     ``(client, topic, **kwargs) -> list[str]``
                            Used by the planner route.
    load_planner_stage      ``(config_server, grade) -> str``
                            Returns the learning-stage string for the planner.
    build_schemas           ``(config_server, grade) -> dict``
                            Returns the schemas dict for /api/schemas.
    validate_params         Optional ``(params) -> None`` request validation
                            hook for subject-specific parameter relationships.
    correct_question        Shared corrector entry point used by manual
                            modification runs.
    verify_question         Shared verifier entry point used by manual
                            modification runs.
    """

    key: str
    question_id_prefix: str
    exam_question_cls: type

    coerce_overrides: Callable
    plan_all_batch_briefs: Callable
    do_sample_params: Callable
    do_generate: Callable
    extract_prior_scope: Callable

    patch_metadata: Callable | None

    plan_core_questions: Callable
    load_planner_stage: Callable
    build_schemas: Callable
    build_generation_prompts: Callable | None = None
    build_subquestion_prompt_previews: Callable | None = None
    validate_params: Callable | None = None
    correct_question: Callable | None = None
    verify_question: Callable | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Schema-building helpers shared by build_schemas callables
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_stage(schemas: dict, grade: int | None) -> str:
    if grade is not None:
        try:
            return grade_to_learning_stage(grade)
        except ValueError:
            pass
    return schemas.get("學習階段", "")


def _ns_validate_params(params: Any) -> None:
    if params.core_competency:
        raise ValueError(
            "core_competency is not supported for natural sciences; "
            "use science_competency instead"
        )

    if params.reporting_scale is not None:
        from src.natural_sciences.reporting_scale import REPORTING_SCALE_ORDER  # noqa: PLC0415

        if params.reporting_scale not in REPORTING_SCALE_ORDER:
            raise ValueError(
                f"reporting_scale {params.reporting_scale!r} is not a valid level; "
                f"allowed values: {REPORTING_SCALE_ORDER}"
            )

    if params.context is None or params.sub_context is None:
        return

    from src.natural_sciences.schema_loader import load_schemas  # noqa: PLC0415

    parents = {
        row["value"]: row.get("parent")
        for row in load_schemas().get("情境子類別", [])
    }
    if parents.get(params.sub_context) not in params.context:
        raise ValueError(
            "context and sub_context are incompatible: "
            f"sub_context {params.sub_context!r} requires "
            f"context {parents.get(params.sub_context)!r}"
        )


def _math_validate_params(params: Any) -> None:
    if params.sub_question_count is not None and params.set_type == "單一題":
        raise ValueError(
            "sub_question_count implies 題型種類=題組題, but explicit "
            "題型種類=單一題 was supplied"
        )

    if params.text_word_limit is not None and params.passage and params.passage.strip():
        raise ValueError(
            "text_word_limit cannot be used with passage for math: "
            "passage is user-authored 文本"
        )

    unsupported = [
        field
        for field in (
            "question_word_limit",
            "option_word_limit",
            "subquestion_configs",
        )
        if getattr(params, field) is not None
    ]
    # disable_reference_fewshot is deliberately excluded: its bool=False default
    # makes omission indistinguishable from an explicit false; making it optional
    # would be an out-of-scope wire change.
    if unsupported:
        raise ValueError(
            "The following parameters are not supported for math: "
            + ", ".join(unsupported)
        )


_MATH_SUBJECTS = [
    {
        "value": "數與量",
        "instruction": (
            "題目主要涵蓋108課綱數學領域「數與量」主題（編碼前綴 N/n），"
            "含整數、有理數、實數、估算、單位換算等。"
        ),
    },
    {
        "value": "代數",
        "instruction": (
            "題目主要涵蓋108課綱數學領域「代數」主題（編碼前綴 R/A/F），"
            "含關係、方程式、函數、不等式等。"
        ),
    },
    {
        "value": "幾何",
        "instruction": (
            "題目主要涵蓋108課綱數學領域「幾何」主題（編碼前綴 S/G），"
            "含平面與立體幾何、座標、變換等。"
        ),
    },
    {
        "value": "統計與機率",
        "instruction": (
            "題目主要涵蓋108課綱數學領域「統計與機率」主題（編碼前綴 D/P），"
            "含資料整理、敘述統計、機率初步等。"
        ),
    },
]

_MATH_CONTENT_TYPES = [
    {
        "value": "純文字",
        "instruction": (
            "純文字題目，不需任何圖表或圖片。題目僅透過文字描述情境與數學問題，"
            "不得輸出 chart_spec。"
        ),
    },
    {
        "value": "含圖片",
        "instruction": (
            "題目必須搭配圖片式或視覺式素材，如幾何圖形、示意圖、座標平面、數線等，"
            "並以 chart_spec 描述素材。"
        ),
    },
    {
        "value": "graphs/charts/tables",
        "instruction": (
            "題目必須搭配圖表或表格素材，如統計圖、折線圖、圓餅圖、比較表或資料表，"
            "並以 chart_spec 提供完整資料。"
        ),
    },
    {
        "value": "customized",
        "instruction": (
            "由使用者自行輸入題目內容類型；送出時以前端輸入文字作為實際內容類型。"
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Social-studies (SS) adapters
# ─────────────────────────────────────────────────────────────────────────────

def _ss_coerce_overrides(params: Any, app_state: Any) -> dict:
    context_override = (
        [_resolve_enum(v, SSQuestionContext) for v in params.context]
        if params.context else None
    )
    set_type_override = _resolve_enum(params.set_type, SSQuestionSetType)
    q_type_override = (
        [_resolve_enum(v, SSQuestionType) for v in params.q_type]
        if params.q_type else None
    )
    subject_override = (
        [SSQuestionSubject(v) for v in params.subject_filter]
        if params.subject_filter else None
    )
    core_competency_override = (
        [SSCoreCompetency(v) for v in params.core_competency]
        if params.core_competency else None
    )
    ss_curriculum_context = getattr(app_state, "ss_curriculum_context", None)
    return {
        "context_override": context_override,
        "set_type_override": set_type_override,
        "q_type_override": q_type_override,
        "subject_override": subject_override,
        "core_competency_override": core_competency_override,
        "ss_curriculum_context": ss_curriculum_context,
    }


def _ss_plan_all_batch_briefs(
    params: Any,
    count: int,
    base_seed: int | None,
    overrides: dict,
    config: Any,
    creative_planning: bool,
    decoded_subquestion_configs: list[dict] | None,
    **kwargs: Any,
) -> list:
    if count < 1:
        return []
    if not creative_planning:
        return [None] * count

    from src.llm_client import LLMClient as _LLMClient

    client_factory = kwargs.get("client_factory") or _LLMClient

    context_override = overrides["context_override"]
    set_type_override = overrides["set_type_override"]
    q_type_override = overrides["q_type_override"]
    subject_override = overrides["subject_override"]

    pre_params_list = []
    for i in range(count):
        seed = (base_seed + i) if base_seed is not None else None
        pre_params_list.append(
            _ss_sample_params_direct(
                grade=params.grade,
                context=context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                subject=subject_override,
                content_type=params.content_type,
                learning_performance=params.learning_performance,
                seed=seed,
                sub_question_count=params.sub_question_count,
                question_word_limit=params.question_word_limit,
                option_word_limit=params.option_word_limit,
                subquestion_configs=decoded_subquestion_configs,
                allow_duplicate_figure_kinds=params.allow_duplicate_figure_kinds,
            ),
        )
    planning_client = client_factory(config)
    return _ss_plan_batch_briefs(planning_client, config, pre_params_list)


def _ss_do_sample_params(
    params: Any,
    overrides: dict,
    *,
    seed: int | None,
    subquestion_configs_decoded: list[dict] | None,
) -> Any:
    return _ss_sample_params_direct(
        grade=params.grade,
        context=overrides["context_override"],
        set_type=overrides["set_type_override"],
        q_type=overrides["q_type_override"],
        subject=overrides["subject_override"],
        core_competency=overrides["core_competency_override"],
        content_type=params.content_type,
        learning_content=params.learning_content,
        learning_performance=params.learning_performance,
        seed=seed,
        sub_question_count=params.sub_question_count,
        question_word_limit=params.question_word_limit,
        option_word_limit=params.option_word_limit,
        subquestion_configs=subquestion_configs_decoded,
        difficulty=params.difficulty,
        allow_duplicate_figure_kinds=params.allow_duplicate_figure_kinds,
    )


def _ss_do_generate(rng_params: Any, overrides: dict, **kwargs: Any) -> Any:
    return _ss_generate_with_corrections(
        config=kwargs["config"],
        client=kwargs["client"],
        params=rng_params,
        question_id=kwargs["question_id"],
        max_retries=kwargs["max_retries"],
        skip_verify=kwargs["skip_verify"],
        disable_reference_fewshot=kwargs["disable_reference_fewshot"],
        html_renderer=kwargs["html_renderer"],
        image_generation_mode=kwargs["image_generation_mode"],
        user_passage=kwargs["user_passage"],
        text_word_limit=kwargs["text_word_limit"],
        user_options=kwargs["user_options"],
        user_topic=kwargs["user_topic"],
        user_core_question=kwargs["user_core_question"],
        core_question_callback=kwargs.get("core_question_callback", True),
        on_question_update=kwargs["on_question_update"],
        prior_scopes=kwargs["prior_scopes"],
        curriculum_context=overrides["ss_curriculum_context"],
        balanced_batch=kwargs["balanced_batch"],
    )


def _ss_build_generation_prompts(
    rng_params: Any, overrides: dict, **kwargs: Any
) -> tuple[str, str, list]:
    return _ss_build_prompts_impl(
        kwargs["config"],
        rng_params,
        disable_reference_fewshot=kwargs["disable_reference_fewshot"],
        image_generation_mode=kwargs["image_generation_mode"],
        user_passage=kwargs["user_passage"],
        text_word_limit=kwargs["text_word_limit"],
        user_options=kwargs["user_options"],
        user_topic=kwargs["user_topic"],
        user_core_question=kwargs["user_core_question"],
        prior_scopes=kwargs["prior_scopes"],
        core_question_callback=kwargs.get("core_question_callback", True),
        balanced_batch=kwargs["balanced_batch"],
    )


def _ss_build_subquestion_prompt_previews(
    rng_params: Any, overrides: dict, **kwargs: Any
) -> list[tuple[int, str, str, list]]:
    return _ss_build_sub_prompts_impl(
        kwargs["config"],
        rng_params,
        disable_reference_fewshot=kwargs["disable_reference_fewshot"],
        image_generation_mode=kwargs["image_generation_mode"],
        user_passage=kwargs["user_passage"],
        user_options=kwargs["user_options"],
        user_topic=kwargs["user_topic"],
        user_core_question=kwargs["user_core_question"],
        prior_scopes=kwargs["prior_scopes"],
        core_question_callback=kwargs.get("core_question_callback", True),
    )


def _ss_patch_metadata(question: Any, coverage_mode: str) -> Any:
    from src.social_studies.schemas import ExamQuestion as _SSExamQuestion  # noqa: PLC0415
    from src.social_studies.schemas import QuestionMetadata as _QM  # noqa: PLC0415

    if not isinstance(question, _SSExamQuestion):
        return question
    if question.metadata is None:
        # Fall back to a minimal metadata object; model attribute may not be
        # available on all config types, so use "unknown" as sentinel.
        question.metadata = _QM(
            grade=question.subquestions[0].年級 if question.subquestions else 0,
            model="unknown",
            coverage_mode_used=coverage_mode,
        )
    else:
        question.metadata = question.metadata.model_copy(
            update={"coverage_mode_used": coverage_mode}
        )
    return question


def _ss_plan_core_questions(client: Any, topic: str, **kwargs: Any) -> list[str]:
    # Lazy import so test monkeypatches on src.social_studies.planner.plan_core_questions are seen.
    import src.social_studies.planner as _m  # noqa: PLC0415
    return _m.plan_core_questions(client, topic, **kwargs)


def _ss_load_planner_stage(config_server: Any, grade: int | None) -> str:
    schemas = ss_load_schemas()
    return ss_load_learning_stage(schemas)


def _ss_build_schemas(config_server: Any, grade: int | None) -> dict:
    schemas = ss_load_schemas(config_server.social_studies_curriculum_dir)
    performance_data = load_ss_learning_performance(
        config_server.social_studies_curriculum_dir / "learning_performance.json"
    )
    learning_stage = _resolve_stage(schemas, grade)
    schemas["學習表現"] = [
        {
            "value": entry["value"],
            "instruction": entry.get("說明", ""),
            "科目": entry.get("科目", ""),
        }
        for entry in performance_data.get("學習表現", [])
        if entry.get("學習階段") == learning_stage
    ]
    content = load_ss_learning_content(
        config_server.social_studies_curriculum_dir / "learning_content.json"
    )
    schemas["學習內容"] = [
        {
            "value": entry["value"],
            "instruction": entry.get("條目說明", ""),
            "科目": entry.get("科目", ""),
        }
        for entry in content.get("學習內容", [])
        if entry.get("學習階段") == learning_stage
    ]
    return schemas


# ─────────────────────────────────────────────────────────────────────────────
# Natural-sciences (NS) adapters
# ─────────────────────────────────────────────────────────────────────────────

def _ns_coerce_overrides(params: Any, app_state: Any) -> dict:
    context_override = (
        [_resolve_enum(v, NSQuestionContext) for v in params.context]
        if params.context else None
    )
    sub_context_override = _resolve_enum(params.sub_context, NSQuestionSubContext)
    set_type_override = _resolve_enum(params.set_type, NSQuestionSetType)
    q_type_override = (
        [_resolve_enum(v, NSQuestionType) for v in params.q_type]
        if params.q_type else None
    )
    science_competency_override = (
        [_resolve_enum(v, NSScienceCompetency) for v in params.science_competency]
        if params.science_competency else None
    )
    ns_curriculum_context = getattr(app_state, "ns_curriculum_context", None)
    return {
        "context_override": context_override,
        "sub_context_override": sub_context_override,
        "set_type_override": set_type_override,
        "q_type_override": q_type_override,
        "science_competency_override": science_competency_override,
        "ns_curriculum_context": ns_curriculum_context,
    }


def _ns_plan_all_batch_briefs(
    params: Any,
    count: int,
    base_seed: int | None,
    overrides: dict,
    config: Any,
    creative_planning: bool,
    decoded_subquestion_configs: list[dict] | None,
    **_kwargs: Any,
) -> list:
    return []


def _ns_do_sample_params(
    params: Any,
    overrides: dict,
    *,
    seed: int | None,
    subquestion_configs_decoded: list[dict] | None,
) -> Any:
    return _ns_sample_params(
        grade=params.grade,
        context=overrides["context_override"],
        sub_context=overrides["sub_context_override"],
        set_type=overrides["set_type_override"],
        q_type=overrides["q_type_override"],
        science_competency=overrides["science_competency_override"],
        content_type=params.content_type,
        learning_content=params.learning_content,
        learning_performance=params.learning_performance,
        seed=seed,
        sub_question_count=params.sub_question_count,
        question_word_limit=params.question_word_limit,
        option_word_limit=params.option_word_limit,
        subquestion_configs=subquestion_configs_decoded,
        difficulty=params.difficulty,
        reporting_scale=params.reporting_scale,
    )


def _ns_do_generate(rng_params: Any, overrides: dict, **kwargs: Any) -> Any:
    return _ns_generate_with_corrections(
        config=kwargs["config"],
        client=kwargs["client"],
        params=rng_params,
        question_id=kwargs["question_id"],
        max_retries=kwargs["max_retries"],
        skip_verify=kwargs["skip_verify"],
        disable_reference_fewshot=kwargs["disable_reference_fewshot"],
        html_renderer=kwargs["html_renderer"],
        image_generation_mode=kwargs["image_generation_mode"],
        user_passage=kwargs["user_passage"],
        text_word_limit=kwargs["text_word_limit"],
        user_options=kwargs["user_options"],
        user_topic=kwargs["user_topic"],
        user_core_question=kwargs["user_core_question"],
        core_question_callback=kwargs.get("core_question_callback", True),
        on_question_update=kwargs["on_question_update"],
        prior_scopes=kwargs["prior_scopes"],
        curriculum_context=overrides["ns_curriculum_context"],
        balanced_batch=kwargs["balanced_batch"],
    )


def _ns_build_generation_prompts(
    rng_params: Any, overrides: dict, **kwargs: Any
) -> tuple[str, str, list]:
    return _ns_build_prompts_impl(
        kwargs["config"],
        rng_params,
        disable_reference_fewshot=kwargs["disable_reference_fewshot"],
        image_generation_mode=kwargs["image_generation_mode"],
        user_passage=kwargs["user_passage"],
        text_word_limit=kwargs["text_word_limit"],
        user_options=kwargs["user_options"],
        user_topic=kwargs["user_topic"],
        user_core_question=kwargs["user_core_question"],
        prior_scopes=kwargs["prior_scopes"],
        core_question_callback=kwargs.get("core_question_callback", True),
        balanced_batch=kwargs["balanced_batch"],
    )


def _ns_build_subquestion_prompt_previews(
    rng_params: Any, overrides: dict, **kwargs: Any
) -> list[tuple[int, str, str, list]]:
    return _ns_build_sub_prompts_impl(
        kwargs["config"],
        rng_params,
        disable_reference_fewshot=kwargs["disable_reference_fewshot"],
        image_generation_mode=kwargs["image_generation_mode"],
        user_passage=kwargs["user_passage"],
        user_options=kwargs["user_options"],
        user_topic=kwargs["user_topic"],
        user_core_question=kwargs["user_core_question"],
        prior_scopes=kwargs["prior_scopes"],
        core_question_callback=kwargs.get("core_question_callback", True),
    )


def _ns_patch_metadata(question: Any, coverage_mode: str) -> Any:
    from src.natural_sciences.schemas import ExamQuestion as _NSExamQuestion  # noqa: PLC0415
    from src.natural_sciences.schemas import QuestionMetadata as _NSQM  # noqa: PLC0415

    if not isinstance(question, _NSExamQuestion):
        return question
    if question.metadata is None:
        question.metadata = _NSQM(
            grade=question.subquestions[0].年級 if question.subquestions else 0,
            model="unknown",
            coverage_mode_used=coverage_mode,
        )
    else:
        question.metadata = question.metadata.model_copy(
            update={"coverage_mode_used": coverage_mode}
        )
    return question


def _ns_plan_core_questions(client: Any, topic: str, **kwargs: Any) -> list[str]:
    # Lazy import so test monkeypatches on src.natural_sciences.planner are seen.
    import src.natural_sciences.planner as _m  # noqa: PLC0415
    return _m.plan_core_questions(client, topic, **kwargs)


def _ns_load_planner_stage(config_server: Any, grade: int | None) -> str:
    schemas = ns_load_schemas()
    if grade is not None:
        try:
            return grade_to_learning_stage(grade)
        except ValueError:
            pass
    return ns_load_learning_stage(schemas)


def _ns_build_schemas(config_server: Any, grade: int | None) -> dict:
    schemas = ns_load_schemas(config_server.natural_sciences_curriculum_dir)
    learning_stage = _resolve_stage(schemas, grade)
    performance = load_ns_learning_performance(
        config_server.natural_sciences_curriculum_dir / "learning_performance.json"
    )
    content = load_ns_learning_content(
        config_server.natural_sciences_curriculum_dir / "learning_content.json"
    )
    schemas["學習表現"] = [
        {
            "value": entry["value"],
            "instruction": entry.get("說明", ""),
            "科目": entry.get("科目", ""),
        }
        for entry in performance.get("學習表現", [])
        if entry.get("學習階段") == learning_stage
    ]
    schemas["學習內容"] = [
        {
            "value": entry["value"],
            "instruction": entry.get("條目說明", ""),
            "科目": entry.get("科目", ""),
        }
        for entry in content.get("學習內容", [])
        if entry.get("學習階段") == learning_stage
    ]
    ns_subjects = sorted({
        entry["科目"] for entry in schemas["學習內容"] if entry.get("科目")
    })
    if ns_subjects:
        schemas["科目"] = [{"value": s, "instruction": ""} for s in ns_subjects]
    return schemas


# ─────────────────────────────────────────────────────────────────────────────
# Math adapters
# ─────────────────────────────────────────────────────────────────────────────

def _math_coerce_overrides(params: Any, app_state: Any) -> dict:
    curriculum = app_state.curriculum
    performance = app_state.performance
    intro_text = app_state.intro_text
    grade_content = app_state.grade_content
    math_curriculum_context = getattr(app_state, "math_curriculum_context", None)
    style_override = (
        [MathQuestionStyle(v) for v in params.style] if params.style else None
    )
    context_override = (
        [_resolve_enum(v, MathQuestionContext) for v in params.context]
        if params.context else None
    )
    set_type_override = _resolve_enum(params.set_type, MathQuestionSetType)
    q_type_override = (
        [_resolve_enum(v, MathQuestionType) for v in params.q_type]
        if params.q_type else None
    )
    return {
        "curriculum": curriculum,
        "performance": performance,
        "intro_text": intro_text,
        "grade_content": grade_content,
        "math_curriculum_context": math_curriculum_context,
        "style_override": style_override,
        "context_override": context_override,
        "set_type_override": set_type_override,
        "q_type_override": q_type_override,
    }


def _math_plan_all_batch_briefs(
    params: Any,
    count: int,
    base_seed: int | None,
    overrides: dict,
    config: Any,
    creative_planning: bool,
    decoded_subquestion_configs: list[dict] | None,
    **_kwargs: Any,
) -> list:
    return []


def _math_do_sample_params(
    params: Any,
    overrides: dict,
    *,
    seed: int | None,
    subquestion_configs_decoded: list[dict] | None,
) -> Any:
    math_subject_filter: str | None = None
    if params.subject_filter:
        math_subject_filter = params.subject_filter[0]

    return _math_sample_params(
        grade_content=overrides["grade_content"],
        grade=params.grade,
        style=overrides["style_override"],
        context=overrides["context_override"],
        set_type=overrides["set_type_override"],
        q_type=overrides["q_type_override"],
        seed=seed,
        core_competency=params.core_competency,
        learning_content=params.learning_content,
        learning_performance=params.learning_performance,
        content_type=params.content_type,
        subject_filter=math_subject_filter,
        sub_question_count=params.sub_question_count,
        text_word_limit=params.text_word_limit,
        difficulty=params.difficulty,
    )


def _math_do_generate(rng_params: Any, overrides: dict, **kwargs: Any) -> Any:
    # Keep the complete SampledParams object intact: generate_with_corrections
    # reads sub_question_count from it to select the shared 題組 core.
    return _math_generate_with_corrections(
        config=kwargs["config"],
        client=kwargs["client"],
        curriculum=overrides["curriculum"],
        performance=overrides["performance"],
        intro_text=overrides["intro_text"],
        grade_content=overrides["grade_content"],
        params=rng_params,
        question_id=kwargs["question_id"],
        max_retries=kwargs["max_retries"],
        skip_verify=kwargs["skip_verify"],
        html_renderer=kwargs["html_renderer"],
        image_generation_mode=kwargs["image_generation_mode"],
        user_topic=kwargs["user_topic"] or "",
        user_passage=kwargs["user_passage"] or "",
        text_word_limit=kwargs["text_word_limit"],
        user_options=kwargs["user_options"],
        user_core_question=kwargs["user_core_question"] or "",
        on_question_update=kwargs["on_question_update"],
        prior_scopes=kwargs["prior_scopes"],
        curriculum_context=overrides["math_curriculum_context"],
    )


def _math_build_generation_prompts(
    rng_params: Any, overrides: dict, **kwargs: Any
) -> tuple[str, str, list]:
    return _math_build_prompts_impl(
        kwargs["config"],
        rng_params,
        user_topic=kwargs["user_topic"] or "",
        user_passage=kwargs["user_passage"] or "",
        text_word_limit=kwargs["text_word_limit"],
        user_options=kwargs["user_options"],
        user_core_question=kwargs["user_core_question"] or "",
        disable_reference_fewshot=kwargs["disable_reference_fewshot"],
        prior_scopes=kwargs["prior_scopes"],
        curriculum_context=overrides["math_curriculum_context"],
    )


def _math_plan_core_questions(client: Any, topic: str, **kwargs: Any) -> list[str]:
    # Lazy import so test monkeypatches on src.planner.plan_core_questions are seen.
    import src.planner as _m  # noqa: PLC0415
    return _m.plan_core_questions(client, topic, **kwargs)


def _math_load_planner_stage(config_server: Any, grade: int | None) -> str:
    if grade is not None:
        try:
            return grade_to_learning_stage(grade)
        except ValueError:
            pass
    return "第四學習階段"


def _math_build_schemas(config_server: Any, grade: int | None) -> dict:
    path: Path = config_server.question_schemas_path
    with path.open("r", encoding="utf-8") as f:
        schemas = json.load(f)
    schemas["科目"] = list(_MATH_SUBJECTS)
    schemas["題目內容類型"] = list(_MATH_CONTENT_TYPES)
    learning_stage = _resolve_stage(schemas, grade)
    performance = load_common_lp(config_server.math_curriculum_dir)
    schemas["學習表現"] = [
        {
            "value": entry["value"],
            "instruction": entry.get("說明", ""),
            "科目": entry.get("科目", ""),
        }
        for entry in performance.get("學習表現", [])
        if entry.get("學習階段") == learning_stage
    ]
    content = load_common_lc(config_server.math_curriculum_dir)
    schemas["學習內容"] = [
        {
            "value": entry["value"],
            "instruction": entry.get("條目說明", ""),
            "科目": entry.get("科目", ""),
        }
        for entry in content.get("學習內容", [])
        if entry.get("學習階段") == learning_stage
    ]
    return schemas


# ─────────────────────────────────────────────────────────────────────────────
# Registry — the ONLY place subject key strings appear in server/
# ─────────────────────────────────────────────────────────────────────────────

SUBJECTS: dict[str, SubjectSpec] = {
    "social_studies": SubjectSpec(
        key="social_studies",
        question_id_prefix="ss_",
        exam_question_cls=SSExamQuestion,
        coerce_overrides=_ss_coerce_overrides,
        plan_all_batch_briefs=_ss_plan_all_batch_briefs,
        do_sample_params=_ss_do_sample_params,
        do_generate=_ss_do_generate,
        build_generation_prompts=_ss_build_generation_prompts,
        build_subquestion_prompt_previews=_ss_build_subquestion_prompt_previews,
        extract_prior_scope=extract_ss_prior_scope,
        patch_metadata=_ss_patch_metadata,
        plan_core_questions=_ss_plan_core_questions,
        load_planner_stage=_ss_load_planner_stage,
        build_schemas=_ss_build_schemas,
        correct_question=_ss_correct_question,
        verify_question=_ss_verify_question,
    ),
    "natural_sciences": SubjectSpec(
        key="natural_sciences",
        question_id_prefix="ns_",
        exam_question_cls=NSExamQuestion,
        coerce_overrides=_ns_coerce_overrides,
        plan_all_batch_briefs=_ns_plan_all_batch_briefs,
        do_sample_params=_ns_do_sample_params,
        do_generate=_ns_do_generate,
        build_generation_prompts=_ns_build_generation_prompts,
        build_subquestion_prompt_previews=_ns_build_subquestion_prompt_previews,
        extract_prior_scope=extract_ns_prior_scope,
        patch_metadata=_ns_patch_metadata,
        plan_core_questions=_ns_plan_core_questions,
        load_planner_stage=_ns_load_planner_stage,
        build_schemas=_ns_build_schemas,
        validate_params=_ns_validate_params,
        correct_question=_ns_correct_question,
        verify_question=_ns_verify_question,
    ),
    "math": SubjectSpec(
        key="math",
        question_id_prefix="q_",
        exam_question_cls=MathExamQuestion,
        coerce_overrides=_math_coerce_overrides,
        plan_all_batch_briefs=_math_plan_all_batch_briefs,
        do_sample_params=_math_do_sample_params,
        do_generate=_math_do_generate,
        build_generation_prompts=_math_build_generation_prompts,
        extract_prior_scope=extract_math_prior_scope,
        patch_metadata=None,
        plan_core_questions=_math_plan_core_questions,
        load_planner_stage=_math_load_planner_stage,
        build_schemas=_math_build_schemas,
        validate_params=_math_validate_params,
        correct_question=_math_correct_question,
        verify_question=_math_verify_question,
    ),
}
