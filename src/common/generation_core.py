"""Shared generation core for NS and SS subjects.

``generate_one_core`` runs the 文本生成器 → N-parallel-子題產生器 pipeline.
``generate_with_corrections_core`` wraps it with the verify/correct retry loop.

Both are parameterised by a :class:`src.common.subject_spec.SubjectGenerationSpec`
instance, which bundles all per-subject callables (prompt builders, parsers,
post-draft hooks, verify/correct functions, etc.).

Design note: ``src/`` must NOT import from ``server/``.  All imports here are
from ``src.*`` only.
"""

from __future__ import annotations

import concurrent.futures
import sys
from collections.abc import Callable, Sequence
from enum import Enum
from typing import Any, get_args

from src.common.figure_policy_trail import FigurePolicyTrailEvent
from src.common.subject_spec import SubjectGenerationSpec
from src.common.verification_trail import (
    VerificationTrailEvent,
    make_correction_trail_entry,
    make_initial_trail_entry,
    make_verification_trail_entry,
)
from src.config import Config
from src.curriculum_context import CurriculumContext
from src.html_renderer import PlaywrightRenderer
from src.llm_client import LLMClient, emit_plan, emit_stage, make_render_error_sink
from src.renderer import render_image


def _emit_update(callback: Callable | None, question: Any, phase: str) -> None:
    if callback is not None:
        callback(question, phase)


def _emit_trail(
    callback: Callable[[VerificationTrailEvent], None] | None,
    question_id: str,
    verification: Any,
    model: str,
) -> None:
    if callback is not None:
        callback(make_verification_trail_entry(question_id, verification, model))


def _emit_initial_trail(
    callback: Callable[[VerificationTrailEvent], None] | None,
    question_id: str,
    question: Any,
) -> None:
    if callback is not None:
        callback(make_initial_trail_entry(question_id, question))


def _emit_correction_trail(
    callback: Callable[[VerificationTrailEvent], None] | None,
    question_id: str,
    question: Any,
    retry_index: int,
    model: str,
) -> None:
    if callback is not None:
        callback(make_correction_trail_entry(question_id, question, retry_index, model))


def build_text_generation_prompts(
    config: Config,
    params: Any,
    spec: SubjectGenerationSpec,
    *,
    disable_reference_fewshot: bool = False,
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    prior_scopes: Sequence[Any] | None = None,
    core_question_callback: bool = False,
) -> tuple[str, str, list, dict]:
    """Build the exact prompts used by a 文本生成器 call."""
    few_shot_dir = config.data_dir / spec.few_shot_subdir / "few_shot"
    text_system, stage_ctx = spec.build_text_system_fn(params)
    text_user, text_images = spec.build_text_user_fn(
        params,
        few_shot_dir,
        user_passage,
        user_options,
        user_topic,
        user_core_question,
        image_generation_mode,
        disable_reference_fewshot,
        prior_scopes,
        core_question_callback,
    )
    return text_system, text_user, text_images, stage_ctx


def build_subquestion_generation_prompts(
    config: Config,
    params: Any,
    spec: SubjectGenerationSpec,
    *,
    disable_reference_fewshot: bool = False,
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    prior_scopes: Sequence[Any] | None = None,
    core_question_callback: bool = False,
) -> list[tuple[int, str, str, list]]:
    """Build deterministic 子題產生器 prompts with visible 文本生成器 placeholders."""
    _, _, _, stage_ctx = build_text_generation_prompts(
        config,
        params,
        spec,
        disable_reference_fewshot=disable_reference_fewshot,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        prior_scopes=prior_scopes,
        core_question_callback=core_question_callback,
    )
    subquestion_configs = getattr(params, "subquestion_configs", [])
    slot_count = params.sub_question_count or len(subquestion_configs) or 3
    plans = spec.make_fallback_sq_plans_fn(params, slot_count)
    sub_system = spec.build_subquestion_system_fn(stage_ctx)
    few_shot_dir = config.data_dir / spec.few_shot_subdir / "few_shot"
    text_raw = {
        "核心問題": "{{核心問題：由前一階段產生}}",
        "文本": "{{文本：由前一階段產生}}",
        "取材來源": ["{{取材來源：由前一階段產生}}"],
    }
    previews = []
    for idx, plan in enumerate(plans, start=1):
        preview_plan = {
            **plan,
            "序號": idx,
            "出題概念": "{{子題 plan：由前一階段產生}}",
        }
        slot_cfg = subquestion_configs[idx - 1] if idx - 1 < len(subquestion_configs) else None
        sub_user, sub_images = spec.build_subquestion_user_fn(
            text_raw,
            params,
            few_shot_dir,
            preview_plan,
            slot_cfg,
            image_generation_mode,
            disable_reference_fewshot,
            core_question_callback,
            idx == len(plans),
        )
        previews.append((idx, sub_system, sub_user, sub_images))
    return previews


