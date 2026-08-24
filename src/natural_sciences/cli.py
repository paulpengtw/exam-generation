"""CLI entry point for PISA Science + 108課綱自然科學 generation."""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from src.common.batch_dedup import PriorScope, extract_ns_prior_scope
from src.common.generation_core import generate_one_core, generate_with_corrections_core
from src.common.subject_spec import NATURAL_SCIENCES, SubjectGenerationSpec
from src.common.subquestion_forcing import force_grade
from src.common.verification_trail import VerificationTrailEntry
from src.config import Config
from src.curriculum_context import CurriculumContext, load_curriculum_context
from src.html_renderer import PlaywrightRenderer
from src.llm_client import LLMClient, emit_stage, make_render_error_sink, make_stderr_observer
from src.natural_sciences.context_builder import (
    LC_INSTRUCTIONS,
    LP_INSTRUCTIONS,
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
    curriculum_texts,
)
from src.natural_sciences.corrector import correct_question
from src.natural_sciences.curriculum_codes import repair_lc_refs, repair_lp_refs
from src.natural_sciences.curriculum_loader import grade_to_learning_stage
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schema_loader import load_grades, load_schemas
from src.natural_sciences.schemas import (
    ExamQuestion,
    ImageSpec,
    LearningContentRef,
    QuestionContext,
    QuestionMetadata,
    QuestionSetType,
    QuestionSubContext,
    QuestionType,
    RubricEntry,
    SampledParams,
    ScienceCompetency,
    SubQuestion,
    SubQuestionConfig,
)
from src.natural_sciences.verifier import verify_question
from src.renderer import render_image

_GRADES: list[int] = load_grades(load_schemas())

QuestionUpdateCallback = Callable[[ExamQuestion, str], None]
VerificationTrailCallback = Callable[[VerificationTrailEntry], None]


def _emit_question_update(
    callback: QuestionUpdateCallback | None,
    question: ExamQuestion,
    phase: str,
) -> None:
    if callback is None:
        return
    callback(question, phase)


def _with_text_word_limit(
    params: SampledParams,
    text_word_limit: int | None,
) -> SampledParams:
    if text_word_limit is None:
        return params

    slot_count = params.sub_question_count or len(params.subquestion_configs) or 3
    configs = list(params.subquestion_configs)
    if len(configs) < slot_count:
        configs.extend(SubQuestionConfig() for _ in range(slot_count - len(configs)))

    return params.model_copy(
        update={
            "text_word_limit": text_word_limit,
            "subquestion_configs": [
                cfg
                if cfg.text_word_limit is not None
                else cfg.model_copy(update={"text_word_limit": text_word_limit})
                for cfg in configs
            ],
        },
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="natural-sciences-exam-generation",
        description="Generate PISA Science + Taiwan natural-sciences exam questions",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate exam questions")
    gen.add_argument("--grade", type=int, choices=_GRADES, help="Target grade level")
    gen.add_argument("--context", type=str, nargs="+", choices=[c.value for c in QuestionContext])
    gen.add_argument("--sub-context", type=str, choices=[c.value for c in QuestionSubContext])
    gen.add_argument("--set-type", type=str, choices=[s.value for s in QuestionSetType])
    gen.add_argument("--q-type", type=str, nargs="+", choices=[q.value for q in QuestionType])
    gen.add_argument(
        "--science-competency",
        type=str,
        nargs="+",
        choices=[c.value for c in ScienceCompetency],
        help="PISA Science / Environmental Science competency pool",
    )
    gen.add_argument("--learning-content", type=str, nargs="+", help="指定學習內容 編碼")
    gen.add_argument("--learning-performance", type=str, nargs="+", help="指定學習表現 編碼")
    gen.add_argument("--content-type", type=str, help="題目內容類型")
    from src.natural_sciences.reporting_scale import REPORTING_SCALE_ORDER as _RS_ORDER
    gen.add_argument(
        "--reporting-scale",
        type=str,
        choices=list(_RS_ORDER),
        default=None,
        help="目標 PISA Science Reporting Scale 等級（取代舊有 --difficulty，自然科學專用）",
    )
    gen.add_argument("--count", type=int, default=1, help="Number of question sets to generate")
    gen.add_argument("--batch", action="store_true", help="Output as single JSON array")
    gen.add_argument("--seed", type=int, help="Random seed for reproducibility")
    gen.add_argument(
        "--no-core-question-callback",
        dest="core_question_callback",
        action="store_false",
        default=True,
        help="關閉最後小題回扣本題組核心問題的提示",
    )
    gen.add_argument("--no-verify", action="store_true", help="Skip verification pass")
    gen.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Max retries when verification fails (default: LLM_MAX_RETRIES env, fallback 3)",
    )
    gen.add_argument(
        "--image-generation-mode",
        choices=["html", "gpt_image"],
        default="html",
        help="Image creation mode for HTML image specs",
    )
    gen.add_argument("--output", type=str, help="Output directory")
    gen.add_argument("--dry-run", action="store_true", help="Show prompt without calling LLM")
    gen.add_argument("--env-file", type=str, help="Path to .env file")

    return parser.parse_args(argv)


