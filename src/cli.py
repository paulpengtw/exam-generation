"""CLI entry point for exam question generation."""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

from src.config import Config
from src.context_builder import build_system_prompt, build_user_prompt
from src.data_loader import (
    get_full_curriculum_text,
    get_full_performance_text,
    get_grade_content,
    load_curriculum,
    load_intro_text,
    load_performance_standards,
)
from src.llm_client import LLMClient
from src.renderer import render_chart
from src.sampler import sample_params
from src.schemas import (
    ChartSpec,
    ExamQuestion,
    LearningContentItem,
    QuestionContext,
    QuestionMetadata,
    QuestionSetType,
    QuestionStyle,
    QuestionType,
    SampledParams,
)
from src.verifier import verify_question


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="exam-generation",
        description="Generate Taiwan junior high school math exam questions using LLMs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate exam questions")
    gen.add_argument("--grade", type=int, choices=[7, 8, 9], help="Target grade level")
    gen.add_argument(
        "--style",
        type=str,
        choices=[s.value for s in QuestionStyle],
        help="Question visual style",
    )
    gen.add_argument("--context", type=str, help="情境 (e.g. 個人, 社會時事)")
    gen.add_argument("--set-type", type=str, help="題型種類 (單一題 or 題組題)")
    gen.add_argument("--q-type", type=str, help="題型 (選擇題, 是非題, etc.)")
    gen.add_argument("--count", type=int, default=1, help="Number of questions to generate")
    gen.add_argument("--batch", action="store_true", help="Output as single JSON array")
    gen.add_argument("--seed", type=int, help="Random seed for reproducibility")
    gen.add_argument("--no-verify", action="store_true", help="Skip verification pass")
    gen.add_argument("--output", type=str, help="Output directory")
    gen.add_argument("--dry-run", action="store_true", help="Show prompt without calling LLM")
    gen.add_argument("--env-file", type=str, help="Path to .env file")

    return parser.parse_args(argv)


def _resolve_enum(value: str | None, enum_cls: type) -> object | None:
    """Resolve a string to an enum value, or return None."""
    if value is None:
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    raise ValueError(f"Invalid value '{value}' for {enum_cls.__name__}")


def generate_one(
    config: Config,
    client: LLMClient | None,
    curriculum: list[dict],
    performance: dict,
    intro_text: str,
    grade_content: dict[int, list[LearningContentItem]],
    params: SampledParams,
    question_id: str,
    dry_run: bool = False,
    skip_verify: bool = False,
) -> ExamQuestion | str:
    """Generate a single exam question.

    Returns ExamQuestion on success, or the prompt string if dry_run=True.
    """
    # Build prompts
    curriculum_text = get_full_curriculum_text(curriculum)
    performance_text = get_full_performance_text(performance)

    system_prompt = build_system_prompt(curriculum_text, performance_text, intro_text)
    user_prompt = build_user_prompt(params, config.data_dir / "few_shot")

    if dry_run:
        return f"=== SYSTEM PROMPT ({len(system_prompt)} chars) ===\n{system_prompt[:2000]}...\n\n=== USER PROMPT ({len(user_prompt)} chars) ===\n{user_prompt}"

    # Generate question via LLM
    print(f"  Generating question {question_id}...", file=sys.stderr)
    raw_json = client.generate_json(system_prompt, user_prompt)

    # Parse into ExamQuestion
    question = _parse_question(raw_json, question_id, params, config.model_execute)

    # Verify if requested
    if not skip_verify:
        print(f"  Verifying question {question_id}...", file=sys.stderr)
        result = verify_question(client, question)
        question.verification = result
        status = "PASSED" if result.passed else "FAILED"
        print(f"  Verification {status}: {result.details[:100]}", file=sys.stderr)

    return question