def generate_one_core(
    config: Config,
    client: LLMClient | None,
    params: Any,
    question_id: str,
    spec: SubjectGenerationSpec,
    *,
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
    core_question_callback: bool = False,
    on_question_update: Callable | None = None,
    on_trail_entry: Callable[[VerificationTrailEvent], None] | None = None,
    on_figure_policy_entry: Callable[[FigurePolicyTrailEvent], None] | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[Any] | None = None,
    curriculum_context: CurriculumContext | None = None,
) -> Any:
    """Shared 文本生成器 → N-parallel-子題產生器 pipeline for NS and SS."""
    # ── Text-prompt build (dry-run returns early) ─────────────────────────
    text_system, text_user, text_images, stage_ctx = build_text_generation_prompts(
        config,
        params,
        spec,
        disable_reference_fewshot=disable_reference_fewshot,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        prior_scopes=prior_scopes,
        core_question_callback=core_question_callback,
    )
    if dry_run:
        img_note = f" ({len(text_images)} few-shot images)" if text_images else ""
        return (
            f"=== TEXT SYSTEM PROMPT ({len(text_system)} chars) ===\n"
            f"{text_system[:2000]}...\n\n"
            f"=== TEXT USER PROMPT ({len(text_user)} chars{img_note}) ===\n{text_user}"
        )

    obs = client.get_observer() if client else None
    print(f"  Generating question {question_id}...", file=sys.stderr)

    emit_stage(obs, "generator", "llm_generate", "start")
    text_raw = client.generate_json(text_system, text_user, images=text_images or None)
    emit_stage(obs, "generator", "llm_generate", "end")

    question = spec.parse_text_shell_fn(text_raw, question_id, params, config.model_execute)

    sq_plans: list[dict] = text_raw.get("subquestions", [])
    if params.sub_question_count is not None:
        sq_plans = sq_plans[:params.sub_question_count]
        if len(sq_plans) < params.sub_question_count:
            fallback_plans = spec.make_fallback_sq_plans_fn(
                params, params.sub_question_count,
            )
            # Known limitation: padded 小題 skip the 文本生成器 coherence pass,
            # so their angle may overlap a sibling 小題.
            sq_plans.extend(fallback_plans[len(sq_plans):])
    if not sq_plans:
        n = params.sub_question_count or 3
        sq_plans = spec.make_fallback_sq_plans_fn(params, n)

    emit_plan(obs, len(sq_plans))

    sub_system = spec.build_subquestion_system_fn(stage_ctx)
    few_shot_dir = config.data_dir / spec.few_shot_subdir / "few_shot"
    max_workers = min(len(sq_plans), config.subgen_max_concurrency)
    use_embedded_subquestions = (
        sub_client_factory is None and client is not None and not isinstance(client, LLMClient)
    )

    def _generate_subquestion(plan_item: tuple[int, dict]) -> Any:
        plan_position, sq_plan = plan_item
        idx = sq_plan.get("序號", plan_position + 1)
        agent_id = f"sub_generator#{idx}"
        if use_embedded_subquestions:
            return spec.parse_subquestion_fn(sq_plan, question_id, params, idx)

        subquestion_configs = getattr(params, "subquestion_configs", [])
        slot_cfg = subquestion_configs[idx - 1] if idx - 1 < len(subquestion_configs) else None
        sub_user, sub_images = spec.build_subquestion_user_fn(
            text_raw, params, few_shot_dir, sq_plan, slot_cfg,
            image_generation_mode, disable_reference_fewshot,
            core_question_callback,
            plan_position == len(sq_plans) - 1,
        )

        attempts = 1 + max(0, config.subgen_retries)
        result = None
        last_exc_text: str = ""
        for attempt in range(1, attempts + 1):
            sub_client = (
                sub_client_factory() if sub_client_factory is not None else LLMClient(config)
            )
            if hasattr(sub_client, "set_observer"):
                sub_client.set_observer(obs)
            emit_stage(obs, agent_id, "llm_generate", "start", attempt=attempt)
            try:
                sq_raw = sub_client.generate_json(
                    sub_system,
                    sub_user,
                    images=sub_images or None,
                    agent_override=agent_id,
                )
                result = spec.parse_subquestion_fn(sq_raw, question_id, params, idx)
            except Exception as e:
                print(
                    f"  Sub-generator {agent_id} attempt {attempt}/{attempts} failed: {e}",
                    file=sys.stderr,
                )
                result = None
                last_exc_text = str(e)
            if result is not None:
                emit_stage(obs, agent_id, "llm_generate", "end", attempt=attempt)
                configured_type = (
                    slot_cfg.question_type
                    if slot_cfg is not None else None
                )
                if configured_type is not None:
                    field = type(result).model_fields.get("題型")
                    enum_type = field.annotation if field is not None else None
                    enum_candidates = (
                        get_args(enum_type) if enum_type is not None else ()
                    )
                    enum_type = next(
                        (
                            candidate
                            for candidate in enum_candidates
                            if isinstance(candidate, type)
                            and issubclass(candidate, Enum)
                        ),
                        enum_type,
                    )
                    try:
                        coerced_type = (
                            enum_type(configured_type)
                            if enum_type is not None else None
                        )
                    except (TypeError, ValueError) as e:
                        print(
                            f"  Could not enforce 題型 for {agent_id}: {e}",
                            file=sys.stderr,
                        )
                    else:
                        if coerced_type is None:
                            print(
                                f"  Could not enforce 題型 for {agent_id}: "
                                "field has no declared enum type",
                                file=sys.stderr,
                            )
                        else:
                            result.題型 = coerced_type
            if result is not None:
                return result
            if attempt < attempts:
                print(
                    f"  Retrying sub-generator {agent_id}"
                    f" (attempt {attempt + 1}/{attempts})...",
                    file=sys.stderr,
                )
        _drop_msg = (
            f"子題 {idx} 生成失敗（{attempts} 次嘗試）: {last_exc_text}"
            if last_exc_text
            else f"子題 {idx} 生成失敗（{attempts} 次嘗試）"
        )
        emit_stage(obs, agent_id, "llm_generate", "error", message=_drop_msg)
        print(
            f"  Sub-generator {agent_id} dropped after {attempts} attempt(s)",
            file=sys.stderr,
        )
        return None

    sq_results: dict[int, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_generate_subquestion, plan_item): plan_item
            for plan_item in enumerate(sq_plans)
        }
        for future in concurrent.futures.as_completed(futures):
            plan_position, sq_plan = futures[future]
            idx = sq_plan.get("序號", plan_position + 1)
            result = future.result()
            if result is not None:
                sq_results[idx] = result

    question.subquestions = [sq_results[k] for k in sorted(sq_results)]
    _emit_update(on_question_update, question, "draft")

    # ── Post-draft hook (SS: ensure_top_level_visual_spec) ────────────────
    if spec.ensure_visual_spec_fn is not None:
        prior_chart_spec = question.chart_spec.model_copy() if question.chart_spec else None
        spec.ensure_visual_spec_fn(question, params, client)
        if question.chart_spec != prior_chart_spec:
            _emit_update(on_question_update, question, "corrected")

    if spec.prepare_visual_policy_fn is not None:
        spec.prepare_visual_policy_fn(
            question,
            params,
            client,
            on_figure_policy_entry=on_figure_policy_entry,
        )

    # ── Top-level image rendering ─────────────────────────────────────────
    chart_image_path: str | None = None
    if question.chart_spec:
        img_path = config.output_dir / f"{question_id}.png"
        print(f"  Rendering image: {img_path}", file=sys.stderr)
        _on_render_error, _render_failed = make_render_error_sink(obs)
        emit_stage(obs, "image_agent", "render_image", "start")
        rendered = render_image(
            question.chart_spec.model_dump(),
            img_path,
            question_text=spec.image_question_text_fn(question),
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
            _emit_update(on_question_update, question, "image")

    # ── Subquestion image rendering ────────────────────────────────────────
    if spec.render_subquestion_images_fn is not None:
        subquestion_image_paths = spec.render_subquestion_images_fn(
            question,
            config,
            client,
            html_renderer,
            image_generation_mode,
            obs,
            params,
            on_figure_policy_entry=on_figure_policy_entry,
        )
        if chart_image_path is None and subquestion_image_paths:
            chart_image_path = subquestion_image_paths[0]
        if subquestion_image_paths:
            _emit_update(on_question_update, question, "image")

    # ── Verification ──────────────────────────────────────────────────────
    if not skip_verify:
        _emit_initial_trail(on_trail_entry, question_id, question)
        print(f"  Verifying question {question_id}...", file=sys.stderr)
        emit_stage(obs, "verifier", "verify", "start")
        result = spec.verify_fn(
            client, question,
            chart_image_path=chart_image_path,
            curriculum_context=curriculum_context,
        )
        emit_stage(obs, "verifier", "verify", "end")
        question.verification = result
        _emit_trail(
            on_trail_entry,
            question_id,
            result,
            config.model_verify or config.model_execute,
        )
        _emit_update(on_question_update, question, "verified")
        status = "PASSED" if result.passed else "FAILED"
        print(f"  Verification {status}: {result.details[:100]}", file=sys.stderr)

    return question


def generate_with_corrections_core(
    config: Config,
    client: LLMClient | None,
    params: Any,
    question_id: str,
    spec: SubjectGenerationSpec,
    *,
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
    core_question_callback: bool = False,
    on_question_update: Callable | None = None,
    on_trail_entry: Callable[[VerificationTrailEvent], None] | None = None,
    on_figure_policy_entry: Callable[[FigurePolicyTrailEvent], None] | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[Any] | None = None,
    curriculum_context: CurriculumContext | None = None,
) -> Any:
    """generate_one_core followed by up to max_retries correction passes."""
    question = generate_one_core(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        spec=spec,
        dry_run=dry_run,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        text_word_limit=text_word_limit,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        core_question_callback=core_question_callback,
        on_question_update=on_question_update,
        on_trail_entry=on_trail_entry,
        on_figure_policy_entry=on_figure_policy_entry,
        sub_client_factory=sub_client_factory,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
    )

    if dry_run or not hasattr(question, "verification"):
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
        prior_subquestion_specs = [
            getattr(sub, "chart_spec", None).model_copy()
            if getattr(sub, "chart_spec", None)
            else None
            for sub in question.subquestions
        ]

        chart_image_path: str | None = None
        if question.圖片:
            p = config.output_dir / question.圖片
            if p.exists():
                chart_image_path = str(p)

        emit_stage(obs, "corrector", "correct", "start", retry=attempt + 1)
        question = spec.correct_fn(
            client, question, question.verification,
            chart_image_path=chart_image_path,
            curriculum_context=curriculum_context,
        )
        emit_stage(obs, "corrector", "correct", "end", retry=attempt + 1)
        _emit_update(on_question_update, question, "corrected")

        new_chart_image_path: str | None = None
        if question.chart_spec and question.chart_spec != prior_chart_spec:
            img_path = config.output_dir / f"{question_id}.png"
            print(f"  Chart spec changed; re-rendering image: {img_path}", file=sys.stderr)
            _on_render_error, _render_failed = make_render_error_sink(obs)
            emit_stage(obs, "image_agent", "render_image", "start")
            rendered = render_image(
                question.chart_spec.model_dump(),
                img_path,
                question_text=spec.image_question_text_fn(question),
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
                _emit_update(on_question_update, question, "image")
        elif question.圖片:
            p = config.output_dir / question.圖片
            new_chart_image_path = str(p) if p.exists() else None

        visual_specs_changed = (
            question.chart_spec != prior_chart_spec
            or len(question.subquestions) != len(prior_subquestion_specs)
            or any(
                getattr(sub, "chart_spec", None) != prior_subquestion_specs[index]
                for index, sub in enumerate(question.subquestions)
                if index < len(prior_subquestion_specs)
            )
        )
        if (
            visual_specs_changed
            and spec.post_correction_visual_policy_fn is not None
        ):
            spec.post_correction_visual_policy_fn(
                question,
                config,
                client,
                html_renderer,
                image_generation_mode,
                obs,
                params,
                on_figure_policy_entry=on_figure_policy_entry,
            )
            if question.圖片:
                new_chart_image_path = str(config.output_dir / question.圖片)

        _emit_correction_trail(
            on_trail_entry,
            question_id,
            question,
            attempt + 1,
            config.model_correct or config.model_execute,
        )

        if not skip_verify:
            emit_stage(obs, "verifier", "verify", "start", retry=attempt + 1)
            result = spec.verify_fn(
                client, question,
                chart_image_path=new_chart_image_path,
                curriculum_context=curriculum_context,
            )
            emit_stage(obs, "verifier", "verify", "end", retry=attempt + 1)
            question.verification = result
            _emit_trail(
                on_trail_entry,
                question_id,
                result,
                config.model_verify or config.model_execute,
            )
            _emit_update(on_question_update, question, "verified")
            status = "PASSED" if result.passed else "FAILED"
            print(f"  Re-verification {status}: {result.details[:100]}", file=sys.stderr)

    return question
