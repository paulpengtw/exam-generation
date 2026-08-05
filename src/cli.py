"""CLI entry point for exam question generation."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from random import Random
from typing import Any

from src.common.batch_dedup import PriorScope, extract_math_prior_scope
from src.common.generation_core import generate_one_core, generate_with_corrections_core
from src.common.subject_spec import SubjectGenerationSpec
from src.config import Config
from src.corrector import correct_question
from src.curriculum_context import CurriculumContext, load_curriculum_context
from src.schema_loader import load_grades, load_schemas

_GRADES: list[int] = load_grades(load_schemas())

from src.context_builder import (
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_system_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
    build_user_prompt,
)
from src.data_loader import (
    get_grade_content,
    load_curriculum,
    load_intro_text,
    load_performance_standards,
)
from src.html_renderer import PlaywrightRenderer
from src.llm_client import LLMClient, emit_stage, make_render_error_sink, make_stderr_observer
from src.renderer import render_image
from src.sampler import grade_to_learning_stage, sample_params
from src.schemas import (
    CoreCompetency,
    ImageSpec,
    ExamQuestion,
    LearningContentItem,
    QuestionContext,
    QuestionMetadata,
    QuestionSetType,
    QuestionStyle,
    QuestionSubject,
    QuestionType,
    SampledParams,
    SubQuestion,
)
from src.verifier import verify_question

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
        prog="exam-generation",
        description="Generate Taiwan junior high school math exam questions using LLMs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate exam questions")
    gen.add_argument("--grade", type=int, choices=_GRADES, help="Target grade level")
    gen.add_argument(
        "--style",
        type=str,
        nargs="+",
        choices=[s.value for s in QuestionStyle],  # type: ignore[attr-defined]
        help="Question visual style(s) — randomly picked from given values if multiple",
    )
    gen.add_argument("--context", type=str, nargs="+", help="情境 (e.g. 個人 社會時事) — one or more values")
    gen.add_argument("--set-type", type=str, help="題型種類 (單一題 or 題組題)")
    gen.add_argument("--q-type", type=str, nargs="+", help="題型 (one or more of: 選擇題, 是非題, etc.) — randomly picked if multiple")
    gen.add_argument(
        "--subject-filter",
        type=str,
        choices=[s.value for s in QuestionSubject],
        help="科目焦點（數與量 / 代數 / 幾何 / 統計與機率 / 跨領域）",
    )
    gen.add_argument(
        "--core-competency",
        type=str,
        nargs="+",
        choices=[c.value for c in CoreCompetency],  # type: ignore[attr-defined]
        help="核心素養代號 pool（如 數-J-A2 數-J-C3）；多值時隨機選 1-3 個",
    )
    gen.add_argument(
        "--learning-content",
        type=str,
        nargs="+",
        help="指定學習內容 編碼（覆蓋隨機取樣）",
    )
    gen.add_argument(
        "--learning-performance",
        type=str,
        nargs="+",
        help="指定學習表現 編碼（覆蓋隨機取樣）",
    )
    gen.add_argument(
        "--content-type",
        type=str,
        choices=["純文字", "含圖片", "graphs/charts/tables", "customized"],
        help="題目內容類型",
    )
    gen.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        default=None,
        help="題目難度（easy / medium / hard；預設 medium，純粹傳遞不參與隨機抽樣）",
    )
    gen.add_argument(
        "--image-generation-mode",
        choices=["html", "gpt_image"],
        default="html",
        help="Image creation mode for HTML image specs",
    )
    gen.add_argument("--topic", type=str, help="使用者指定主題／議題")
    gen.add_argument("--passage", type=str, help="使用者指定題幹文字（逐字使用）")
    gen.add_argument("--options", type=str, nargs="+", help="使用者指定選項（依序使用）")
    gen.add_argument("--core-question", type=str, help="使用者指定核心問題")
    gen.add_argument("--count", type=int, default=1, help="Number of questions to generate")
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
    """Resolve a string to an enum value, or return None."""
    if value is None:
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    raise ValueError(f"Invalid value '{value}' for {enum_cls.__name__}")


def _parse_math_learning_items(
    raw_items: object,
    fallback: list[LearningContentItem],
) -> list[LearningContentItem]:
    """Parse a math 小題's curriculum references, falling back to sampled values."""
    if not isinstance(raw_items, list):
        return list(fallback)
    parsed: list[LearningContentItem] = []
    for item in raw_items:
        if isinstance(item, dict):
            parsed.append(
                LearningContentItem(
                    編碼=str(item.get("編碼", "")),
                    說明=str(item.get("說明", "")),
                )
            )
        elif isinstance(item, str):
            parts = item.split("：", 1)
            parsed.append(
                LearningContentItem(
                    編碼=parts[0].strip() if len(parts) > 1 else item,
                    說明=parts[1].strip() if len(parts) > 1 else "",
                )
            )
    return parsed or list(fallback)