def _parse_question(
    raw: dict,
    question_id: str,
    params: SampledParams,
    model: str,
) -> ExamQuestion:
    """Parse raw LLM JSON output into an ExamQuestion."""
    # Handle 學習內容 which may come as strings or dicts
    raw_content = raw.get("學習內容", [])
    parsed_content = []
    for item in raw_content:
        if isinstance(item, dict):
            parsed_content.append(LearningContentItem(
                編碼=item.get("編碼", ""),
                說明=item.get("說明", item.get("學習內容條目及說明", "")),
            ))
        elif isinstance(item, str):
            parts = item.split("：", 1)
            parsed_content.append(LearningContentItem(
                編碼=parts[0].strip() if len(parts) > 1 else "",
                說明=parts[1].strip() if len(parts) > 1 else item,
            ))

    # Handle 數學思考
    raw_thinking = raw.get("數學思考", [])

    # Handle chart_spec
    chart_spec = None
    if "chart_spec" in raw and raw["chart_spec"]:
        try:
            chart_spec = ChartSpec(**raw["chart_spec"])
        except Exception:
            chart_spec = ChartSpec(
                chart_type=raw["chart_spec"].get("chart_type", "geometry"),
                data=raw["chart_spec"].get("data", {}),
                labels=raw["chart_spec"].get("labels", {}),
                title=raw["chart_spec"].get("title", ""),
                description=raw["chart_spec"].get("description", ""),
            )

    return ExamQuestion(
        id=question_id,
        情境=raw.get("情境", params.情境.value),
        題型種類=raw.get("題型種類", params.題型種類.value),
        題型=raw.get("題型", params.題型.value),
        數學思考=raw_thinking,
        學習內容=parsed_content,
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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.command != "generate":
        return

    # Load config
    config = Config.from_env(args.env_file)
    if args.output:
        config.output_dir = Path(args.output)

    if not args.dry_run:
        config.validate()

    # Ensure output dir exists
    config.output_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    curriculum = load_curriculum(config.data_dir / "curriculum" / "學習內容.json")
    performance = load_performance_standards(config.data_dir / "curriculum" / "學習表現.json")
    intro_text = load_intro_text(Path("Introduction to \"學習表現\" and \"學習階段\".md"))

    # Build grade content index
    grade_content = {g: get_grade_content(curriculum, g) for g in (7, 8, 9)}

    # Initialize LLM client (skip for dry-run)
    client = None if args.dry_run else LLMClient(config)

    # Resolve optional overrides
    style_override = QuestionStyle(args.style) if args.style else None
    context_override = _resolve_enum(args.context, QuestionContext)
    set_type_override = _resolve_enum(args.set_type, QuestionSetType)
    q_type_override = _resolve_enum(args.q_type, QuestionType)

    # Generate questions
    results = []
    base_seed = args.seed
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for i in range(args.count):
        seed = (base_seed + i) if base_seed is not None else None
        rng = random.Random(seed)

        params = sample_params(
            grade_content=grade_content,
            grade=args.grade,
            style=style_override,
            context=context_override,
            set_type=set_type_override,
            q_type=q_type_override,
            seed=seed,
        )

        question_id = f"q_{timestamp}_{i+1:03d}"

        print(f"\n[{i+1}/{args.count}] Sampled: grade={params.grade}, "
              f"style={params.style.value}, 情境={params.情境.value}, "
              f"題型={params.題型.value}", file=sys.stderr)
        print(f"  學習內容: {', '.join(c.編碼 for c in params.學習內容)}", file=sys.stderr)

        result = generate_one(
            config=config,
            client=client,
            curriculum=curriculum,
            performance=performance,
            intro_text=intro_text,
            grade_content=grade_content,
            params=params,
            question_id=question_id,
            dry_run=args.dry_run,
            skip_verify=args.no_verify,
        )

        if args.dry_run:
            print(result)
            return

        question = result
        assert isinstance(question, ExamQuestion)

        # Render chart if needed
        if question.chart_spec:
            img_path = config.output_dir / f"{question_id}.png"
            print(f"  Rendering chart: {img_path}", file=sys.stderr)
            rendered = render_chart(question.chart_spec.model_dump(), img_path)
            if rendered:
                question.圖片 = f"{question_id}.png"

        results.append(question)

        # Write individual JSON (unless batch mode)
        if not args.batch:
            out_path = config.output_dir / f"{question_id}.json"
            out_path.write_text(
                question.model_dump_json(indent=2, exclude_none=True),
                encoding="utf-8",
            )
            print(f"  Saved: {out_path}", file=sys.stderr)

    # Batch output
    if args.batch and results:
        batch_path = config.output_dir / f"batch_{timestamp}.json"
        batch_data = [json.loads(q.model_dump_json(exclude_none=True)) for q in results]
        batch_path.write_text(
            json.dumps(batch_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nBatch saved: {batch_path}", file=sys.stderr)

    print(f"\nDone. Generated {len(results)} question(s).", file=sys.stderr)


if __name__ == "__main__":
    main()
