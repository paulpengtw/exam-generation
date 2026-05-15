"""CLI entry point for social studies (PISA reading literacy) exam question generation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from src.config import Config
from src.html_renderer import PlaywrightRenderer
from src.llm_client import LLMClient
from src.renderer import render_image
from src.social_studies.context_builder import build_system_prompt, build_user_prompt
from src.social_studies.corrector import correct_question
from src.social_studies.data_loader import load_few_shot_examples  # noqa: F401
from src.social_studies.sampler import sample_params
from src.social_studies.schema_loader import load_grades, load_schemas
from src.social_studies.schemas import (
    ExamQuestion,
    ImageSpec,
    QuestionContext,
    QuestionMetadata,
    QuestionSetType,
    QuestionStyle,
    QuestionType,
    SampledParams,
)
from src.social_studies.verifier import verify_question

_GRADES: list[int] = load_grades(load_schemas())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="social-studies-exam-generation",
        description="Generate PISA-style reading literacy exam questions using LLMs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate exam questions")
    gen.add_argument("--grade", type=int, choices=_GRADES, help="Target grade level")
    gen.add_argument(
        "--style",
        type=str,
        nargs="+",
        choices=[s.value for s in QuestionStyle],  # type: ignore[attr-defined]
        help="Question style(s) — randomly picked from given values if multiple",
    )
    gen.add_argument("--context", type=str, nargs="+", help="情境 (e.g. 個人 公共)")
    gen.add_argument("--set-type", type=str, help="題型種類 (always 題組題 for PISA)")
    gen.add_argument("--q-type", type=str, nargs="+", help="題型 (one or more values)")
    gen.add_argument("--count", type=int, default=1, help="Number of question sets to generate")
    gen.add_argument("--batch", action="store_true", help="Output as single JSON array")
    gen.add_argument("--seed", type=int, help="Random seed for reproducibility")
    gen.add_argument("--no-verify", action="store_true", help="Skip verification pass")
    gen.add_argument("--max-retries", type=int, default=None,
                     help="Max retries when verification fails (default: LLM_MAX_RETRIES env, fallback 3)")
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
    """Parse raw LLM JSON output into a social-studies ExamQuestion."""
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
        情境=raw.get("情境", [c.value for c in params.情境]),
        題型種類=raw.get("題型種類", params.題型種類.value),
        題型=raw.get("題型", params.題型.value),
        閱讀歷程=raw.get("閱讀歷程", [p.value for p in params.閱讀歷程]),
        文本形式=raw.get("文本形式", params.文本形式.value),
        題目=raw.get("題目", []),
        正確解題分析=raw.get("正確解題分析", []),
        chart_spec=chart_spec,
        metadata=QuestionMetadata(
            grade=params.grade,
            style=params.style,
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
    html_renderer: PlaywrightRenderer | None = None,
) -> ExamQuestion | str:
    """Generate a single PISA reading question set."""
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(params, config.data_dir / "social_studies" / "few_shot")

    if dry_run:
        return (
            f"=== SYSTEM PROMPT ({len(system_prompt)} chars) ===\n{system_prompt[:2000]}...\n\n"
            f"=== USER PROMPT ({len(user_prompt)} chars) ===\n{user_prompt}"
        )

    print(f"  Generating question {question_id}...", file=sys.stderr)
    raw_json = client.generate_json(system_prompt, user_prompt)

    question = _parse_question(raw_json, question_id, params, config.model_execute)

    chart_image_path: str | None = None
    if question.chart_spec:
        img_path = config.output_dir / f"{question_id}.png"
        print(f"  Rendering image: {img_path}", file=sys.stderr)
        rendered = render_image(
            question.chart_spec.model_dump(),
            img_path,
            question_text="\n".join(question.題目),
            html_renderer=html_renderer,
            llm_client=client,
        )
        if rendered:
            question.圖片 = f"{question_id}.png"
            chart_image_path = rendered

    if not skip_verify:
        print(f"  Verifying question {question_id}...", file=sys.stderr)
        result = verify_question(client, question, chart_image_path=chart_image_path)
        question.verification = result
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
    html_renderer: PlaywrightRenderer | None = None,
    dry_run: bool = False,
) -> ExamQuestion | str:
    """generate_one followed by up to max_retries correction passes."""
    question = generate_one(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        dry_run=dry_run,
        skip_verify=skip_verify,
        html_renderer=html_renderer,
    )

    if dry_run or not isinstance(question, ExamQuestion):
        return question

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

        question = correct_question(client, question, question.verification,
                                    chart_image_path=chart_image_path)

        new_chart_image_path: str | None = None
        if question.chart_spec and question.chart_spec != prior_chart_spec:
            img_path = config.output_dir / f"{question_id}.png"
            print(f"  Chart spec changed; re-rendering image: {img_path}", file=sys.stderr)
            rendered = render_image(
                question.chart_spec.model_dump(),
                img_path,
                question_text="\n".join(question.題目),
                html_renderer=html_renderer,
                llm_client=client,
            )
            if rendered:
                question.圖片 = f"{question_id}.png"
                new_chart_image_path = rendered
        elif question.圖片:
            p = config.output_dir / question.圖片
            new_chart_image_path = str(p) if p.exists() else None

        if not skip_verify:
            result = verify_question(client, question, chart_image_path=new_chart_image_path)
            question.verification = result
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

    html_renderer = None
    if not args.dry_run:
        try:
            html_renderer = PlaywrightRenderer()
            html_renderer.start()
            print("  Playwright browser started.", file=sys.stderr)
        except Exception as e:
            print(f"  Warning: Playwright unavailable ({e}). HTML images will be skipped.", file=sys.stderr)

    style_override = [QuestionStyle(v) for v in args.style] if args.style else None
    context_override = (
        [_resolve_enum(v, QuestionContext) for v in args.context]
        if args.context else None
    )
    set_type_override = _resolve_enum(args.set_type, QuestionSetType)
    q_type_override = [_resolve_enum(v, QuestionType) for v in args.q_type] if args.q_type else None

    results = []
    base_seed = args.seed
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
            question_id = f"ss_{timestamp}_{i+1:03d}"

            params = sample_params(
                grade=args.grade,
                style=style_override,
                context=context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                seed=seed,
            )

            print(f"\n[{i+1}/{args.count}] Sampled: grade={params.grade}, "
                  f"style={params.style.value}, 情境={'、'.join(c.value for c in params.情境)}, "
                  f"題型={params.題型.value}, 閱讀歷程={'、'.join(p.value for p in params.閱讀歷程)}, "
                  f"文本形式={params.文本形式.value}", file=sys.stderr)

            result = generate_with_corrections(
                config=config,
                client=client,
                params=params,
                question_id=question_id,
                max_retries=max_retries,
                skip_verify=args.no_verify,
                html_renderer=html_renderer,
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