def _parse_math_text_shell(
    raw: dict,
    question_id: str,
    params: SampledParams,
    model: str,
) -> ExamQuestion:
    """Parse 文本生成器 output into a math 題組 shell."""
    question = _parse_question(raw, question_id, params, model)
    return question.model_copy(
        update={
            "核心問題": raw.get("核心問題", ""),
            "文本": raw.get("文本", ""),
            "取材來源": raw.get("取材來源", []),
            "subquestions": [],
        },
    )


def _parse_math_subquestion(
    sq_raw: dict,
    question_id: str,
    params: SampledParams,
    idx: int,
) -> SubQuestion | None:
    """Parse one complete math 小題 from a 子題產生器 response."""
    if not isinstance(sq_raw, dict):
        return None
    try:
        raw_distractor = sq_raw.get("誘答分析", {})
        distractor = (
            {str(key): str(value) for key, value in raw_distractor.items()}
            if isinstance(raw_distractor, dict)
            else {}
        )
        return SubQuestion(
            id=sq_raw.get("id", f"{question_id}-{idx:02d}"),
            序號=sq_raw.get("序號", idx),
            年級=params.grade,
            題型=sq_raw.get("題型", params.題型.value),
            題目=sq_raw.get("題目", ""),
            答案=sq_raw.get("答案", ""),
            答案解析=sq_raw.get("答案解析", ""),
            誘答分析=distractor,
            學習內容=_parse_math_learning_items(sq_raw.get("學習內容"), params.學習內容),
            學習表現=_parse_math_learning_items(sq_raw.get("學習表現"), params.學習表現),
            出題概念=sq_raw.get("出題概念", ""),
        )
    except Exception:
        return None


def _make_math_fallback_sq_plans(params: SampledParams, n: int) -> list[dict]:
    """Create fallback 小題 plans for the shared 強制值 count guarantee."""
    return [
        {"序號": i, "題型": params.題型.value, "出題概念": ""}
        for i in range(1, n + 1)
    ]


def _with_text_word_limit(
    params: SampledParams,
    text_word_limit: int | None,
) -> SampledParams:
    if text_word_limit is None:
        return params
    return params.model_copy(update={"text_word_limit": text_word_limit})


def _math_build_text_system(params: SampledParams) -> tuple[str, dict]:
    learning_stage = grade_to_learning_stage(params.grade)
    return build_text_system_prompt(learning_stage=learning_stage), {
        "learning_stage": learning_stage,
    }


def _math_build_text_user(
    params: SampledParams,
    few_shot_dir: Path,
    user_passage: str | None,
    user_options: list[str] | None,
    user_topic: str | None,
    user_core_question: str | None,
    image_generation_mode: str,
    disable_reference_fewshot: bool,
    prior_scopes: Sequence[PriorScope] | None,
) -> tuple[str, list[Path]]:
    return build_text_user_prompt(
        params,
        few_shot_dir,
        rng=Random(params.seed),
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        disable_reference_fewshot=disable_reference_fewshot,
        prior_scopes=prior_scopes,
        text_word_limit=params.text_word_limit,
    )


def _math_build_subquestion_system(stage_ctx: dict) -> str:
    return build_subquestion_system_prompt(learning_stage=stage_ctx["learning_stage"])


def _math_build_subquestion_user(
    text_raw: dict,
    params: SampledParams,
    few_shot_dir: Path,
    sq_plan: dict,
    slot_cfg: object | None,
    image_generation_mode: str,
    disable_reference_fewshot: bool,
) -> tuple[str, list[Path]]:
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
    )


