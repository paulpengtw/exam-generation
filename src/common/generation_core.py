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
import inspect
import logging
import sys
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from enum import Enum
from typing import Any, get_args

from pydantic import ValidationError

from src.common.correction_decision import CorrectionDecision
from src.common.figure_policy_trail import FigurePolicyTrailEvent
from src.common.generation_events import (
    OperationScope,
    QuestionContext,
    new_operation_scope,
    new_run_id,
)
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

logger = logging.getLogger(__name__)


@contextmanager
def _client_scope_binding(client: Any, scope: OperationScope | None):
    """Temporarily bind the immutable operation to nested client helpers."""
    setter = getattr(client, "set_scope", None)
    if setter is None or scope is None:
        yield
        return
    previous = getattr(client, "scope", None)
    setter(scope)
    try:
        yield
    finally:
        setter(previous)


def _call_with_optional_scope(
    function: Callable,
    *args: Any,
    scope: OperationScope | None,
    **kwargs: Any,
) -> Any:
    """Call a subject hook with an explicit scope when its seam supports it.

    A few tests and downstream integrations provide small legacy hook doubles
    with the pre-v2 signature.  Inspecting the callable once at the boundary
    preserves those adapters without catching ``TypeError`` from the hook
    body, while production hooks receive ownership explicitly.
    """
    if scope is not None:
        try:
            signature = inspect.signature(function)
            parameters = signature.parameters.values()
            accepts_scope = "scope" in signature.parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            accepts_scope = False
        if accepts_scope:
            kwargs["scope"] = scope
    nested_client = next(
        (argument for argument in args if hasattr(argument, "set_scope")),
        None,
    )
    with _client_scope_binding(nested_client, scope):
        return function(*args, **kwargs)


def _callback_with_optional_scope(
    callback: Callable | None,
    *args: Any,
    scope: OperationScope | None,
    **kwargs: Any,
) -> Any:
    """Invoke an event callback with scope when its seam supports it."""
    if callback is None:
        return None
    if scope is not None:
        try:
            signature = inspect.signature(callback)
            parameters = signature.parameters.values()
            accepts_scope = "scope" in signature.parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            accepts_scope = False
        if accepts_scope:
            kwargs["scope"] = scope
    return callback(*args, **kwargs)


class GenerationCancelled(Exception):
    """Raised at stage boundaries when the run's cancel signal has been set.

    Workers catch this and exit silently — the client has already disconnected.
    No error SSE event is emitted; the route layer persists 'aborted'.
    """


class SubquestionParseError(ValueError):
    """Safe, operator-facing reason for an unusable subquestion response."""

    _FIELDS = frozenset({
        "id", "序號", "年級", "科目", "科學能力", "核心素養", "學習內容",
        "學習表現", "出題概念", "出題指示", "認知歷程", "reporting_scale", "題型",
        "題目", "答案", "答案解析", "評分規準", "誘答分析", "題目內容類型",
        "image_generation_mode", "圖片", "chart_spec", "interaction",
    })

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)

    @classmethod
    def from_validation(cls, error: ValidationError) -> "SubquestionParseError":
        """Convert Pydantic details to a field/type-only safe reason."""
        try:
            first = error.errors(include_input=False, include_context=False, include_url=False)[0]
        except (AttributeError, IndexError, TypeError):
            return cls("子題欄位驗證失敗（validation_error）")
        location = first.get("loc", ())
        field = location[0] if location else "子題欄位"
        if field not in cls._FIELDS:
            field = "子題欄位"
        raw_type = first.get("type", "validation_error")
        error_type = str(raw_type)
        error_type = "".join(
            character for character in error_type
            if character.isalnum() or character in {".", "_", "-"}
        )[:64] or "validation_error"
        return cls(f"子題欄位「{field}」驗證失敗（{error_type}）")


def _emit_update(callback: Callable | None, question: Any, phase: str) -> None:
    if callback is not None:
        callback(question, phase)


def _apply_fixed_subquestion_identity(
    subquestion: Any,
    question_id: str,
    plan_position: int,
    *,
    enabled: bool,
) -> Any:
    """Apply the program-owned identity for one normalized grouped slot."""
    if not enabled:
        return subquestion
    slot_number = plan_position + 1
    subquestion.id = f"{question_id}-sq{slot_number:03d}"
    subquestion.序號 = slot_number
    # ``_plan_index`` is intentionally one-based because subject config lists
    # and the existing renderer filenames are one-based.  It is independent
    # from the zero-based transport ``subquestion_index`` in the manifest.
    if hasattr(subquestion, "_plan_index"):
        subquestion._plan_index = slot_number
    return subquestion


