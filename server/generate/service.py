"""SSE streaming wrapper around subject-specific generate_with_corrections functions.

Each request runs concurrently in its own ThreadPoolExecutor thread with its own
LLMObserver, so multiple questions can generate in parallel.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import itertools
import json
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime
from typing import Any

import anyio

from server.config import ServerConfig
from server.db import AsyncSessionLocal
from server.generate.drain import get_drain
from server.generate.event_protocol import QuestionTerminalPayload
from server.generate.marshalling import (
    SSEEventName,
    make_combined_observer,
    make_publisher_observer,
    make_publisher_pipeline_emitter,
    make_publisher_trail_emitter,
    question_to_event,
)
from server.generate.models import (
    GenerateParams,
    build_sse_error,
)
from server.generate.persistence import (
    make_exchange_recorder,
    make_figure_policy_trail_recorder,
    make_reference_example_record_recorder,
    persist_generation_record,
)
from server.generate.publisher import GenerationPublisher
from server.generate.snapshot_ledger import QuestionSnapshotLedger
from server.generate.subjects import (
    SUBJECTS,
    SubjectSpec,
    resolved_payload_for_index,
)
from server.observability import record_generation_outcome
from src.common.generation_core import GenerationCancelled
from src.common.generation_events import QuestionContext, allocate_manifest, new_run_id
from src.llm_client import LLMClient

logger = logging.getLogger(__name__)

# How long to wait for a pooled renderer before emitting a WARNING.
# Lowered in tests via monkeypatch.
RENDERER_POOL_WAIT_WARN_THRESHOLD_S: float = 5.0


def _resolved_worker_params(
    i: int,
    params: GenerateParams,
    spec: SubjectSpec,
    overrides: dict,
) -> Any:
    """Convert one resolver-completed payload for a submit/preview worker."""
    payload = resolved_payload_for_index(params, i)
    return spec.params_from_resolved_payload(payload, overrides)


def _per_question_text_instruction(i: int, params: GenerateParams) -> str | None:
    """Return the effective text_instruction for worker i.

    A non-blank per_question_params[i].text_instruction (a 確認頁修改 override)
    takes precedence over the request-level params.text_instruction.  A blank or
    absent row value falls back to the request-level value.  (#637)
    """
    payload = resolved_payload_for_index(params, i)
    return payload.get("text_instruction") or params.text_instruction


def build_prompt_previews(
    params: GenerateParams,
    config: ServerConfig,
    app_state: Any,
) -> list[dict[str, Any]]:
    """Resolve parameters and build first-stage prompts without an LLM client."""
    spec = SUBJECTS[params.subject]
    overrides = spec.coerce_overrides(params, app_state)
    client_config = dataclasses.replace(
        config,
        model_execute=params.model_execute or config.model_execute,
        model_plan=params.model_plan or config.model_plan,
        model_verify=params.model_verify or config.model_verify,    # #375
        model_correct=params.model_correct or config.model_correct,  # #375
        effort_plan=params.effort_plan or config.effort_plan,
        effort_execute=params.effort_execute or config.effort_execute,
        effort_verify=params.effort_verify or config.effort_verify,   # #377
        effort_correct=params.effort_correct or config.effort_correct,  # #377
    )
    balanced_batch = params.coverage_mode == "balanced" and params.count > 1
    previews = []
    for i in range(max(1, params.count)):
        sampled = _resolved_worker_params(
            i,
            params,
            spec,
            overrides,
        )
        assert spec.build_generation_prompts is not None
        effective_ti = _per_question_text_instruction(i, params)
        system, user, _images = spec.build_generation_prompts(
            sampled,
            overrides,
            config=client_config,
            disable_reference_fewshot=params.disable_reference_fewshot,
            image_generation_mode=params.image_generation_mode,
            user_passage=params.passage,
            text_word_limit=params.text_word_limit,
            user_options=params.options,
            user_topic=params.topic,
            user_core_question=params.core_question,
            text_instruction=effective_ti,
            prior_scopes=[],
            balanced_batch=balanced_batch,
            core_question_callback=params.core_question_callback,
        )
        previews.append(
            {"index": i, "system_prompt": system, "user_prompt": user}
        )
        if spec.build_subquestion_prompt_previews is not None:
            for sub_idx, sub_system, sub_user, _sub_images in (
                spec.build_subquestion_prompt_previews(
                    sampled,
                    overrides,
                    config=client_config,
                    disable_reference_fewshot=params.disable_reference_fewshot,
                    image_generation_mode=params.image_generation_mode,
                    user_passage=params.passage,
                    user_options=params.options,
                    user_topic=params.topic,
                    user_core_question=params.core_question,
                    text_instruction=effective_ti,
                    prior_scopes=[],
                    core_question_callback=params.core_question_callback,
                )
            ):
                previews.append(
                    {
                        "index": i,
                        "subquestion_index": sub_idx,
                        "system_prompt": sub_system,
                        "user_prompt": sub_user,
                    }
                )
    return previews


def _decode_subquestion_configs(
    raw: str | None,
    on_error: Callable[[str], None] | None = None,
) -> list[dict] | None:
    """Decode social-studies per-subquestion configs from the GET query string."""
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"subquestion_configs JSON parse failed: {exc} — per-小題 配置已被忽略"
        logger.warning("subquestion_configs JSON parse failed, ignoring: %s", exc)
        if on_error is not None:
            on_error(msg)
        return None
    if not isinstance(decoded, list):
        msg = "subquestion_configs must be a JSON array — per-小題 配置已被忽略"
        logger.warning("subquestion_configs JSON must be an array, ignoring")
        if on_error is not None:
            on_error(msg)
        return None
    return [item for item in decoded if isinstance(item, dict)]


@dataclasses.dataclass(frozen=True)
class _RunContext:
    """Frozen bundle of per-request context threaded through _worker_one.

    ``prior_scopes`` is mutable (frozen prevents *reassignment*, not *mutation*).
    ``emit_pipeline`` / ``next_order`` are callables closed over their own state.
    """

    spec: SubjectSpec
    params: GenerateParams
    overrides: dict
    client_config: ServerConfig
    count: int
    base_seed: int | None
    max_retries: int
    timestamp: str
    html_renderer: Any
    decoded_subquestion_configs: list | None
    app_state: Any
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    prior_scopes: list  # mutated by workers; frozen prevents field reassignment only
    prior_scopes_lock: threading.Lock
    emit_pipeline: Any  # Callable[..., None] from make_pipeline_emitter
    generation_log_id: uuid.UUID | None
    figure_policy_recorder: Any
    reference_example_recorder: Any
    retention_days: int
    session_factory: Any
    next_order: Any  # Callable[[], int]
    config: ServerConfig
    balanced_batch: bool
    cancel_event: threading.Event
    run_id: str
    manifest: tuple[QuestionContext, ...]
    publisher: GenerationPublisher
    snapshot_ledger: QuestionSnapshotLedger
    drain_telemetry: Any


def _build_run_context(
    params: GenerateParams,
    config: ServerConfig,
    app_state: Any,
    *,
    spec: SubjectSpec,
    session_factory: Any,
    generation_log_id: uuid.UUID | None,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    html_renderer: Any,
    on_error: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
    publisher: GenerationPublisher | None = None,
    run_id: str | None = None,
) -> _RunContext:
    """Build the frozen per-request context from resolved collaborators."""
    overrides = spec.coerce_overrides(params, app_state)
    client_config = dataclasses.replace(
        config,
        model_execute=params.model_execute or config.model_execute,
        model_plan=params.model_plan or config.model_plan,
        model_verify=params.model_verify or config.model_verify,    # #375
        model_correct=params.model_correct or config.model_correct,  # #375
        effort_plan=params.effort_plan or config.effort_plan,
        effort_execute=params.effort_execute or config.effort_execute,
        effort_verify=params.effort_verify or config.effort_verify,   # #377
        effort_correct=params.effort_correct or config.effort_correct,  # #377
    )
    order_counter = itertools.count(1)
    order_lock = threading.Lock()
    balanced_batch = params.coverage_mode == "balanced" and params.count > 1
    _run_id = (
        run_id
        if run_id is not None
        else (str(generation_log_id) if generation_log_id is not None else new_run_id())
    )
    _manifest = allocate_manifest(spec.question_id_prefix, _run_id, max(1, params.count))
    _publisher = publisher if publisher is not None else GenerationPublisher(
        run_id=_run_id, loop=loop, queue=queue
    )
    _snapshot_ledger = QuestionSnapshotLedger()
    figure_policy_recorder = make_figure_policy_trail_recorder(
        generation_log_id=generation_log_id,
        loop=loop,
        session_factory=session_factory,
    )
    reference_example_recorder = make_reference_example_record_recorder(
        generation_log_id=generation_log_id,
        loop=loop,
        session_factory=session_factory,
        disabled=bool(params.disable_reference_fewshot),
    )

    def _next_order() -> int:
        with order_lock:
            return next(order_counter)

    return _RunContext(
        spec=spec,
        params=params,
        overrides=overrides,
        client_config=client_config,
        count=max(1, params.count),
        base_seed=params.seed,
        max_retries=params.max_retries,
        timestamp=datetime.now().strftime("%Y%m%d_%H%M%S"),
        html_renderer=html_renderer,
        decoded_subquestion_configs=_decode_subquestion_configs(
            params.subquestion_configs,
            on_error=on_error,
        ),
        app_state=app_state,
        loop=loop,
        queue=queue,
        prior_scopes=[],
        prior_scopes_lock=threading.Lock(),
        emit_pipeline=make_publisher_pipeline_emitter(_publisher, _manifest),
        generation_log_id=generation_log_id,
        figure_policy_recorder=figure_policy_recorder,
        reference_example_recorder=reference_example_recorder,
        retention_days=config.llm_exchange_retention_days,
        session_factory=session_factory,
        next_order=_next_order,
        config=config,
        balanced_batch=balanced_batch,
        cancel_event=cancel_event if cancel_event is not None else threading.Event(),
        run_id=_run_id,
        manifest=_manifest,
        publisher=_publisher,
        snapshot_ledger=_snapshot_ledger,
        drain_telemetry=get_drain(app_state),
    )


def _build_question_terminal_payload(
    *,
    question_id: str,
    termination_reason: str,
    has_final: bool,
    final_revision: int | None,
    question: Any | None,
    params: GenerateParams,
    output_dir: Any,  # Path | None
    unknown_reason: str | None = None,
) -> dict[str, Any]:
    """Build a QuestionTerminalPayload dict; validated before returning.

    On any validation failure, returns a minimal 'unknown' delivery payload
    so the worker never crashes.

    Spec notes:
    - grouped subjects (SS/NS) get expected=[] for now (fixed slots are #744).
    - operation/call ids are #743; sibling-independent error handling is #747.
    """
    from pathlib import Path as _Path

    # --- review ---
    if not has_final:
        review: dict[str, Any] = {
            "status": "unknown",
            "reason": unknown_reason or "no final content",
        }
    elif params.skip_verify:
        review = {
            "status": "skipped",
            "content_revision": final_revision,
        }
    elif question is not None and getattr(question, "verification", None) is not None:
        passed = question.verification.passed
        review = {
            "status": "passed" if passed else "failed",
            "content_revision": final_revision,
        }
    else:
        review = {
            "status": "unknown",
            "reason": "no verification evidence",
            "content_revision": final_revision,
        }

    # --- image slots (flat math only; #744 will handle grouped slots) ---
    expected: list[dict] = []
    delivered: list[dict] = []
    missing: list[dict] = []

    if has_final and question is not None:
        # An image slot exists when the pipeline adopted an image
        # (i.e. chart_spec or image_spec is non-None on the final question)
        has_image_spec = (
            getattr(question, "chart_spec", None) is not None
            or getattr(question, "image_spec", None) is not None
        )
        # Also check 圖片 field — it's set when pipeline wrote the PNG path
        img_filename: str | None = getattr(question, "圖片", None)

        if has_image_spec or img_filename:
            slot = {"kind": "image", "question_id": question_id, "subquestion_id": None}
            expected.append(slot)
            if img_filename and output_dir is not None:
                img_path = _Path(output_dir) / img_filename
                if img_path.exists():
                    delivered.append(slot)
                else:
                    missing.append(slot)
            else:
                missing.append(slot)

    # --- delivery_status ---
    if not has_final:
        if termination_reason == "cancelled":
            delivery_status = "unknown"
        else:
            delivery_status = "none"
    elif missing:
        delivery_status = "partial"
    else:
        delivery_status = "complete"

    raw_payload: dict[str, Any] = {
        "termination_reason": termination_reason,
        "has_final": has_final,
        "final_revision": final_revision,
        "delivery_status": delivery_status,
        "expected": expected,
        "delivered": delivered,
        "missing": missing,
        "review": review,
    }
    if unknown_reason is not None:
        raw_payload["unknown_reason"] = unknown_reason

    try:
        QuestionTerminalPayload.model_validate(raw_payload)
        return raw_payload
    except Exception as exc:  # ValidationError
        logger.warning(
            "question_terminal validation failed for %s (%s): %s",
            question_id,
            termination_reason,
            exc,
        )
        # Fall back to a minimal unknown-delivery terminal
        fallback: dict[str, Any] = {
            "termination_reason": termination_reason,
            "has_final": False,
            "final_revision": None,
            "delivery_status": "unknown",
            "expected": [],
            "delivered": [],
            "missing": [],
            "review": {"status": "unknown", "reason": "terminal evidence inconsistent"},
            "unknown_reason": "terminal evidence inconsistent",
        }
        return fallback


def _worker_one(
    i: int,
    question_client: LLMClient,
    ctx: _RunContext,
    batch_briefs: list,
) -> None:
    """Execute one question-generation worker; enqueues result/error events."""
    with ctx.drain_telemetry.ctx_active_worker():
        _worker_one_body(i, question_client, ctx, batch_briefs)


def _worker_one_body(
    i: int,
    question_client: LLMClient,
    ctx: _RunContext,
    batch_briefs: list,
) -> None:
    """Run the v2 worker body inside the drain telemetry wrapper."""
    worker_recorder = make_exchange_recorder(
        generation_log_id=ctx.generation_log_id,
        retention_days=ctx.retention_days,
        loop=ctx.loop,
        session_factory=ctx.session_factory,
        next_order=ctx.next_order,
    )
    figure_policy_recorder = ctx.figure_policy_recorder
    reference_example_recorder = ctx.reference_example_recorder
    question_client.set_observer(
        make_combined_observer(
            make_publisher_observer(ctx.publisher, ctx.manifest[i]),
            worker_recorder,
        )
    )
    # Wrap emit_question_update to commit to the snapshot ledger and carry
    # content_revision in every question_update context (slice 5).
    _revision_tracker: list[int] = [0]  # mutable container so the closure can write back

    def emit_question_update(question: Any, phase: str) -> None:
        q_dict = json.loads(question.model_dump_json(exclude_none=True))
        rev, _ = ctx.snapshot_ledger.commit(q_dict, ctx.config.output_dir)
        _revision_tracker[0] = rev
        _upd_payload: dict[str, Any] = {
            "index": ctx.manifest[i].index,
            "phase": phase,
            "question": question_to_event(question, ctx.config),
        }
        ctx.publisher.publish(
            SSEEventName.QUESTION_UPDATE,
            question_id=ctx.manifest[i].question_id,
            index=ctx.manifest[i].index,
            content_revision=rev,
            payload=_upd_payload,
        )

    emit_trail_entry = make_publisher_trail_emitter(ctx.publisher, ctx.manifest[i])
    verification_trail: list[dict[str, Any]] = []
    figure_policy_trail: list[dict[str, Any]] = []
    reference_example_entries: list[dict[str, Any]] = []

    def capture_trail_entry(entry: Any) -> None:
        payload = (
            entry.model_dump(mode="json")
            if hasattr(entry, "model_dump")
            else entry
        )
        verification_trail.append(payload)
        emit_trail_entry(entry)

    def capture_figure_policy_entry(entry: Any) -> None:
        payload = (
            entry.model_dump(mode="json")
            if hasattr(entry, "model_dump")
            else entry
        )
        figure_policy_trail.append(payload)
        emit_trail_entry(entry)
        if figure_policy_recorder is not None:
            figure_policy_recorder(entry)

    def capture_reference_example_entry(entry: Any) -> None:
        payload = (
            entry.model_dump(mode="json")
            if hasattr(entry, "model_dump")
            else entry
        )
        reference_example_entries.append(payload)
        emit_trail_entry(entry)
        if reference_example_recorder is not None:
            reference_example_recorder(entry)

    ctx.emit_pipeline("question_start", index=i, total=ctx.count)
    with ctx.prior_scopes_lock:
        prior_snapshot = list(ctx.prior_scopes)
    _terminal_status = "failed"  # updated before each exit
    try:
        rng_params = _resolved_worker_params(
            i,
            ctx.params,
            ctx.spec,
            ctx.overrides,
        )

        # Site 2: apply creative brief when available (SS only in practice)
        if i < len(batch_briefs) and batch_briefs[i] is not None:
            rng_params = rng_params.model_copy(
                update={"creative_brief": batch_briefs[i]},
            )

        # Site 3: generate via registry (replaces if/elif generate calls)
        question_id = ctx.manifest[i].question_id
        question = ctx.spec.do_generate(
            rng_params,
            ctx.overrides,
            config=ctx.client_config,
            client=question_client,
            question_id=question_id,
            max_retries=ctx.max_retries,
            skip_verify=ctx.params.skip_verify,
            disable_reference_fewshot=ctx.params.disable_reference_fewshot,
            html_renderer=ctx.html_renderer,
            image_generation_mode=ctx.params.image_generation_mode,
            user_passage=ctx.params.passage,
            text_word_limit=ctx.params.text_word_limit,
            user_options=ctx.params.options,
            user_topic=ctx.params.topic,
            user_core_question=ctx.params.core_question,
            text_instruction=_per_question_text_instruction(i, ctx.params),
            core_question_callback=ctx.params.core_question_callback,
            on_question_update=emit_question_update,
            on_trail_entry=None if ctx.params.skip_verify else capture_trail_entry,
            on_figure_policy_entry=capture_figure_policy_entry,
            on_reference_example_entry=capture_reference_example_entry,
            prior_scopes=prior_snapshot,
            balanced_batch=ctx.balanced_batch,
            is_cancelled=ctx.cancel_event.is_set,
        )

        # Site 4: metadata patching (SS only; other specs have patch_metadata=None)
        if ctx.spec.patch_metadata is not None:
            question = ctx.spec.patch_metadata(
                question,
                ctx.params.coverage_mode,
                getattr(rng_params, "target_surface", None),
            )

        assert isinstance(question, ctx.spec.exam_question_cls)

        # Site 5: prior-scope extraction via registry
        new_scope = ctx.spec.extract_prior_scope(question)
        if new_scope is not None:
            with ctx.prior_scopes_lock:
                ctx.prior_scopes.append(new_scope)
        ctx.emit_pipeline("question_end", index=i, total=ctx.count)
        record_generation_outcome(ctx.params.subject, "success")
        sidecars: dict[str, Any] = {
            "reference_example_record": {
                "disabled": bool(ctx.params.disable_reference_fewshot),
                "entries": reference_example_entries,
            },
        }
        if verification_trail:
            sidecars["verification_trail"] = verification_trail
        if figure_policy_trail:
            sidecars["figure_policy_trail"] = figure_policy_trail
        # Commit the final question to the ledger (unchanged content keeps revision).
        _q_final_dict = json.loads(question.model_dump_json(exclude_none=True))
        _final_revision, _ = ctx.snapshot_ledger.commit(
            _q_final_dict, ctx.config.output_dir
        )
        _revision_tracker[0] = _final_revision
        ctx.publisher.publish(
            SSEEventName.RESULT,
            question_id=question_id,
            index=i,
            content_revision=_final_revision,
            payload=question_to_event(question, ctx.config),
            sidecars=sidecars,
        )
        # Normal terminal – published AFTER the result event.
        _terminal_payload = _build_question_terminal_payload(
            question_id=question_id,
            termination_reason="normal",
            has_final=True,
            final_revision=_final_revision,
            question=question,
            params=ctx.params,
            output_dir=ctx.config.output_dir,
        )
        ctx.publisher.publish(
            SSEEventName.QUESTION_TERMINAL,
            question_id=question_id,
            index=i,
            payload=_terminal_payload,
        )
    except GenerationCancelled:
        # Client disconnected; exit cleanly without emitting an error event.
        _qid_cancel = ctx.manifest[i].question_id
        _cancel_payload = _build_question_terminal_payload(
            question_id=_qid_cancel,
            termination_reason="cancelled",
            has_final=False,
            final_revision=None,
            question=None,
            params=ctx.params,
            output_dir=ctx.config.output_dir,
            unknown_reason="cancelled before completion",
        )
        ctx.publisher.publish(
            SSEEventName.QUESTION_TERMINAL,
            question_id=_qid_cancel,
            index=i,
            payload=_cancel_payload,
        )
    except Exception as exc:
        record_generation_outcome(ctx.params.subject, "failure")
        ctx.publisher.publish(
            SSEEventName.ERROR,
            question_id=question_id,
            index=i,
            payload=build_sse_error(
                "generation_failed",
                f"Question generation failed ({type(exc).__name__})",
            ),
        )
        logger.exception("worker_one error (index=%d)", i)
        _failed_payload = _build_question_terminal_payload(
            question_id=question_id,
            termination_reason="failed",
            has_final=False,
            final_revision=None,
            question=None,
            params=ctx.params,
            output_dir=ctx.config.output_dir,
            unknown_reason="no final content",
        )
        ctx.publisher.publish(
            SSEEventName.QUESTION_TERMINAL,
            question_id=question_id,
            index=i,
            payload=_failed_payload,
        )


async def generate_question_stream(
    params: GenerateParams,
    config: ServerConfig,
    app_state: Any,
    user_id: uuid.UUID | None = None,
    generation_log_id: uuid.UUID | None = None,
    *,
    subjects: Mapping[str, SubjectSpec] | None = None,
    session_factory: Any = None,
    client_factory: Callable[..., LLMClient] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding SSE event dicts for one or more questions.

    Injectable collaborators (keyword-only, all default to production singletons):
      subjects        — the subject-spec registry; defaults to SUBJECTS.
      session_factory — async session maker; defaults to AsyncSessionLocal.
      client_factory  — LLMClient constructor; defaults to LLMClient.
    """
    _subjects = subjects if subjects is not None else SUBJECTS
    _session_factory = session_factory if session_factory is not None else AsyncSessionLocal
    _client_factory = client_factory if client_factory is not None else LLMClient

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _drain = get_drain(app_state)
    _drain.register_queue(queue)
    _drain._inc("_active_runs")
    renderer_pool = getattr(app_state, "renderer_pool", None)

    # Per-render lease: a renderer is borrowed only for the duration of one HTML
    # render call, then returned immediately.  The pool is never held for the
    # lifetime of the stream, so an aborted run releases its renderer within one
    # render call, not when its worker thread exits (issue #700 option 2).
    # The cancel_event is created here so it can be shared with the lease object
    # before _build_run_context is called.
    _run_id = str(generation_log_id) if generation_log_id is not None else new_run_id()
    _publisher = GenerationPublisher(run_id=_run_id, loop=loop, queue=queue)
    _cancel_event = threading.Event()
    if renderer_pool is not None:
        from server.generate.renderer_lease import RendererLease  # noqa: PLC0415
        html_renderer: Any = RendererLease(
            renderer_pool,
            loop,
            _cancel_event,
            queue,
            publisher=_publisher,
            drain_telemetry=_drain,
        )
    else:
        html_renderer = None

    signal_task: asyncio.Task[None] | None = None
    config.output_dir.mkdir(parents=True, exist_ok=True)
    spec = _subjects[params.subject]

    _sq_config_error_msgs: list[str] = []

    def _collect_sq_config_error(msg: str) -> None:
        _sq_config_error_msgs.append(msg)

    ctx = _build_run_context(
        params, config, app_state,
        spec=spec,
        session_factory=_session_factory,
        generation_log_id=generation_log_id,
        loop=loop,
        queue=queue,
        html_renderer=html_renderer,
        on_error=_collect_sq_config_error,
        cancel_event=_cancel_event,
        publisher=_publisher,
        run_id=_run_id,
    )

    ctx.publisher.publish(
        SSEEventName.STARTED,
        payload={
            "protocol_version": 2,
            "total": ctx.count,
            "questions": [
                {"index": qc.index, "question_id": qc.question_id}
                for qc in ctx.manifest
            ],
            "generation_log_id": str(generation_log_id) if generation_log_id is not None else None,
        },
    )
    await asyncio.sleep(0)
    yield queue.get_nowait()

    # Emit any deferred sq_config errors (collected during _build_run_context) via publisher.
    for _sq_msg in _sq_config_error_msgs:
        ctx.publisher.publish(
            SSEEventName.STAGE,
            payload={
                "type": "stage",
                "agent": "generator",
                "stage": "subquestion_configs",
                "status": "error",
                "message": _sq_msg,
                "ts": time.time(),
            },
        )

    # Site 2 (creative-brief / coverage planning): delegated to spec.
    # SS: plans briefs when creative_planning=True; returns [None]*count otherwise.
    # Math / NS: always returns [] so the brief-application check is a no-op.
    # Run in a worker thread so a synchronous LLM planning call (e.g. Opus for
    # 社會領域 with creative_planning=True, ~14 s) does not block the event loop
    # and freeze pings, /health, and other requests (issue #701).
    ctx.publisher.publish(
        SSEEventName.STAGE,
        payload={
            "type": "stage",
            "agent": "planner",
            "stage": "batch_briefs",
            "status": "start",
            "ts": time.time(),
        },
    )

    # The planner uses the same exchange order allocator as workers.  Its
    # observer must be installed before the provider call so request,
    # reasoning, content and response events are both streamed and paired for
    # persistence.  A disabled retention policy returns None while leaving the
    # SSE half of the combined observer active.
    planner_recorder = make_exchange_recorder(
        generation_log_id=ctx.generation_log_id,
        retention_days=ctx.retention_days,
        loop=ctx.loop,
        session_factory=ctx.session_factory,
        next_order=ctx.next_order,
    )
    planner_events_enabled = True
    _planner_publisher_observer = make_publisher_observer(ctx.publisher, None)

    def _planner_queue_observer(event: dict[str, Any]) -> None:
        # Once the stream is cancelled/closed, preserve recorder callbacks for
        # a late response but stop enqueueing events that no consumer can read.
        if planner_events_enabled:
            _planner_publisher_observer(event)

    planner_observer = make_combined_observer(
        _planner_queue_observer, planner_recorder,
    )
    planning_task = asyncio.create_task(asyncio.to_thread(
        functools.partial(
            spec.plan_all_batch_briefs,
            params, ctx.count, ctx.base_seed, ctx.overrides, ctx.client_config,
            ctx.client_config.creative_planning, ctx.decoded_subquestion_configs,
            client_factory=_client_factory,
            observer=planner_observer,
        )
    ))

    async def _cleanup_planning() -> None:
        nonlocal planner_events_enabled
        planner_events_enabled = False
        ctx.cancel_event.set()
        # Cancelling asyncio.to_thread's wrapper does not stop a provider call
        # already running in its executor thread.  It does release the stream
        # immediately, while the still-live observer/recorder closure can pair
        # and persist that provider's eventual response.
        with anyio.CancelScope(shield=True):
            planning_task.cancel()
            await asyncio.gather(planning_task, return_exceptions=True)

    try:
        # Consume observer events while the synchronous planner remains in its
        # worker thread.  The queue-get task is always cancelled and awaited
        # when the planner wins the race, so a completed or cancelled stream
        # never leaves an orphaned consumer behind.
        while True:
            queue_get_task = asyncio.create_task(queue.get())
            try:
                done, _pending = await asyncio.wait(
                    {planning_task, queue_get_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except BaseException:
                queue_get_task.cancel()
                await asyncio.gather(queue_get_task, return_exceptions=True)
                raise

            if queue_get_task in done:
                yield queue_get_task.result()
                continue

            queue_get_task.cancel()
            await asyncio.gather(queue_get_task, return_exceptions=True)
            # Observer callbacks use call_soon_threadsafe.  Give those
            # callbacks one event-loop turn after the thread reports done,
            # then drain every planner event before the stage-end marker.
            await asyncio.sleep(0)
            while not queue.empty():
                yield queue.get_nowait()
            batch_briefs = await planning_task
            break
    except asyncio.CancelledError:
        # Cancelling the asyncio wrapper around to_thread does not stop the
        # provider thread.  Release the stream immediately; its still-live
        # observer/recorder closure can pair and persist a late response, while
        # the cancel flag prevents any worker submission after planning exits.
        await _cleanup_planning()
        raise
    except GeneratorExit:
        # ``aclose()`` injects GeneratorExit at the current yield.  Treat it as
        # a clean stream close while the provider can finish recording.
        await _cleanup_planning()
        return
    except BaseException:
        await _cleanup_planning()
        raise
    finally:
        # Success reaches this finally after the planner task and every queued
        # planner event have been consumed; cancellation paths have already
        # disabled the gate in _cleanup_planning().
        planner_events_enabled = False

    ctx.publisher.publish(
        SSEEventName.STAGE,
        payload={
            "type": "stage",
            "agent": "planner",
            "stage": "batch_briefs",
            "status": "end",
            "ts": time.time(),
        },
    )

    # Guard: if the request was cancelled while planning ran in its thread
    # (e.g. the client disconnected), do not submit workers.  This is an extra
    # safety net; CancelledError during the await above already prevents reaching
    # this line in the normal asyncio cancellation path.
    if ctx.cancel_event.is_set():
        return

    ctx.emit_pipeline("pipeline_start", total=ctx.count)
    question_clients = [_client_factory(ctx.client_config) for _ in range(ctx.count)]
    futures = [
        loop.run_in_executor(
            None, functools.partial(_worker_one, i, question_clients[i], ctx, batch_briefs),
        )
        for i in range(ctx.count)
    ]

    async def _wait_and_signal() -> None:
        await asyncio.gather(*futures, return_exceptions=True)
        ctx.emit_pipeline("pipeline_end", total=ctx.count)
        ctx.publisher.publish(SSEEventName.DONE, payload={})

    signal_task = asyncio.create_task(_wait_and_signal())
    try:
        while True:
            event = await queue.get()
            # v2 envelopes use {context, payload} shape — no top-level "event" key.
            # Route them through unchanged; persistence and stop-sentinel checks
            # operate only on v1 events.
            event_name = event.get("event")
            if (
                event_name == SSEEventName.RESULT
                and user_id is not None
                and isinstance(event.get("payload"), dict)
            ):
                await persist_generation_record(
                    user_id=user_id,
                    generation_log_id=generation_log_id,
                    subject=params.subject,
                    params=params,
                    payload=event["payload"],
                    session_factory=_session_factory,
                    verification_trail_json=event.get("verification_trail"),
                    figure_policy_trail_json=event.get("figure_policy_trail"),
                    reference_example_record_json=event.get("reference_example_record"),
                )
            yield event
            if event_name in (SSEEventName.DONE, SSEEventName.ERROR):
                break
    finally:
        ctx.cancel_event.set()
        # Shield the inner cleanup from anyio/asyncio cancellation so that a
        # client disconnect cannot interrupt await signal_task.  Without the
        # shield, CancelledError is raised there and the inner finally exits
        # early before flush() runs.  The renderer is no longer returned here
        # (per-render lease; see RendererLease.render()).
        with anyio.CancelScope(shield=True):
            try:
                await signal_task
            finally:
                if ctx.figure_policy_recorder is not None:
                    await ctx.figure_policy_recorder.flush()
                if ctx.reference_example_recorder is not None:
                    await ctx.reference_example_recorder.flush()
            _drain.unregister_queue(queue)
            _drain._dec("_active_runs")