_MATH_SPEC = SubjectGenerationSpec(
    few_shot_subdir="",
    build_text_system_fn=_math_build_text_system,
    build_text_user_fn=_math_build_text_user,
    build_subquestion_system_fn=_math_build_subquestion_system,
    build_subquestion_user_fn=_math_build_subquestion_user,
    parse_text_shell_fn=_parse_math_text_shell,
    parse_subquestion_fn=_parse_math_subquestion,
    make_fallback_sq_plans_fn=_make_math_fallback_sq_plans,
    ensure_visual_spec_fn=None,
    render_subquestion_images_fn=None,
    image_question_text_fn=lambda question: "\n".join(question.題目) or question.文本,
    verify_fn=verify_question,
    correct_fn=correct_question,
)


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
    disable_reference_fewshot: bool = False,
    html_renderer: PlaywrightRenderer | None = None,
    image_generation_mode: str = "html",
    user_topic: str = "",
    user_passage: str = "",
    text_word_limit: int | None = None,
    user_options: list[str] | None = None,
    user_core_question: str = "",
    on_question_update: QuestionUpdateCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
    curriculum_context: CurriculumContext | None = None,
) -> ExamQuestion | str:
    """Generate a single exam question.

    Returns ExamQuestion on success, or the prompt string if dry_run=True.

    Args:
        curriculum_context: When supplied, used as the canonical curriculum corpus
            for the generator system prompt and threaded through to the verifier.
            When ``None``, ``build_system_prompt`` falls back to its own
            module-level math corpus defaults.
    """
    params = _with_text_word_limit(params, text_word_limit)
    if params.sub_question_count is not None:
        return generate_one_core(
            config=config,
            client=client,
            params=params,
            question_id=question_id,
            spec=_MATH_SPEC,
            dry_run=dry_run,
            skip_verify=skip_verify,
            disable_reference_fewshot=disable_reference_fewshot,
            html_renderer=html_renderer,
            image_generation_mode=image_generation_mode,
            user_passage=user_passage or None,
            user_options=user_options,
            user_topic=user_topic or None,
            user_core_question=user_core_question or None,
            on_question_update=on_question_update,
            sub_client_factory=sub_client_factory,
            prior_scopes=prior_scopes,
            curriculum_context=curriculum_context,
        )

    # Build prompts using the canonical math curriculum corpus.
    # The legacy ``curriculum`` / ``performance`` / ``intro_text`` positional
    # params are retained for backward compat (grade_content derivation) but
    # are no longer injected into the system prompt.
    system_prompt, user_prompt, few_shot_images = build_generation_prompts(
        config,
        params,
        user_topic=user_topic,
        user_passage=user_passage,
        text_word_limit=text_word_limit,
        user_options=user_options,
        user_core_question=user_core_question,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
    )

    if dry_run:
        img_note = f" ({len(few_shot_images)} few-shot images)" if few_shot_images else ""
        return (
            f"=== SYSTEM PROMPT ({len(system_prompt)} chars) ===\n{system_prompt[:2000]}...\n\n"
            f"=== USER PROMPT ({len(user_prompt)} chars{img_note}) ===\n{user_prompt}"
        )

    obs = client.get_observer() if client else None

    # Generate question via LLM
    print(f"  Generating question {question_id}...", file=sys.stderr)
    emit_stage(obs, "generator", "llm_generate", "start")
    raw_json = client.generate_json(system_prompt, user_prompt)
    emit_stage(obs, "generator", "llm_generate", "end")

    # Parse into ExamQuestion
    question = _parse_question(raw_json, question_id, params, config.model_execute)
    _emit_question_update(on_question_update, question, "draft")

    # Render image before verification so verifier can see the PNG
    chart_image_path: str | None = None
    if question.chart_spec:
        img_path = config.output_dir / f"{question_id}.png"
        print(f"  Rendering image: {img_path}", file=sys.stderr)
        question_text = "\n".join(question.題目)
        _on_render_error, _render_failed = make_render_error_sink(obs)
        emit_stage(obs, "image_agent", "render_image", "start")
        rendered = render_image(
            question.chart_spec.model_dump(),
            img_path,
            question_text=question_text,
            html_renderer=html_renderer,
            llm_client=client,
            image_generation_mode=image_generation_mode,
            on_error=_on_render_error,
        )
        if not _render_failed:
            emit_stage(obs, "image_agent", "render_image", "end")
        if rendered:
            question.圖片 = f"{question_id}.png"
            chart_image_path = rendered
            _emit_question_update(on_question_update, question, "image")

    # Verify if requested
    if not skip_verify:
        print(f"  Verifying question {question_id}...", file=sys.stderr)
        emit_stage(obs, "verifier", "verify", "start")
        result = verify_question(
            client,
            question,
            chart_image_path=chart_image_path,
            curriculum_context=curriculum_context,
        )
        emit_stage(obs, "verifier", "verify", "end")
        question.verification = result
        _emit_question_update(on_question_update, question, "verified")
        status = "PASSED" if result.passed else "FAILED"
        print(f"  Verification {status}: {result.details[:100]}", file=sys.stderr)

    return question