def _resolve_enum(value: str | None, enum_cls: type) -> object | None:
    if value is None:
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    raise ValueError(f"Invalid value '{value}' for {enum_cls.__name__}")


def _parse_subquestion(
    sq_raw: dict,
    question_id: str,
    params: SampledParams,
    i: int,
) -> SubQuestion | None:
    if not isinstance(sq_raw, dict):
        return None
    try:
        cfg = params.subquestion_configs[i - 1] if i - 1 < len(params.subquestion_configs) else None
        lc_refs = [
            LearningContentRef(編碼=r.get("編碼", ""), 說明=r.get("說明", ""))
            for r in sq_raw.get("學習內容", [])
            if isinstance(r, dict) and r.get("編碼")
        ]
        lp_refs = [
            LearningContentRef(編碼=r.get("編碼", ""), 說明=r.get("說明", ""))
            for r in sq_raw.get("學習表現", [])
            if isinstance(r, dict) and r.get("編碼")
        ]
        learning_stage = grade_to_learning_stage(params.grade)
        if cfg and cfg.learning_content:
            lc_refs = [
                LearningContentRef(編碼=code, 說明=LC_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_content
            ]
        else:
            # Issue #92: canonicalize LLM-emitted codes; unknown codes are
            # dropped and an empty result falls back to the sampled pool.
            # Issue #287: off-stage codes are also dropped and fall back.
            lc_refs = repair_lc_refs(lc_refs, params.學習內容_pool, learning_stage=learning_stage)
        if cfg and cfg.learning_performance:
            lp_refs = [
                LearningContentRef(編碼=code, 說明=LP_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_performance
            ]
        else:
            lp_refs = repair_lp_refs(lp_refs, params.學習表現_pool, learning_stage=learning_stage)
        rubric = [
            RubricEntry(
                code=str(r.get("code", "")),
                規準說明=r.get("規準說明", ""),
                學生作答實例=r.get("學生作答實例", []),
            )
            for r in (sq_raw.get("評分規準") or sq_raw.get("評分標準") or [])
            if isinstance(r, dict)
        ]
        raw_distractor = sq_raw.get("誘答分析", {})
        if isinstance(raw_distractor, dict):
            distractor = {str(k): str(v) for k, v in raw_distractor.items()}
        else:
            distractor = {}
        sq_chart_spec = None
        raw_sq_spec = sq_raw.get("image_spec") or sq_raw.get("chart_spec")
        if isinstance(raw_sq_spec, dict):
            try:
                sq_chart_spec = ImageSpec(**raw_sq_spec)
            except Exception:
                sq_chart_spec = None
        result = SubQuestion(
            id=sq_raw.get("id", f"{question_id}-{sq_raw.get('序號', i):02d}"),
            序號=sq_raw.get("序號", i),
            年級=sq_raw.get("年級", params.grade),
            科目=sq_raw.get("科目", ["自然科學"]),
            科學能力=sq_raw.get("科學能力", [c.value for c in params.科學能力]),
            核心素養=sq_raw.get("核心素養", []),
            學習內容=lc_refs,
            學習表現=lp_refs,
            出題概念=sq_raw.get("出題概念", ""),
            reporting_scale=sq_raw.get("reporting_scale") or (cfg.reporting_scale if cfg else None),
            題型=sq_raw.get("題型", params.題型.value),
            題目=sq_raw.get("題目", ""),
            答案=sq_raw.get("答案", ""),
            答案解析=sq_raw.get("答案解析", ""),
            評分規準=rubric,
            誘答分析=distractor,
            題目內容類型=sq_raw.get("題目內容類型"),
            image_generation_mode=sq_raw.get("image_generation_mode"),
            圖片=sq_raw.get("圖片"),
            chart_spec=sq_chart_spec,
        )
        result.科目 = ["自然科學"]
        # Issue #286: force 年級 from sampled params, never trust the LLM value.
        # The prompt's own JSON example hard-codes 年級=8, causing junior-high
        # values to leak into senior-high requests.  科目 is already forced
        # above; 年級 gets the same treatment via the shared helper so that
        # 社會領域 (issue #290) can reuse it later.
        force_grade(result, params.grade)
        result._plan_index = i
        return result
    except Exception:
        return None


def _parse_text_shell(
    raw: dict,
    question_id: str,
    params: SampledParams,
    model: str,
) -> ExamQuestion:
    """Parse text-generator JSON output into an ExamQuestion without subquestions."""
    chart_spec = None
    raw_spec = raw.get("image_spec") or raw.get("chart_spec")
    if raw_spec:
        try:
            chart_spec = ImageSpec(**raw_spec)
        except Exception:
            if raw_spec.get("chart_type"):
                chart_spec = ImageSpec(
                    render_mode="chart",
                    chart_type=raw_spec.get("chart_type"),
                    data=raw_spec.get("data", {}),
                    labels=raw_spec.get("labels", {}),
                    title=raw_spec.get("title", ""),
                    description=raw_spec.get("description", ""),
                )
            else:
                chart_spec = ImageSpec(
                    render_mode="html",
                    description=raw_spec.get("description", raw_spec.get("title", "")),
                    title=raw_spec.get("title", ""),
                    data=raw_spec.get("data", {}),
                )

    return ExamQuestion(
        id=question_id,
        核心問題=raw.get("核心問題", ""),
        文本=raw.get("文本", ""),
        取材來源=raw.get("取材來源", []),
        subquestions=[],
        情境=[c.value for c in params.情境],
        情境子類別=params.情境子類別.value,
        題型種類=params.題型種類.value,
        題型=params.題型.value,
        科學能力=[c.value for c in params.科學能力],
        題目內容類型=params.題目內容類型,
        題目=raw.get("題目", []),
        正確解題分析=raw.get("正確解題分析", []),
        chart_spec=chart_spec,
        metadata=QuestionMetadata(
            grade=params.grade,
            model=model,
            seed=None,
        ),
    )


def _ns_build_text_system(params: SampledParams) -> tuple[str, dict]:
    learning_stage = grade_to_learning_stage(params.grade)
    content_text, performance_text = curriculum_texts(learning_stage, params.學習內容_pool)
    system = build_text_system_prompt(
        learning_stage=learning_stage,
        content_text=content_text,
        performance_text=performance_text,
    )
    return system, {
        "learning_stage": learning_stage,
        "content_text": content_text,
        "performance_text": performance_text,
    }


def _ns_build_text_user(
    params, few_shot_dir,
    user_passage, user_options, user_topic, user_core_question,
    image_generation_mode, disable_reference_fewshot, prior_scopes,
    core_question_callback,
    balanced_batch: bool = False,
):
    return build_text_user_prompt(
        params,
        few_shot_dir,
        rng=random.Random(params.seed),
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        image_generation_mode=image_generation_mode,
        disable_reference_fewshot=disable_reference_fewshot,
        prior_scopes=prior_scopes,
        core_question_callback=core_question_callback,
        balanced_batch=balanced_batch,
    )


def _ns_build_subquestion_system(stage_ctx: dict) -> str:
    return build_subquestion_system_prompt(
        learning_stage=stage_ctx["learning_stage"],
        content_text=stage_ctx["content_text"],
        performance_text=stage_ctx["performance_text"],
    )


def _ns_build_subquestion_user(
    text_raw, params, few_shot_dir, sq_plan, slot_cfg,
    image_generation_mode, disable_reference_fewshot,
    core_question_callback, is_last,
):
    return build_subquestion_user_prompt(
        核心問題=text_raw.get("核心問題", ""),
        文本=text_raw.get("文本", ""),
        取材來源=text_raw.get("取材來源", []),
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=few_shot_dir,
        image_generation_mode=image_generation_mode,
        cfg=slot_cfg,
        disable_reference_fewshot=disable_reference_fewshot,
        core_question_callback=core_question_callback,
        is_last=is_last,
    )


def _ns_make_fallback_sq_plans(params: SampledParams, n: int) -> list[dict]:
    return [
        {"序號": i, "題型": params.題型.value, "出題概念": ""}
        for i in range(1, n + 1)
    ]


def _ns_render_subquestion_images(
    question: ExamQuestion,
    config: Config,
    client: Any,
    html_renderer: Any,
    image_generation_mode: str,
    obs: Any,
    params: SampledParams,
) -> list[str]:
    """Render non-null NS 小題 chart specs and attach their PNG filenames."""
    rendered_paths: list[str] = []
    subquestion_image_modes = {
        i: cfg.image_generation_mode
        for i, cfg in enumerate(params.subquestion_configs, start=1)
        if cfg.image_generation_mode
    }
    for sub in question.subquestions:
        if not sub.chart_spec:
            continue
        plan_index = sub._plan_index if sub._plan_index is not None else sub.序號
        img_path = config.output_dir / f"{question.id}_sq{plan_index}.png"
        mode = subquestion_image_modes.get(plan_index, image_generation_mode)
        sub.image_generation_mode = mode
        question_text = "\n\n".join(
            part for part in (question.文本, sub.題目) if part
        )
        print(f"  Rendering subquestion image: {img_path}", file=sys.stderr)
        on_render_error, render_failed = make_render_error_sink(obs)
        emit_stage(obs, "image_agent", "render_image", "start")
        rendered = render_image(
            sub.chart_spec.model_dump(),
            img_path,
            question_text=question_text,
            html_renderer=html_renderer,
            llm_client=client,
            image_generation_mode=mode,
            on_error=on_render_error,
        )
        if not render_failed:
            emit_stage(obs, "image_agent", "render_image", "end")
        if rendered:
            sub.圖片 = img_path.name
            rendered_paths.append(rendered)
    return rendered_paths


_NS_SPEC = SubjectGenerationSpec(
    few_shot_subdir="natural_sciences",
    build_text_system_fn=_ns_build_text_system,
    build_text_user_fn=_ns_build_text_user,
    build_subquestion_system_fn=_ns_build_subquestion_system,
    build_subquestion_user_fn=_ns_build_subquestion_user,
    parse_text_shell_fn=_parse_text_shell,
    parse_subquestion_fn=_parse_subquestion,
    make_fallback_sq_plans_fn=_ns_make_fallback_sq_plans,
    ensure_visual_spec_fn=None,
    render_subquestion_images_fn=_ns_render_subquestion_images,
    image_question_text_fn=lambda q: "\n".join(q.題目),
    verify_fn=verify_question,
    correct_fn=correct_question,
)


def _ns_spec_for_batch(balanced_batch: bool) -> SubjectGenerationSpec:
    if not balanced_batch:
        return _NS_SPEC

    def build_text_user(*args: Any) -> tuple[str, list[Path]]:
        return _ns_build_text_user(*args, balanced_batch=True)

    return dataclasses.replace(_NS_SPEC, build_text_user_fn=build_text_user)


def generate_one(
    config: Config,
    client: LLMClient | None,
    params: SampledParams,
    question_id: str,
    dry_run: bool = False,
    skip_verify: bool = False,
    disable_reference_fewshot: bool = False,
    html_renderer: PlaywrightRenderer | None = None,
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    text_word_limit: int | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    on_question_update: QuestionUpdateCallback | None = None,
    on_trail_entry: VerificationTrailCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
    curriculum_context: CurriculumContext | None = None,
    balanced_batch: bool = False,
    core_question_callback: bool = True,
) -> ExamQuestion | str:
    """Generate a single PISA Science question set."""
    params = _with_text_word_limit(params, text_word_limit)
    return generate_one_core(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        spec=_ns_spec_for_batch(balanced_batch),
        dry_run=dry_run,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        core_question_callback=core_question_callback,
        on_question_update=on_question_update,
        on_trail_entry=on_trail_entry,
        sub_client_factory=sub_client_factory,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
    )


def build_generation_prompts(
    config: Config,
    params: SampledParams,
    **kwargs: Any,
) -> tuple[str, str, list]:
    """Build the exact prompts used by the 自然科學文本生成器."""
    from src.common.generation_core import build_text_generation_prompts

    params = _with_text_word_limit(params, kwargs.pop("text_word_limit", None))
    spec = _ns_spec_for_batch(kwargs.pop("balanced_batch", False))
    kwargs.setdefault("core_question_callback", True)
    system, user, images, _stage_ctx = build_text_generation_prompts(
        config, params, spec, **kwargs
    )
    return system, user, images


def build_subquestion_prompt_previews(
    config: Config,
    params: SampledParams,
    **kwargs: Any,
) -> list[tuple[int, str, str, list]]:
    """Build 子題產生器 prompts without invoking either generation stage."""
    from src.common.generation_core import (  # noqa: PLC0415
        build_subquestion_generation_prompts,
    )

    return build_subquestion_generation_prompts(
        config,
        params,
        _NS_SPEC,
        disable_reference_fewshot=kwargs.get("disable_reference_fewshot", False),
        image_generation_mode=kwargs.get("image_generation_mode", "html"),
        user_passage=kwargs.get("user_passage"),
        user_options=kwargs.get("user_options"),
        user_topic=kwargs.get("user_topic"),
        user_core_question=kwargs.get("user_core_question"),
        prior_scopes=kwargs.get("prior_scopes"),
        core_question_callback=kwargs.get("core_question_callback", True),
    )


def generate_with_corrections(
    config: Config,
    client: LLMClient | None,
    params: SampledParams,
    question_id: str,
    max_retries: int = 3,
    skip_verify: bool = False,
    disable_reference_fewshot: bool = False,
    html_renderer: PlaywrightRenderer | None = None,
    image_generation_mode: str = "html",
    dry_run: bool = False,
    user_passage: str | None = None,
    text_word_limit: int | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    on_question_update: QuestionUpdateCallback | None = None,
    on_trail_entry: VerificationTrailCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
    curriculum_context: CurriculumContext | None = None,
    balanced_batch: bool = False,
    core_question_callback: bool = True,
) -> ExamQuestion | str:
    """generate_one followed by up to max_retries correction passes.

    ``metadata.reporting_scales`` is set to the resolved Reporting Scale of
    each surviving 小題 in 序號 order.  The list is written once here — after
    the correction loop — so it is consistent with the final subquestion list
    and cannot drift across correction passes.
    """
    result = generate_with_corrections_core(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        spec=_ns_spec_for_batch(balanced_batch),
        max_retries=max_retries,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        dry_run=dry_run,
        user_passage=user_passage,
        text_word_limit=text_word_limit,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        core_question_callback=core_question_callback,
        on_question_update=on_question_update,
        on_trail_entry=on_trail_entry,
        sub_client_factory=sub_client_factory,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
    )
    if isinstance(result, ExamQuestion) and result.metadata is not None:
        result.metadata.reporting_scales = [
            sq.reporting_scale or ""
            for sq in result.subquestions
        ]
    return result


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.command != "generate":
        return

    config = Config.from_env(args.env_file)
    if args.output:
        config.output_dir = Path(args.output)

    if not args.dry_run:
        config.validate()

    config.output_dir.mkdir(parents=True, exist_ok=True)

    client = None if args.dry_run else LLMClient(config)
    if client is not None:
        client.set_observer(make_stderr_observer(truncate=config.log_truncate))

    html_renderer = None
    if not args.dry_run:
        try:
            html_renderer = PlaywrightRenderer()
            html_renderer.start()
            print("  Playwright browser started.", file=sys.stderr)
        except Exception as e:
            print(
                f"  Warning: Playwright unavailable ({e}). HTML images will be skipped.",
                file=sys.stderr,
            )

    context_override = (
        [_resolve_enum(v, QuestionContext) for v in args.context]
        if args.context else None
    )
    sub_context_override = _resolve_enum(args.sub_context, QuestionSubContext)
    set_type_override = _resolve_enum(args.set_type, QuestionSetType)
    q_type_override = [_resolve_enum(v, QuestionType) for v in args.q_type] if args.q_type else None
    science_competency_override = (
        [_resolve_enum(v, ScienceCompetency) for v in args.science_competency]
        if args.science_competency else None
    )
    learning_content_override = args.learning_content if args.learning_content else None
    learning_performance_override = args.learning_performance if args.learning_performance else None
    content_type_override = args.content_type if args.content_type else None

    # Build the canonical NS curriculum context once per run; all pipeline stages share it.
    ns_curriculum_context = load_curriculum_context(NATURAL_SCIENCES.data_dir)

    results = []
    prior_scopes: list[PriorScope] = []
    base_seed = args.seed
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
            question_id = f"ns_{timestamp}_{i+1:03d}"

            params = sample_params(
                grade=args.grade,
                context=context_override,
                sub_context=sub_context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                science_competency=science_competency_override,
                learning_content=learning_content_override,
                learning_performance=learning_performance_override,
                content_type=content_type_override,
                seed=seed,
                reporting_scale=args.reporting_scale,
            )

            print(
                f"\n[{i + 1}/{args.count}] Sampled: grade={params.grade}, "
                f"情境={'、'.join(c.value for c in params.情境)}, "
                f"情境子類別={params.情境子類別.value}, "
                f"題型={params.題型.value}, "
                f"科學能力={'、'.join(c.value for c in params.科學能力)}, "
                f"題目內容類型={params.題目內容類型}",
                file=sys.stderr,
            )

            result = generate_with_corrections(
                config=config,
                client=client,
                params=params,
                question_id=question_id,
                max_retries=max_retries,
                skip_verify=args.no_verify,
                html_renderer=html_renderer,
                image_generation_mode=args.image_generation_mode,
                dry_run=args.dry_run,
                core_question_callback=args.core_question_callback,
                prior_scopes=list(prior_scopes),
                curriculum_context=ns_curriculum_context,
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)
            results.append(question)

            scope = extract_ns_prior_scope(question)
            if scope is not None:
                prior_scopes.append(scope)

            if not args.batch:
                out_path = config.output_dir / f"{question_id}.json"
                out_path.write_text(
                    question.model_dump_json(indent=2, exclude_none=True),
                    encoding="utf-8",
                )
                print(f"  Saved: {out_path}", file=sys.stderr)

        if args.batch and results:
            batch_path = config.output_dir / f"batch_{timestamp}.json"
            batch_data = [json.loads(q.model_dump_json(exclude_none=True)) for q in results]
            batch_path.write_text(
                json.dumps(batch_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\nBatch saved: {batch_path}", file=sys.stderr)

        print(f"\nDone. Generated {len(results)} question set(s).", file=sys.stderr)

    finally:
        if html_renderer is not None:
            html_renderer.stop()


if __name__ == "__main__":
    main()