def _emit_trail(
    callback: Callable[[VerificationTrailEvent], None] | None,
    question_id: str,
    verification: Any,
    model: str,
    scope: OperationScope | None = None,
) -> None:
    if callback is not None:
        _callback_with_optional_scope(
            callback,
            make_verification_trail_entry(question_id, verification, model),
            scope=scope,
        )


def _emit_initial_trail(
    callback: Callable[[VerificationTrailEvent], None] | None,
    question_id: str,
    question: Any,
    scope: OperationScope | None = None,
) -> None:
    if callback is not None:
        _callback_with_optional_scope(
            callback,
            make_initial_trail_entry(question_id, question),
            scope=scope,
        )


def _emit_correction_trail(
    callback: Callable[[VerificationTrailEvent], None] | None,
    question_id: str,
    question: Any,
    retry_index: int,
    model: str,
    decision: CorrectionDecision | None = None,
    scope: OperationScope | None = None,
) -> None:
    if callback is not None:
        _callback_with_optional_scope(
            callback,
            make_correction_trail_entry(
                question_id, question, retry_index, model,
                outcome=decision.outcome if decision is not None else None,
                reason=decision.reason if decision is not None else None,
            ),
            scope=scope,
        )


def _scoped_callback(
    callback: Callable | None,
    scope: OperationScope | None,
) -> Callable | None:
    """Bind a callback's event ownership without changing its legacy shape."""
    if callback is None:
        return None

    def emit(*args: Any, **kwargs: Any) -> Any:
        return _callback_with_optional_scope(callback, *args, scope=scope, **kwargs)

    return emit


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
    text_instruction: str | None = None,
    prior_scopes: Sequence[Any] | None = None,
    core_question_callback: bool = False,
) -> tuple[str, str, list, dict, list]:
    """Build the exact prompts used by a 文本生成器 call."""
    few_shot_dir = config.data_dir / spec.few_shot_subdir / "few_shot"
    text_system, stage_ctx = spec.build_text_system_fn(params)
    text_user, text_images, text_draws = spec.build_text_user_fn(
        params,
        few_shot_dir,
        user_passage,
        user_options,
        user_topic,
        user_core_question,
        text_instruction,
        image_generation_mode,
        disable_reference_fewshot,
        prior_scopes,
        core_question_callback,
    )
    return text_system, text_user, text_images, stage_ctx, text_draws


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
    text_instruction: str | None = None,
    prior_scopes: Sequence[Any] | None = None,
    core_question_callback: bool = False,
) -> list[tuple[int, str, str, list]]:
    """Build deterministic 子題產生器 prompts with visible 文本生成器 placeholders."""
    _, _, _, stage_ctx, _text_draws = build_text_generation_prompts(
        config,
        params,
        spec,
        disable_reference_fewshot=disable_reference_fewshot,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        text_instruction=text_instruction,
        prior_scopes=prior_scopes,
        core_question_callback=core_question_callback,
    )
    subquestion_configs = getattr(params, "subquestion_configs", []) or []
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
        slot_cfg = subquestion_configs[idx - 1] if 1 <= idx <= len(subquestion_configs) else None
        sub_user, sub_images, _sub_draws = spec.build_subquestion_user_fn(
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
    text_instruction: str | None = None,
    core_question_callback: bool = False,
    on_question_update: Callable | None = None,
    on_trail_entry: Callable[[VerificationTrailEvent], None] | None = None,
    on_figure_policy_entry: Callable[[FigurePolicyTrailEvent], None] | None = None,
    on_reference_example_entry: Callable | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[Any] | None = None,
    curriculum_context: CurriculumContext | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    question_context: QuestionContext | None = None,
) -> Any:
    """Shared 文本生成器 → N-parallel-子題產生器 pipeline for NS and SS."""
    owner = question_context or QuestionContext(
        run_id=new_run_id(), question_id=question_id, index=0
    )
    text_scope = new_operation_scope(owner, kind="text")
    # ── Text-prompt build (dry-run returns early) ─────────────────────────
    text_system, text_user, text_images, stage_ctx, text_ref_draws = build_text_generation_prompts(
        config,
        params,
        spec,
        disable_reference_fewshot=disable_reference_fewshot,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        text_instruction=text_instruction,
        prior_scopes=prior_scopes,
        core_question_callback=core_question_callback,
    )
    if on_reference_example_entry is not None:
        _now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        for _draw in text_ref_draws:
            _draw_copy = dict(_draw, question_id=question_id, timestamp=_now.isoformat())
            _callback_with_optional_scope(
                on_reference_example_entry,
                _draw_copy,
                scope=text_scope,
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

    emit_stage(obs, "generator", "llm_generate", "start", scope=text_scope)
    text_raw = client.generate_json(
        text_system,
        text_user,
        images=text_images or None,
        scope=text_scope,
    )
    emit_stage(obs, "generator", "llm_generate", "end", scope=text_scope)

    # ── Cancel boundary: after text generator, before subquestion generation ─
    if is_cancelled is not None and is_cancelled():
        raise GenerationCancelled()

    question = spec.parse_text_shell_fn(text_raw, question_id, params, config.model_execute)

    sq_plans: list[dict] = text_raw.get("subquestions", [])
    subquestion_configs = getattr(params, "subquestion_configs", [])
    resolved_slot_count = (
        params.sub_question_count
        or len(subquestion_configs)
        or len(sq_plans)
        or 3
    )
    if spec.fixed_subquestion_identity:
        sq_plans = sq_plans[:resolved_slot_count]
        if len(sq_plans) < resolved_slot_count:
            fallback_plans = spec.make_fallback_sq_plans_fn(
                params, resolved_slot_count,
            )
            # Known limitation: padded 小題 skip the 文本生成器 coherence pass,
            # so their angle may overlap a sibling 小題.
            sq_plans.extend(fallback_plans[len(sq_plans):])
    elif params.sub_question_count is not None:
        sq_plans = sq_plans[:params.sub_question_count]
        if len(sq_plans) < params.sub_question_count:
            fallback_plans = spec.make_fallback_sq_plans_fn(
                params, params.sub_question_count,
            )
            # Known limitation: padded 小題 skip the 文本生成器 coherence pass,
            # so their angle may overlap a sibling 小題.
            sq_plans.extend(fallback_plans[len(sq_plans):])
    if not sq_plans:
        n = resolved_slot_count
        sq_plans = spec.make_fallback_sq_plans_fn(params, n)

    slot_manifest = None
    if spec.fixed_subquestion_identity:
        slot_manifest = [
            {
                "subquestion_index": plan_position,
                "id": f"{question_id}-sq{plan_position + 1:03d}",
                "序號": plan_position + 1,
            }
            for plan_position in range(len(sq_plans))
        ]
    emit_plan(obs, len(sq_plans), scope=text_scope, slots=slot_manifest)
    _emit_update(on_question_update, question, "draft")

    sub_system = spec.build_subquestion_system_fn(stage_ctx)
    few_shot_dir = config.data_dir / spec.few_shot_subdir / "few_shot"
    max_workers = min(len(sq_plans), config.subgen_max_concurrency)
    use_embedded_subquestions = (
        sub_client_factory is None and client is not None and not isinstance(client, LLMClient)
    )

    def _generate_subquestion(plan_item: tuple[int, dict]) -> Any:
        plan_position, sq_plan = plan_item
        idx = plan_position + 1
        agent_id = f"sub_generator#{idx}"
        if use_embedded_subquestions:
            try:
                parsed = spec.parse_subquestion_fn(sq_plan, question_id, params, idx)
                return _apply_fixed_subquestion_identity(
                    parsed,
                    question_id,
                    plan_position,
                    enabled=spec.fixed_subquestion_identity,
                )
            except SubquestionParseError as exc:
                # Embedded responses predate the retrying LLM path; preserve
                # their existing drop-on-parse-failure behavior while keeping
                # the reason safe for operators.
                logger.warning(
                    "embedded subquestion discarded: question_id=%s agent=%s reason=%s",
                    question_id,
                    agent_id,
                    exc.reason,
                )
                return None

        slot_cfg = subquestion_configs[idx - 1] if 1 <= idx <= len(subquestion_configs) else None
        sub_user, sub_images, sub_ref_draws = spec.build_subquestion_user_fn(
            text_raw, params, few_shot_dir, sq_plan, slot_cfg,
            image_generation_mode, disable_reference_fewshot,
            core_question_callback,
            plan_position == len(sq_plans) - 1,
        )
        first_sub_scope = new_operation_scope(
            owner,
            kind="subquestion",
            subquestion_index=plan_position,
        )
        if on_reference_example_entry is not None:
            _sub_now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            for _sub_draw in sub_ref_draws:
                _sub_draw_copy = dict(
                    _sub_draw, question_id=question_id, timestamp=_sub_now.isoformat()
                )
                _callback_with_optional_scope(
                    on_reference_example_entry,
                    _sub_draw_copy,
                    scope=first_sub_scope,
                )

        attempts = 1 + max(0, config.subgen_retries)
        result = None
        last_failure_reason = ""
        superseded_operation_id: str | None = None
        for attempt in range(1, attempts + 1):
            last_failure_reason = ""
            sub_scope = (
                first_sub_scope
                if attempt == 1
                else new_operation_scope(
                    owner,
                    kind="subquestion",
                    subquestion_index=plan_position,
                    supersedes_operation_id=superseded_operation_id,
                )
            )
            sub_client = (
                sub_client_factory() if sub_client_factory is not None else LLMClient(config)
            )
            if hasattr(sub_client, "set_scope"):
                sub_client.set_scope(sub_scope)
            if hasattr(sub_client, "set_observer"):
                sub_client.set_observer(obs)
            emit_stage(
                obs,
                agent_id,
                "llm_generate",
                "start",
                scope=sub_scope,
                attempt=attempt,
            )
            try:
                sq_raw = sub_client.generate_json(
                    sub_system,
                    sub_user,
                    images=sub_images or None,
                    agent_override=agent_id,
                    scope=sub_scope,
                )
            except Exception as e:
                last_failure_reason = f"provider call raised {type(e).__name__}"
                print(
                    f"  Sub-generator {agent_id} attempt {attempt}/{attempts} failed: "
                    f"{last_failure_reason}",
                    file=sys.stderr,
                )
                result = None
            else:
                try:
                    result = spec.parse_subquestion_fn(
                        sq_raw, question_id, params, idx
                    )
                except SubquestionParseError as e:
                    last_failure_reason = e.reason
                    result = None
                except Exception as e:
                    last_failure_reason = (
                        f"subquestion parser raised {type(e).__name__}"
                    )
                    result = None
                if result is not None:
                    result = _apply_fixed_subquestion_identity(
                        result,
                        question_id,
                        plan_position,
                        enabled=spec.fixed_subquestion_identity,
                    )
                if result is None and not last_failure_reason:
                    last_failure_reason = (
                        "subquestion response did not satisfy the expected schema"
                    )
            if result is not None:
                emit_stage(
                    obs,
                    agent_id,
                    "llm_generate",
                    "end",
                    scope=sub_scope,
                    attempt=attempt,
                )
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
                superseded_operation_id = sub_scope.operation_id
                print(
                    f"  Retrying sub-generator {agent_id}"
                    f" (attempt {attempt + 1}/{attempts})...",
                    file=sys.stderr,
                )
        _drop_msg = (
            f"子題 {idx} 生成失敗（{attempts} 次嘗試）: {last_failure_reason}"
            if last_failure_reason
            else f"子題 {idx} 生成失敗（{attempts} 次嘗試）"
        )
        logger.warning(
            "subquestion generation exhausted: question_id=%s agent=%s attempts=%d reason=%s",
            question_id,
            agent_id,
            attempts,
            last_failure_reason or "subquestion response did not satisfy the expected schema",
        )
        emit_stage(
            obs,
            agent_id,
            "llm_generate",
            "error",
            scope=sub_scope,
            message=_drop_msg,
        )
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
            idx = plan_position + 1
            result = future.result()
            if result is not None:
                sq_results[idx] = result
                question.subquestions = [sq_results[k] for k in sorted(sq_results)]
                _emit_update(on_question_update, question, "draft")

    question.subquestions = [sq_results[k] for k in sorted(sq_results)]

    # ── Cancel boundary: after subquestion generation, before image/verify ─
    if is_cancelled is not None and is_cancelled():
        raise GenerationCancelled()

    # ── Post-draft hook (SS: ensure_top_level_visual_spec) ────────────────
    visual_spec_scope = new_operation_scope(owner, kind="image_spec")
    if spec.ensure_visual_spec_fn is not None:
        prior_chart_spec = question.chart_spec.model_copy() if question.chart_spec else None
        _call_with_optional_scope(
            spec.ensure_visual_spec_fn,
            question,
            params,
            client,
            scope=visual_spec_scope,
        )
        if question.chart_spec != prior_chart_spec:
            _emit_update(on_question_update, question, "corrected")

    visual_policy_scope = new_operation_scope(owner, kind="image_policy")
    if spec.prepare_visual_policy_fn is not None:
        _call_with_optional_scope(
            spec.prepare_visual_policy_fn,
            question,
            params,
            client,
            on_figure_policy_entry=_scoped_callback(
                on_figure_policy_entry,
                visual_policy_scope,
            ),
            scope=visual_policy_scope,
        )

    # ── Top-level image rendering ─────────────────────────────────────────
    chart_image_path: str | None = None
    if question.chart_spec:
        img_path = config.output_dir / f"{question_id}.png"
        print(f"  Rendering image: {img_path}", file=sys.stderr)
        image_scope = new_operation_scope(owner, kind="image")
        _on_render_error, _render_failed = make_render_error_sink(obs, scope=image_scope)
        emit_stage(obs, "image_agent", "render_image", "start", scope=image_scope)
        rendered = render_image(
            question.chart_spec.model_dump(),
            img_path,
            question_text=spec.image_question_text_fn(question),
            html_renderer=html_renderer,
            llm_client=client,
            image_generation_mode=image_generation_mode,
            on_error=_on_render_error,
            scope=image_scope,
        )
        if not _render_failed:
            emit_stage(obs, "image_agent", "render_image", "end", scope=image_scope)
        if rendered:
            question.圖片 = f"{question_id}.png"
            chart_image_path = rendered
            _emit_update(on_question_update, question, "image")

    # ── Subquestion image rendering ────────────────────────────────────────
    if spec.render_subquestion_images_fn is not None:
        subquestion_image_scope = new_operation_scope(owner, kind="image")
        subquestion_image_paths = _call_with_optional_scope(
            spec.render_subquestion_images_fn,
            question,
            config,
            client,
            html_renderer,
            image_generation_mode,
            obs,
            params,
            on_figure_policy_entry=_scoped_callback(
                on_figure_policy_entry,
                subquestion_image_scope,
            ),
            scope=subquestion_image_scope,
        )
        if chart_image_path is None and subquestion_image_paths:
            chart_image_path = subquestion_image_paths[0]
        if subquestion_image_paths:
            _emit_update(on_question_update, question, "image")

    # ── Cancel boundary: after image rendering, before verification ───────
    if is_cancelled is not None and is_cancelled():
        raise GenerationCancelled()

    # ── Verification ──────────────────────────────────────────────────────
    if not skip_verify:
        verify_scope = new_operation_scope(owner, kind="verify")
        _emit_initial_trail(
            on_trail_entry,
            question_id,
            question,
            scope=verify_scope,
        )
        print(f"  Verifying question {question_id}...", file=sys.stderr)
        emit_stage(obs, "verifier", "verify", "start", scope=verify_scope)
        result = _call_with_optional_scope(
            spec.verify_fn,
            client, question,
            chart_image_path=chart_image_path,
            curriculum_context=curriculum_context,
            scope=verify_scope,
        )
        emit_stage(obs, "verifier", "verify", "end", scope=verify_scope)
        question.verification = result
        _emit_trail(
            on_trail_entry,
            question_id,
            result,
            config.model_verify or config.model_execute,
            scope=verify_scope,
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
    text_instruction: str | None = None,
    core_question_callback: bool = False,
    on_question_update: Callable | None = None,
    on_trail_entry: Callable[[VerificationTrailEvent], None] | None = None,
    on_figure_policy_entry: Callable[[FigurePolicyTrailEvent], None] | None = None,
    on_reference_example_entry: Callable | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[Any] | None = None,
    curriculum_context: CurriculumContext | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    question_context: QuestionContext | None = None,
) -> Any:
    """generate_one_core followed by up to max_retries correction passes."""
    owner = question_context or QuestionContext(
        run_id=new_run_id(), question_id=question_id, index=0
    )
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
        text_instruction=text_instruction,
        core_question_callback=core_question_callback,
        on_question_update=on_question_update,
        on_trail_entry=on_trail_entry,
        on_figure_policy_entry=on_figure_policy_entry,
        on_reference_example_entry=on_reference_example_entry,
        sub_client_factory=sub_client_factory,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
        is_cancelled=is_cancelled,
        question_context=owner,
    )

    if dry_run or not hasattr(question, "verification"):
        return question

    obs = client.get_observer() if client else None
    previous_correction_operation_id: str | None = None
    previous_image_operation_id: str | None = None
    previous_verify_operation_id: str | None = None

    for attempt in range(max_retries):
        if is_cancelled is not None and is_cancelled():
            raise GenerationCancelled()
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

        correction_scope = new_operation_scope(
            owner,
            kind="correction",
            supersedes_operation_id=previous_correction_operation_id,
        )
        previous_correction_operation_id = correction_scope.operation_id
        emit_stage(
            obs, "corrector", "correct", "start",
            retry=attempt + 1, question_id=question_id,
            scope=correction_scope,
        )
        decisions: list[CorrectionDecision] = []
        corrected = _call_with_optional_scope(
            spec.correct_fn,
            client, question, question.verification,
            chart_image_path=chart_image_path,
            curriculum_context=curriculum_context,
            on_decision=decisions.append,
            scope=correction_scope,
        )
        decision = decisions[-1] if decisions else None
        rejected = decision is not None and decision.outcome == "rejected"
        if rejected:
            reason = decision.reason
            emit_stage(
                obs, "corrector", "correct", "error", retry=attempt + 1,
                question_id=question_id, code="correction_rejected",
                message=reason.message,
                reason=reason.model_dump(),
                scope=correction_scope,
            )
        else:
            question = corrected
            emit_stage(
                obs, "corrector", "correct", "end",
                retry=attempt + 1, question_id=question_id,
                scope=correction_scope,
            )
            _emit_update(on_question_update, question, "corrected")

        new_chart_image_path: str | None = None
        if rejected:
            new_chart_image_path = chart_image_path
        else:
            if question.chart_spec and question.chart_spec != prior_chart_spec:
                img_path = config.output_dir / f"{question_id}.png"
                print(f"  Chart spec changed; re-rendering image: {img_path}", file=sys.stderr)
                image_scope = new_operation_scope(
                    owner,
                    kind="image",
                    supersedes_operation_id=previous_image_operation_id,
                )
                previous_image_operation_id = image_scope.operation_id
                _on_render_error, _render_failed = make_render_error_sink(obs, scope=image_scope)
                emit_stage(obs, "image_agent", "render_image", "start", scope=image_scope)
                rendered = render_image(
                    question.chart_spec.model_dump(),
                    img_path,
                    question_text=spec.image_question_text_fn(question),
                    html_renderer=html_renderer,
                    llm_client=client,
                    image_generation_mode=image_generation_mode,
                    on_error=_on_render_error,
                    scope=image_scope,
                )
                if not _render_failed:
                    emit_stage(obs, "image_agent", "render_image", "end", scope=image_scope)
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
                visual_policy_scope = new_operation_scope(
                    owner,
                    kind="image_policy",
                    supersedes_operation_id=previous_image_operation_id,
                )
                _call_with_optional_scope(
                    spec.post_correction_visual_policy_fn,
                    question,
                    config,
                    client,
                    html_renderer,
                    image_generation_mode,
                    obs,
                    params,
                    on_figure_policy_entry=_scoped_callback(
                        on_figure_policy_entry,
                        visual_policy_scope,
                    ),
                    scope=visual_policy_scope,
                )
                if question.圖片:
                    new_chart_image_path = str(config.output_dir / question.圖片)

        _emit_correction_trail(
            on_trail_entry,
            question_id,
            question,
            attempt + 1,
            config.model_correct or config.model_execute,
            decision,
            scope=correction_scope,
        )

        if not skip_verify:
            verify_scope = new_operation_scope(
                owner,
                kind="verify",
                supersedes_operation_id=previous_verify_operation_id,
            )
            previous_verify_operation_id = verify_scope.operation_id
            emit_stage(
                obs,
                "verifier",
                "verify",
                "start",
                retry=attempt + 1,
                scope=verify_scope,
            )
            result = _call_with_optional_scope(
                spec.verify_fn,
                client, question,
                chart_image_path=new_chart_image_path,
                curriculum_context=curriculum_context,
                scope=verify_scope,
            )
            emit_stage(
                obs,
                "verifier",
                "verify",
                "end",
                retry=attempt + 1,
                scope=verify_scope,
            )
            question.verification = result
            _emit_trail(
                on_trail_entry,
                question_id,
                result,
                config.model_verify or config.model_execute,
                scope=verify_scope,
            )
            _emit_update(on_question_update, question, "verified")
            status = "PASSED" if result.passed else "FAILED"
            print(f"  Re-verification {status}: {result.details[:100]}", file=sys.stderr)

    return question