def build_generation_prompts(
    config: Config,
    params: SampledParams,
    *,
    user_topic: str = "",
    user_passage: str = "",
    text_word_limit: int | None = None,
    user_options: list[str] | None = None,
    user_core_question: str = "",
    prior_scopes: Sequence[PriorScope] | None = None,
    curriculum_context: CurriculumContext | None = None,
    disable_reference_fewshot: bool = False,
) -> tuple[str, str, list[str]]:
    """Build the exact prompts used by math's first model call."""
    params = _with_text_word_limit(params, text_word_limit)
    if params.sub_question_count is not None:
        learning_stage = grade_to_learning_stage(params.grade)
        system_prompt = build_text_system_prompt(learning_stage=learning_stage)
        user_prompt, few_shot_images = build_text_user_prompt(
            params,
            config.data_dir / "few_shot",
            rng=Random(params.seed),
            user_passage=user_passage,
            user_options=user_options,
            user_topic=user_topic,
            user_core_question=user_core_question,
            disable_reference_fewshot=disable_reference_fewshot,
            prior_scopes=prior_scopes,
        )
        return system_prompt, user_prompt, few_shot_images

    system_prompt = build_system_prompt(curriculum_context=curriculum_context)
    user_prompt, few_shot_images = build_user_prompt(
        params,
        config.data_dir / "few_shot",
        rng=Random(params.seed),
        user_topic=user_topic,
        user_passage=user_passage,
        user_options=user_options,
        user_core_question=user_core_question,
        prior_scopes=prior_scopes,
    )
    return system_prompt, user_prompt, few_shot_images


