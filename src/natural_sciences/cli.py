"""CLI entry point for PISA Science + 108課綱自然科學 generation."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import Config
from src.html_renderer import PlaywrightRenderer
from src.llm_client import LLMClient, emit_stage, make_stderr_observer
from src.natural_sciences.context_builder import (
    LC_INSTRUCTIONS,
    LP_INSTRUCTIONS,
    _LEARNING_STAGE,
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
)
from src.natural_sciences.corrector import correct_question
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
)
from src.natural_sciences.verifier import verify_question
from src.renderer import render_image

_GRADES: list[int] = load_grades(load_schemas())

QuestionUpdateCallback = Callable[[ExamQuestion, str], None]


def _emit_question_update(
    callback: QuestionUpdateCallback | None,
    question: ExamQuestion,
    phase: str,
) -> None:
    if callback is None:
        return
    callback(question, phase)


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
    gen.add_argument("--count", type=int, default=1, help="Number of question sets to generate")
    gen.add_argument("--batch", action="store_true", help="Output as single JSON array")
    gen.add_argument("--seed", type=int, help="Random seed for reproducibility")
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


def _parse_question(
    raw: dict,
    question_id: str,
    params: SampledParams,
    model: str,
) -> ExamQuestion:
    """Parse raw LLM JSON output into a natural-sciences ExamQuestion."""
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

    subquestions: list[SubQuestion] = []
    for i, sq_raw in enumerate(raw.get("subquestions", []), start=1):
        if not isinstance(sq_raw, dict):
            continue
        try:
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
            rubric = [
                RubricEntry(
                    code=str(r.get("code", "")),
                    規準說明=r.get("規準說明", ""),
                    學生作答實例=r.get("學生作答實例", []),
                )
                for r in (sq_raw.get("評分規準") or sq_raw.get("評分標準") or [])
                if isinstance(r, dict)
            ]
            subquestions.append(
                SubQuestion(
                    id=sq_raw.get("id", f"{question_id}-{sq_raw.get('序號', i):02d}"),
                    序號=sq_raw.get("序號", i),
                    年級=sq_raw.get("年級", params.grade),
                    科目=sq_raw.get("科目", ["自然科學"]),
                    科學能力=sq_raw.get("科學能力", [c.value for c in params.科學能力]),
                    核心素養=sq_raw.get("核心素養", []),
                    學習內容=lc_refs,
                    學習表現=lp_refs,
                    出題概念=sq_raw.get("出題概念", ""),
                    題型=sq_raw.get("題型", params.題型.value),
                    題目=sq_raw.get("題目", ""),
                    答案=sq_raw.get("答案", ""),
                    答案解析=sq_raw.get("答案解析", ""),
                    評分規準=rubric,
                )
            )
        except Exception:
            pass

    return ExamQuestion(
        id=question_id,
        核心問題=raw.get("核心問題", ""),
        文本=raw.get("文本", ""),
        取材來源=raw.get("取材來源", []),
        subquestions=subquestions,
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
        if cfg and cfg.learning_content:
            lc_refs = [
                LearningContentRef(編碼=code, 說明=LC_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_content
            ]
        if cfg and cfg.learning_performance:
            lp_refs = [
                LearningContentRef(編碼=code, 說明=LP_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_performance
            ]
        rubric = [
            RubricEntry(
                code=str(r.get("code", "")),
                規準說明=r.get("規準說明", ""),
                學生作答實例=r.get("學生作答實例", []),
            )
            for r in (sq_raw.get("評分規準") or sq_raw.get("評分標準") or [])
            if isinstance(r, dict)
        ]
        return SubQuestion(
            id=sq_raw.get("id", f"{question_id}-{sq_raw.get('序號', i):02d}"),
            序號=sq_raw.get("序號", i),
            年級=sq_raw.get("年級", params.grade),
            科目=sq_raw.get("科目", ["自然科學"]),
            科學能力=sq_raw.get("科學能力", [c.value for c in params.科學能力]),
            核心素養=sq_raw.get("核心素養", []),
            學習內容=lc_refs,
            學習表現=lp_refs,
            出題概念=sq_raw.get("出題概念", ""),
            題型=sq_raw.get("題型", params.題型.value),
            題目=sq_raw.get("題目", ""),
            答案=sq_raw.get("答案", ""),
            答案解析=sq_raw.get("答案解析", ""),
            評分規準=rubric,
        )
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
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    on_question_update: QuestionUpdateCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
) -> ExamQuestion | str:
    """Generate a single PISA Science question set."""
    if dry_run:
        text_system = build_text_system_prompt()
        text_user, text_images = build_text_user_prompt(
            params,
            config.data_dir / "natural_sciences" / "few_shot",
            user_passage=user_passage,
            user_options=user_options,
            user_topic=user_topic,
            user_core_question=user_core_question,
            image_generation_mode=image_generation_mode,
            disable_reference_fewshot=disable_reference_fewshot,
        )
        img_note = f" ({len(text_images)} few-shot images)" if text_images else ""
        return (
            f"=== TEXT SYSTEM PROMPT ({len(text_system)} chars) ===\n{text_system[:2000]}...\n\n"
            f"=== TEXT USER PROMPT ({len(text_user)} chars{img_note}) ===\n{text_user}"
        )

    obs = client.get_observer() if client else None

    print(f"  Generating question {question_id}...", file=sys.stderr)

    text_system = build_text_system_prompt()
    text_user, text_images = build_text_user_prompt(
        params,
        config.data_dir / "natural_sciences" / "few_shot",
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        image_generation_mode=image_generation_mode,
        disable_reference_fewshot=disable_reference_fewshot,
    )
    emit_stage(obs, "generator", "llm_generate", "start")
    text_raw = client.generate_json(text_system, text_user, images=text_images or None)
    emit_stage(obs, "generator", "llm_generate", "end")

    question = _parse_text_shell(text_raw, question_id, params, config.model_execute)
    sq_plans: list[dict] = text_raw.get("subquestions", [])
    if not sq_plans:
        n = params.sub_question_count or 3
        sq_plans = [
            {"序號": i, "題型": params.題型.value, "出題概念": ""}
            for i in range(1, n + 1)
        ]

    sub_system = build_subquestion_system_prompt(learning_stage=_LEARNING_STAGE)
    max_workers = min(len(sq_plans), config.subgen_max_concurrency)
    use_embedded_subquestions = (
        sub_client_factory is None and client is not None and not isinstance(client, LLMClient)
    )

    def _generate_subquestion(sq_plan: dict) -> SubQuestion | None:
        idx = sq_plan.get("序號", sq_plans.index(sq_plan) + 1)
        agent_id = f"sub_generator#{idx}"
        if use_embedded_subquestions:
            return _parse_subquestion(sq_plan, question_id, params, idx)

        sub_client = sub_client_factory() if sub_client_factory is not None else LLMClient(config)
        if hasattr(sub_client, "set_observer"):
            sub_client.set_observer(obs)
        slot_cfg = (
            params.subquestion_configs[idx - 1]
            if idx - 1 < len(params.subquestion_configs) else None
        )
        sub_user, sub_images = build_subquestion_user_prompt(
            核心問題=text_raw.get("核心問題", ""),
            文本=text_raw.get("文本", ""),
            取材來源=text_raw.get("取材來源", []),
            sq_plan=sq_plan,
            params=params,
            few_shot_dir=config.data_dir / "natural_sciences" / "few_shot",
            image_generation_mode=image_generation_mode,
            cfg=slot_cfg,
            disable_reference_fewshot=disable_reference_fewshot,
        )
        emit_stage(obs, agent_id, "llm_generate", "start")
        try:
            sq_raw = sub_client.generate_json(
                sub_system,
                sub_user,
                images=sub_images or None,
                agent_override=agent_id,
            )
            result = _parse_subquestion(sq_raw, question_id, params, idx)
        except Exception as e:
            print(f"  Sub-generator {agent_id} failed: {e}", file=sys.stderr)
            result = None
        emit_stage(obs, agent_id, "llm_generate", "end")
        return result

    sq_results: dict[int, SubQuestion] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_generate_subquestion, sq_plan): sq_plan
            for sq_plan in sq_plans
        }
        for future in concurrent.futures.as_completed(futures):
            sq_plan = futures[future]
            idx = sq_plan.get("序號", sq_plans.index(sq_plan) + 1)
            result = future.result()
            if result is not None:
                sq_results[idx] = result

    question.subquestions = [sq_results[k] for k in sorted(sq_results)]
    _emit_question_update(on_question_update, question, "draft")

    chart_image_path: str | None = None
    if question.chart_spec:
        img_path = config.output_dir / f"{question_id}.png"
        print(f"  Rendering image: {img_path}", file=sys.stderr)
        emit_stage(obs, "image_agent", "render_image", "start")
        rendered = render_image(
            question.chart_spec.model_dump(),
            img_path,
            question_text="\n".join(question.題目),
            html_renderer=html_renderer,
            llm_client=client,
            image_generation_mode=image_generation_mode,
        )
        emit_stage(obs, "image_agent", "render_image", "end")
        if rendered:
            question.圖片 = f"{question_id}.png"
            chart_image_path = rendered
            _emit_question_update(on_question_update, question, "image")

    if not skip_verify:
        print(f"  Verifying question {question_id}...", file=sys.stderr)
        emit_stage(obs, "verifier", "verify", "start")
        result = verify_question(client, question, chart_image_path=chart_image_path)
        emit_stage(obs, "verifier", "verify", "end")
        question.verification = result
        _emit_question_update(on_question_update, question, "verified")
        status = "PASSED" if result.passed else "FAILED"
        print(f"  Verification {status}: {result.details[:100]}", file=sys.stderr)

    return question


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
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    on_question_update: QuestionUpdateCallback | None = None,
) -> ExamQuestion | str:
    """generate_one followed by up to max_retries correction passes."""
    question = generate_one(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        dry_run=dry_run,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        on_question_update=on_question_update,
    )

    if dry_run or not isinstance(question, ExamQuestion):
        return question

    obs = client.get_observer() if client else None

    for attempt in range(max_retries):
        if skip_verify or question.verification is None or question.verification.passed:
            break

        print(
            f"  Verification failed; applying correction "
            f"(attempt {attempt + 1}/{max_retries})...",
            file=sys.stderr,
        )

        prior_chart_spec = question.chart_spec.model_copy() if question.chart_spec else None

        chart_image_path: str | None = None
        if question.圖片:
            p = config.output_dir / question.圖片
            if p.exists():
                chart_image_path = str(p)

        emit_stage(obs, "corrector", "correct", "start", retry=attempt + 1)
        question = correct_question(
            client, question, question.verification, chart_image_path=chart_image_path
        )
        emit_stage(obs, "corrector", "correct", "end", retry=attempt + 1)
        _emit_question_update(on_question_update, question, "corrected")

        new_chart_image_path: str | None = None
        if question.chart_spec and question.chart_spec != prior_chart_spec:
            img_path = config.output_dir / f"{question_id}.png"
            print(f"  Chart spec changed; re-rendering image: {img_path}", file=sys.stderr)
            emit_stage(obs, "image_agent", "render_image", "start")
            rendered = render_image(
                question.chart_spec.model_dump(),
                img_path,
                question_text="\n".join(question.題目),
                html_renderer=html_renderer,
                llm_client=client,
                image_generation_mode=image_generation_mode,
            )
            emit_stage(obs, "image_agent", "render_image", "end")
            if rendered:
                question.圖片 = f"{question_id}.png"
                new_chart_image_path = rendered
                _emit_question_update(on_question_update, question, "image")
        elif question.圖片:
            p = config.output_dir / question.圖片
            new_chart_image_path = str(p) if p.exists() else None

        if not skip_verify:
            emit_stage(obs, "verifier", "verify", "start", retry=attempt + 1)
            result = verify_question(client, question, chart_image_path=new_chart_image_path)
            emit_stage(obs, "verifier", "verify", "end", retry=attempt + 1)
            question.verification = result
            _emit_question_update(on_question_update, question, "verified")
            status = "PASSED" if result.passed else "FAILED"
            print(f"  Re-verification {status}: {result.details[:100]}", file=sys.stderr)

    return question


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

    results = []
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
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)
            results.append(question)

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
