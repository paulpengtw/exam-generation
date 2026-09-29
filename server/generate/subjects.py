"""SubjectSpec registry — single declaration point for all per-subject dispatch.

This module is the ONLY place in server/ where subject strings appear as keys.
Every dispatch site in service.py, routes.py, and utility/routes.py must resolve
behaviour through SUBJECTS[subject_key] rather than if/elif chains.

Subject adapters are imported here once and patched at this module boundary by
the service seam tests.  They convert the resolver-completed payload and keep
generation independent of the random samplers.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Callable

from src.cli import _math_params_from_resolved as _math_params_from_resolved_impl
from src.cli import build_generation_prompts as _math_build_prompts_impl
from src.cli import build_subquestion_prompt_previews as _math_build_sub_prompts_impl
from src.cli import generate_with_corrections as _math_generate_with_corrections
from src.common.admission import admitted_parents_by_code
from src.common.batch_dedup import (
    extract_math_prior_scope,
    extract_ns_prior_scope,
    extract_ss_prior_scope,
)
from src.common.core_competency_loader import allowed_competencies as allowed_math_competencies
from src.common.core_competency_loader import (
    competency_instructions as math_competency_instructions,
)
from src.common.core_competency_loader import load_core_competencies as load_math_core_competencies
from src.common.curriculum_loader import load_learning_content as load_common_lc
from src.common.curriculum_loader import load_learning_performance as load_common_lp
from src.common.kwarg_compat import accepts_kwarg
from src.corrector import correct_question as _math_correct_question
from src.natural_sciences.cli import (
    _ns_params_from_resolved as _ns_params_from_resolved_impl,
)
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
from src.natural_sciences.reporting_scale import (
    REPORTING_SCALE_LEVELS,
    REPORTING_SCALE_ORDER,
)
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
from src.sampler import _MATH_SUBJECT_TO_PREFIXES, grade_to_learning_stage
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
    _ss_params_from_resolved as _ss_params_from_resolved_impl,
)
from src.social_studies.cli import (
    build_generation_prompts as _ss_build_prompts_impl,
)
from src.social_studies.cli import (
    build_subquestion_prompt_previews as _ss_build_sub_prompts_impl,
)
from src.social_studies.cli import (
    generate_with_corrections as _ss_generate_with_corrections,
)
from src.social_studies.core_competency_loader import (
    allowed_competencies as allowed_ss_competencies,
)
from src.social_studies.core_competency_loader import (
    competency_instructions as ss_competency_instructions,
)
from src.social_studies.core_competency_loader import (
    load_core_competencies as load_ss_core_competencies,
)
from src.social_studies.corrector import correct_question as _ss_correct_question
from src.social_studies.curriculum_loader import (
    load_learning_content as load_ss_learning_content,
)
from src.social_studies.curriculum_loader import (
    load_learning_performance as load_ss_learning_performance,
)
from src.social_studies.domain_mapping import (
    load_code_to_domains_mapping as load_ss_code_to_domains_mapping,
)
from src.social_studies.figure_kind_loader import (
    CANONICAL_FIGURE_KINDS,
)
from src.social_studies.schema_loader import (
    digital_only_question_types as ss_digital_only_question_types,
)
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


def _scoped_client(factory: Callable[..., Any], config: Any, scope: Any) -> Any:
    """Call a client factory with explicit scope when its seam supports it."""
    client = factory(config, scope=scope) if accepts_kwarg(factory, "scope") else factory(config)
    if scope is not None and hasattr(client, "set_scope"):
        client.set_scope(scope)
    return client


def resolved_payload_for_index(params: Any, index: int) -> dict[str, Any]:
    """Return the already-resolved request payload for one worker."""
    payload = params.model_dump(mode="json")
    raw_rows = payload.get("per_question_params")
    row: dict[str, Any] | None = None
    if raw_rows:
        if isinstance(raw_rows, str):
            raw_rows = json.loads(raw_rows)
        if not isinstance(raw_rows, list) or index >= len(raw_rows):
            raise ValueError("resolved per_question_params has no worker row")
        row = raw_rows[index]
        if not isinstance(row, dict):
            raise ValueError(f"resolved per_question_params[{index}] must be an object")
        payload.update(row)
    payload["per_question_params"] = None
    row_seed = row.get("seed") if row is not None else None
    if row_seed is None and params.seed is not None:
        payload["seed"] = params.seed + index
    return payload


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
    params_from_resolved_payload
                            ``(payload, overrides) -> SampledParams``
                            Converts the resolver's completed wire payload
                            without drawing any new values.
    do_generate             ``(rng_params, overrides, **common_kwargs)
                            -> ExamQuestion``
                            Adapters consume the resolver-completed payload so
                            generation does not perform another random draw.
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
    params_from_resolved_payload: Callable
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


def _validate_curriculum_subject_pairs(
    params: Any,
    *,
    load_content: Callable[[], dict],
    load_performance: Callable[[], dict],
    subquestion_configs: list[dict] | None = None,
) -> None:
    subjects = [value for value in (getattr(params, "subject_filter", None) or []) if value]
    if not subjects:
        return

    admissions = {
        "learning_content": admitted_parents_by_code(
            load_content(), "學習內容", "科目"
        ),
        "learning_performance": admitted_parents_by_code(
            load_performance(), "學習表現", "科目"
        ),
    }
    subject_label = "、".join(subjects)

    def validate_values(values: object, field: str) -> None:
        if not isinstance(values, list):
            return
        for code in values:
            if not isinstance(code, str):
                continue
            admitted_subjects = admissions[field].get(code, [])
            if not any(subject in admitted_subjects for subject in subjects):
                raise ValueError(
                    f"科目 {subject_label!r} does not admit {field} code {code!r}"
                )

    for field in admissions:
        validate_values(getattr(params, field, None), field)
    for config in subquestion_configs or []:
        for field in admissions:
            validate_values(config.get(field), field)


def _math_curriculum_dir() -> Path:
    return Path(
        os.environ.get(
            "MATH_CURRICULUM_DIR",
            str(Path(__file__).resolve().parents[2] / "data" / "math" / "curriculum"),
        )
    )


def _reject_unknown_subquestion_config_keys(
    decoded_rows: list,
    config_cls: type,
    *,
    subject_label: str,
) -> None:
    """Reject any per-小題 config row whose keys are not declared by config_cls.

    Runs config_cls.model_validate(row) for each dict row and collects only
    errors whose type == "extra_forbidden" (pydantic's extra="forbid" violation).
    All other error types are ignored — in particular, unknown enum VALUES for
    question_type are left to existing downstream behaviour: the SS sampler
    (_coerce_subquestion_config) redraws an unknown question_type, and the NS
    sampler raises a pydantic enum error, so both already produce 422 without
    this helper touching enum values.

    Raises ValueError naming every offending path as
      subquestion_configs[{i}].{key}
    followed by a generic message.
    """
    import pydantic  # noqa: PLC0415

    violations: list[str] = []
    for i, row in enumerate(decoded_rows):
        if not isinstance(row, dict):
            continue
        try:
            config_cls.model_validate(row)
        except pydantic.ValidationError as exc:
            for error in exc.errors():
                if error.get("type") == "extra_forbidden":
                    loc = error.get("loc", ())
                    key = loc[-1] if loc else "?"
                    violations.append(
                        f"subquestion_configs[{i}].{key} is not a valid "
                        f"各小題配置 field for {subject_label}"
                    )
    if violations:
        raise ValueError("; ".join(violations))


def _ns_validate_params(params: Any) -> None:
    unsupported_surface_fields = [
        field
        for field in ("content_domain", "target_surface")
        if getattr(params, field, None) is not None
    ]
    if unsupported_surface_fields:
        raise ValueError(
            "The following parameters are not supported for natural sciences: "
            + ", ".join(unsupported_surface_fields)
        )

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

    if params.subquestion_configs:
        try:
            raw = json.loads(params.subquestion_configs)
        except (TypeError, json.JSONDecodeError):
            raw = []
        if isinstance(raw, list):
            from src.natural_sciences.schemas import (  # noqa: PLC0415
                SubQuestionConfig as NSSubQuestionConfig,
            )
            _reject_unknown_subquestion_config_keys(
                raw, NSSubQuestionConfig, subject_label="自然科學"
            )


def _ss_validate_params(params: Any) -> None:
    from src.social_studies.schema_loader import load_schemas  # noqa: PLC0415
    from src.social_studies.schemas import ContentDomain  # noqa: PLC0415

    question_type_values = {
        row["value"]
        for row in load_schemas().get("題型", [])
        if isinstance(row, dict) and isinstance(row.get("value"), str)
    }
    invalid_q_types = sorted(set(params.q_type or []) - question_type_values)
    if invalid_q_types:
        raise ValueError(
            "q_type contains retired or unknown social-studies question type(s): "
            + ", ".join(invalid_q_types)
        )

    if params.content_domain is not None and params.content_domain not in {
        member.value for member in ContentDomain
    }:
        raise ValueError(
            f"content_domain {params.content_domain!r} is not a valid social-studies domain"
        )

    try:
        decoded = json.loads(params.subquestion_configs) if params.subquestion_configs else []
    except (TypeError, json.JSONDecodeError):
        decoded = []
    decoded_configs = (
        [item for item in decoded if isinstance(item, dict)]
        if isinstance(decoded, list)
        else None
    )
    _validate_curriculum_subject_pairs(
        params,
        load_content=load_ss_learning_content,
        load_performance=load_ss_learning_performance,
        subquestion_configs=decoded_configs,
    )
    if isinstance(decoded, list):
        retired_pins = {
            question_type
            for item in decoded
            if isinstance(item, dict)
            for question_type in [item.get("question_type")]
            if question_type == "封閉式建構反應題"
        }
        if retired_pins:
            raise ValueError(
                "封閉式建構反應題已退役（retired），新的生成請求不得釘選此題型"
            )

    if params.target_surface in {None, "紙本"}:
        if isinstance(decoded, list):
            digital_only = set(ss_digital_only_question_types())
            pinned_types = {
                question_type
                for item in decoded
                if isinstance(item, dict)
                for question_type in [item.get("question_type")]
                if isinstance(question_type, str)
            }
            pinned_types.update(params.q_type or [])
            blocked = sorted(pinned_types & digital_only)
            if blocked:
                raise ValueError(
                    "target_surface must be 數位 for digital-only question type(s): "
                    + ", ".join(blocked)
                )

    if isinstance(decoded, list):
        from src.social_studies.schemas import (  # noqa: PLC0415
            SubQuestionConfig as SSSubQuestionConfig,
        )
        _reject_unknown_subquestion_config_keys(
            decoded, SSSubQuestionConfig, subject_label="社會領域"
        )


def _math_validate_params(params: Any) -> None:
    _validate_curriculum_subject_pairs(
        params,
        load_content=lambda: load_common_lc(
            _math_curriculum_dir(),
            subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES,
        ),
        load_performance=lambda: load_common_lp(
            _math_curriculum_dir(),
            subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES,
        ),
    )
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
            "content_domain",
            "target_surface",
        )
        if getattr(params, field) is not None
    ]
    if params.text_instruction and params.text_instruction.strip():
        unsupported.append("text_instruction")
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

    pre_params_list = [
        _ss_params_from_resolved_impl(resolved_payload_for_index(params, i))
        for i in range(count)
    ]
    planning_client = _scoped_client(
        client_factory,
        config,
        kwargs.get("operation_scope"),
    )
    observer = kwargs.get("observer")
    if observer is not None:
        planning_client.set_observer(observer)
    planner_scope = kwargs.get("operation_scope")
    return _ss_plan_batch_briefs(
        planning_client,
        config,
        pre_params_list,
        scope=planner_scope,
    )


def _ss_params_from_resolved_payload(payload: dict[str, Any], _overrides: dict) -> Any:
    return _ss_params_from_resolved_impl(payload)


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
        text_instruction=kwargs.get("text_instruction"),
        core_question_callback=kwargs.get("core_question_callback", True),
        on_question_update=kwargs["on_question_update"],
        on_trail_entry=kwargs.get("on_trail_entry"),
        on_figure_policy_entry=kwargs.get("on_figure_policy_entry"),
        on_reference_example_entry=kwargs.get("on_reference_example_entry"),
        prior_scopes=kwargs["prior_scopes"],
        curriculum_context=overrides["ss_curriculum_context"],
        balanced_batch=kwargs["balanced_batch"],
        is_cancelled=kwargs.get("is_cancelled"),
        question_context=kwargs.get("question_context"),
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
        text_instruction=kwargs.get("text_instruction"),
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
        text_instruction=kwargs.get("text_instruction"),
        prior_scopes=kwargs["prior_scopes"],
        core_question_callback=kwargs.get("core_question_callback", True),
    )


def _ss_patch_metadata(
    question: Any,
    coverage_mode: str,
    target_surface: str | None = None,
) -> Any:
    from src.social_studies.schemas import ExamQuestion as _SSExamQuestion  # noqa: PLC0415
    from src.social_studies.schemas import QuestionMetadata as _QM  # noqa: PLC0415

    if not isinstance(question, _SSExamQuestion):
        return question
    surface = "紙本" if target_surface is None else target_surface
    if question.metadata is None:
        # Fall back to a minimal metadata object; model attribute may not be
        # available on all config types, so use "unknown" as sentinel.
        question.metadata = _QM(
            grade=question.subquestions[0].年級 if question.subquestions else 0,
            model="unknown",
            coverage_mode_used=coverage_mode,
            surface_used=surface,
        )
    else:
        question.metadata = question.metadata.model_copy(
            update={"coverage_mode_used": coverage_mode, "surface_used": surface}
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
    core_path = config_server.social_studies_curriculum_dir / "core_competencies.json"
    core_data = load_ss_core_competencies(core_path if core_path.exists() else None)
    core_instructions = ss_competency_instructions(core_data)
    schemas["核心素養"] = [
        {"value": value, "instruction": core_instructions.get(value, "")}
        for value in allowed_ss_competencies(core_data, learning_stage)
    ]
    schemas["digital_only_question_types"] = ss_digital_only_question_types(schemas)
    schemas["學習表現"] = [
        {
            "value": entry["value"],
            "instruction": entry.get("說明", ""),
            "科目": entry.get("科目", ""),
            "admitted_by": entry["admitted_by"],
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
            "admitted_by": entry["admitted_by"],
        }
        for entry in content.get("學習內容", [])
        if entry.get("學習階段") == learning_stage
    ]
    schemas["內容領域_mapping"] = load_ss_code_to_domains_mapping(
        curriculum_dir=config_server.social_studies_curriculum_dir,
    )
    schemas["figure_kinds"] = list(CANONICAL_FIGURE_KINDS)
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


def _ns_params_from_resolved_payload(payload: dict[str, Any], _overrides: dict) -> Any:
    return _ns_params_from_resolved_impl(payload)


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
        on_trail_entry=kwargs.get("on_trail_entry"),
        on_figure_policy_entry=kwargs.get("on_figure_policy_entry"),
        on_reference_example_entry=kwargs.get("on_reference_example_entry"),
        prior_scopes=kwargs["prior_scopes"],
        curriculum_context=overrides["ns_curriculum_context"],
        balanced_batch=kwargs["balanced_batch"],
        is_cancelled=kwargs.get("is_cancelled"),
        question_context=kwargs.get("question_context"),
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
        text_instruction=kwargs.get("text_instruction"),
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


def _ns_patch_metadata(
    question: Any,
    coverage_mode: str,
    _target_surface: str | None = None,
) -> Any:
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
    schemas["reporting_scale"] = [
        {"value": level, "instruction": REPORTING_SCALE_LEVELS[level]}
        for level in REPORTING_SCALE_ORDER
    ]
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
    schemas["figure_kinds"] = list(CANONICAL_FIGURE_KINDS)
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


def _math_params_from_resolved_payload(
    payload: dict[str, Any],
    overrides: dict,
) -> Any:
    return _math_params_from_resolved_impl(
        payload,
        grade_content=overrides["grade_content"],
        performance=overrides["performance"],
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
        on_trail_entry=kwargs.get("on_trail_entry"),
        prior_scopes=kwargs["prior_scopes"],
        curriculum_context=overrides["math_curriculum_context"],
        is_cancelled=kwargs.get("is_cancelled"),
        question_context=kwargs.get("question_context"),
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


def _math_build_subquestion_prompt_previews(
    rng_params: Any, overrides: dict, **kwargs: Any
) -> list[tuple[int, str, str, list]]:
    """Build math 子題產生器 previews for 題組題 with zero-based subquestion_index.

    Returns an empty list for flat (單一題) math where sub_question_count is None.
    """
    return _math_build_sub_prompts_impl(
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
    core_path = config_server.math_curriculum_dir / "core_competencies.json"
    core_data = load_math_core_competencies(core_path)
    core_instructions = math_competency_instructions(core_data)
    schemas["核心素養"] = [
        {"value": value, "instruction": core_instructions.get(value, "")}
        for value in allowed_math_competencies(core_data, learning_stage)
    ]
    performance = load_common_lp(
        config_server.math_curriculum_dir,
        subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES,
    )
    schemas["學習表現"] = [
        {
            "value": entry["value"],
            "instruction": entry.get("說明", ""),
            "科目": entry.get("科目", ""),
            "admitted_by": entry["admitted_by"],
        }
        for entry in performance.get("學習表現", [])
        if entry.get("學習階段") == learning_stage
    ]
    content = load_common_lc(
        config_server.math_curriculum_dir,
        subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES,
    )
    schemas["學習內容"] = [
        {
            "value": entry["value"],
            "instruction": entry.get("條目說明", ""),
            "科目": entry.get("科目", ""),
            "admitted_by": entry["admitted_by"],
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
        params_from_resolved_payload=_ss_params_from_resolved_payload,
        do_generate=_ss_do_generate,
        build_generation_prompts=_ss_build_generation_prompts,
        build_subquestion_prompt_previews=_ss_build_subquestion_prompt_previews,
        extract_prior_scope=extract_ss_prior_scope,
        patch_metadata=_ss_patch_metadata,
        plan_core_questions=_ss_plan_core_questions,
        load_planner_stage=_ss_load_planner_stage,
        build_schemas=_ss_build_schemas,
        validate_params=_ss_validate_params,
        correct_question=_ss_correct_question,
        verify_question=_ss_verify_question,
    ),
    "natural_sciences": SubjectSpec(
        key="natural_sciences",
        question_id_prefix="ns_",
        exam_question_cls=NSExamQuestion,
        coerce_overrides=_ns_coerce_overrides,
        plan_all_batch_briefs=_ns_plan_all_batch_briefs,
        params_from_resolved_payload=_ns_params_from_resolved_payload,
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
        params_from_resolved_payload=_math_params_from_resolved_payload,
        do_generate=_math_do_generate,
        build_generation_prompts=_math_build_generation_prompts,
        build_subquestion_prompt_previews=_math_build_subquestion_prompt_previews,
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