def generate_with_corrections(
    config: Config,
    client: LLMClient | None,
    curriculum: list[dict],
    performance: dict,
    intro_text: str,
    grade_content: dict[int, list[LearningContentItem]],
    params: SampledParams,
    question_id: str,
    max_retries: int = 3,
    skip_verify: bool = False,
    disable_reference_fewshot: bool = False,
    html_renderer: PlaywrightRenderer | None = None,
    dry_run: bool = False,
    image_generation_mode: str = "html",
    user_topic: str = "",
    user_passage: str = "",
    text_word_limit: int | None = None,
    user_options: list[str] | None = None,
    user_core_question: str = "",
    on_question_update: QuestionUpdateCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
    curriculum_context: CurriculumContext | None = None,
) -> ExamQuestion | str:
    """generate_one followed by up to max_retries correction passes.

    On each failed verification, sends the question + verifier details back to
    the LLM to produce a minimal targeted fix rather than regenerating from scratch.
    Image is only re-rendered when chart_spec actually changes.

    Args:
        curriculum_context: The canonical curriculum corpus for this run.
            Threaded into the generator, verifier, and corrector so all three
            see the same curriculum section.  When ``None``, each component
            falls back to its own defaults.
    """
    params = _with_text_word_limit(params, text_word_limit)
    if params.sub_question_count is not None:
        return generate_with_corrections_core(
            config=config,
            client=client,
            params=params,
            question_id=question_id,
            spec=_MATH_SPEC,
            max_retries=max_retries,
            skip_verify=skip_verify,
            disable_reference_fewshot=disable_reference_fewshot,
            html_renderer=html_renderer,
            image_generation_mode=image_generation_mode,
            dry_run=dry_run,
            user_passage=user_passage or None,
            user_options=user_options,
            user_topic=user_topic or None,
            user_core_question=user_core_question or None,
            on_question_update=on_question_update,
            sub_client_factory=sub_client_factory,
            prior_scopes=prior_scopes,
            curriculum_context=curriculum_context,
        )

    question = generate_one(
        config=config,
        client=client,
        curriculum=curriculum,
        performance=performance,
        intro_text=intro_text,
        grade_content=grade_content,
        params=params,
        question_id=question_id,
        dry_run=dry_run,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_topic=user_topic,
        user_passage=user_passage,
        text_word_limit=text_word_limit,
        user_options=user_options,
        user_core_question=user_core_question,
        on_question_update=on_question_update,
        sub_client_factory=sub_client_factory,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
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

        # Resolve current PNG path for multimodal corrector
        chart_image_path: str | None = None
        if question.圖片:
            p = config.output_dir / question.圖片
            if p.exists():
                chart_image_path = str(p)

        emit_stage(obs, "corrector", "correct", "start", retry=attempt + 1)
        question = correct_question(
            client, question, question.verification,
            chart_image_path=chart_image_path,
            curriculum_context=curriculum_context,
        )
        emit_stage(obs, "corrector", "correct", "end", retry=attempt + 1)
        _emit_question_update(on_question_update, question, "corrected")

        # Re-render only when chart_spec actually changed
        new_chart_image_path: str | None = None
        if question.chart_spec and question.chart_spec != prior_chart_spec:
            img_path = config.output_dir / f"{question_id}.png"
            print(f"  Chart spec changed; re-rendering image: {img_path}", file=sys.stderr)
            _on_render_error, _render_failed = make_render_error_sink(obs)
            emit_stage(obs, "image_agent", "render_image", "start")
            rendered = render_image(
                question.chart_spec.model_dump(),
                img_path,
                question_text="\n".join(question.題目),
                html_renderer=html_renderer,
                llm_client=client,
                image_generation_mode=image_generation_mode,
                on_error=_on_render_error,
            )
            if not _render_failed:
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
            result = verify_question(
                client, question,
                chart_image_path=new_chart_image_path,
                curriculum_context=curriculum_context,
            )
            emit_stage(obs, "verifier", "verify", "end", retry=attempt + 1)
            question.verification = result
            _emit_question_update(on_question_update, question, "verified")
            status = "PASSED" if result.passed else "FAILED"
            print(
                f"  Re-verification {status}: {result.details[:100]}",
                file=sys.stderr,
            )

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

    # Handle image_spec (new) or chart_spec (legacy field name) from LLM output
    chart_spec = None
    raw_spec = raw.get("image_spec") or raw.get("chart_spec")
    if raw_spec:
        try:
            chart_spec = ImageSpec(**raw_spec)
        except Exception:
            # Fallback: infer render_mode from presence of chart_type
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

    # Parse new curriculum fields (Phase 3)
    raw_lp = raw.get("學習表現", [])
    parsed_lp: list[LearningContentItem] = []
    for item in raw_lp:
        if isinstance(item, dict):
            parsed_lp.append(LearningContentItem(
                編碼=item.get("編碼", ""),
                說明=item.get("說明", ""),
            ))
        elif isinstance(item, str):
            parts = item.split("：", 1)
            parsed_lp.append(LearningContentItem(
                編碼=parts[0].strip() if len(parts) > 1 else item,
                說明=parts[1].strip() if len(parts) > 1 else "",
            ))
    if not parsed_lp:
        parsed_lp = list(params.學習表現)

    raw_cc = raw.get("核心素養", [])
    if isinstance(raw_cc, list) and raw_cc:
        core_competencies = [str(c) for c in raw_cc]
    else:
        core_competencies = list(params.核心素養)

    raw_distractor = raw.get("誘答分析", {})
    if isinstance(raw_distractor, dict):
        distractor = {str(k): str(v) for k, v in raw_distractor.items()}
    else:
        distractor = {}

    return ExamQuestion(
        id=question_id,
        情境=raw.get("情境", [c.value for c in params.情境]),
        題型種類=raw.get("題型種類", params.題型種類.value),
        題型=raw.get("題型", params.題型.value),
        數學思考=raw_thinking,
        學習內容=parsed_content,
        題目=raw.get("題目", []),
        正確解題分析=raw.get("正確解題分析", []),
        chart_spec=chart_spec,
        核心素養=core_competencies,
        學習表現=parsed_lp,
        題目內容類型=raw.get("題目內容類型", params.題目內容類型),
        出題概念=raw.get("出題概念", ""),
        誘答分析=distractor,
        metadata=QuestionMetadata(
            grade=params.grade,
            style=params.style,
            model=model,
            seed=None,
            difficulty=params.difficulty,
        ),
    )



def _start_html_renderer(client: "LLMClient | None") -> "PlaywrightRenderer | None":
    """Start Playwright renderer; emit an error stage event on failure.

    Returns the started renderer on success, or None on failure.
    The stderr warning and None-renderer non-fatal behavior are preserved.
    """
    try:
        renderer = PlaywrightRenderer()
        renderer.start()
        print("  Playwright browser started.", file=sys.stderr)
        return renderer
    except Exception as e:
        print(
            f"  Warning: Playwright unavailable ({e}). HTML images will be skipped.",
            file=sys.stderr,
        )
        if client is not None:
            emit_stage(
                client.get_observer(),
                "image_agent",
                "renderer_startup",
                "error",
                message=str(e),
            )
        return None


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

    # Build grade content index (still uses the legacy per-grade sampler source)
    grade_content = {g: get_grade_content(curriculum, g) for g in _GRADES}

    # Build the canonical curriculum context once; all pipeline stages share it.
    math_curriculum_context = load_curriculum_context()

    # Initialize LLM client (skip for dry-run)
    client = None if args.dry_run else LLMClient(config)
    if client is not None:
        client.set_observer(make_stderr_observer(truncate=config.log_truncate))

    # Initialize Playwright renderer (skip for dry-run)
    # Started once here and reused across all questions to amortize ~1-2s startup cost
    html_renderer = _start_html_renderer(client) if not args.dry_run else None

    # Resolve optional overrides
    style_override = [QuestionStyle(v) for v in args.style] if args.style else None
    context_override = (
        [_resolve_enum(v, QuestionContext) for v in args.context]
        if args.context else None
    )
    set_type_override = _resolve_enum(args.set_type, QuestionSetType)
    q_type_override = [_resolve_enum(v, QuestionType) for v in args.q_type] if args.q_type else None
    core_competency_override = (
        [CoreCompetency(v) for v in args.core_competency]
        if args.core_competency else None
    )
    learning_content_override = args.learning_content if args.learning_content else None
    learning_performance_override = args.learning_performance if args.learning_performance else None
    content_type_override = args.content_type if args.content_type else None
    subject_filter_override = args.subject_filter if args.subject_filter else None

    # Generate questions
    results = []
    prior_scopes: list[PriorScope] = []
    base_seed = args.seed
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
            question_id = f"q_{timestamp}_{i+1:03d}"

            params = sample_params(
                grade_content=grade_content,
                grade=args.grade,
                style=style_override,
                context=context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                seed=seed,
                core_competency=core_competency_override,
                learning_content=learning_content_override,
                learning_performance=learning_performance_override,
                content_type=content_type_override,
                subject_filter=subject_filter_override,
                difficulty=args.difficulty,
            )

            print(f"\n[{i+1}/{args.count}] Sampled: grade={params.grade}, "
                  f"style={params.style.value}, 情境={'、'.join(c.value for c in params.情境)}, "
                  f"題型={params.題型.value}", file=sys.stderr)
            print(f"  學習內容: {', '.join(c.編碼 for c in params.學習內容)}", file=sys.stderr)

            result = generate_with_corrections(
                config=config,
                client=client,
                curriculum=curriculum,
                performance=performance,
                intro_text=intro_text,
                grade_content=grade_content,
                params=params,
                question_id=question_id,
                max_retries=max_retries,
                skip_verify=args.no_verify,
                html_renderer=html_renderer,
                dry_run=args.dry_run,
                image_generation_mode=args.image_generation_mode,
                user_topic=args.topic or "",
                user_passage=args.passage or "",
                user_options=args.options,
                user_core_question=args.core_question or "",
                prior_scopes=list(prior_scopes),
                curriculum_context=math_curriculum_context,
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)

            results.append(question)

            scope = extract_math_prior_scope(question)
            if scope is not None:
                prior_scopes.append(scope)

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

    finally:
        if html_renderer is not None:
            html_renderer.stop()


if __name__ == "__main__":
    main()
