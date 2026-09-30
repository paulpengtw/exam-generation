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
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

import anyio
from pydantic import ValidationError

from server.config import ServerConfig
from server.db import AsyncSessionLocal
from server.generate.drain import get_drain
from server.generate.event_protocol import QuestionTerminalPayload, StartedPayload
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
    SAVE_MAX_ATTEMPTS,
    make_exchange_recorder,
    make_figure_policy_trail_recorder,
    make_reference_example_record_recorder,
    persist_generation_record,
)
from server.generate.publisher import GenerationPublisher
from server.generate.question_terminal import (
    _compute_delivery_status,
    _compute_expected_delivered_missing,
    _compute_review,
    _QuestionPositionResolution,
)
from server.generate.snapshot_ledger import QuestionSnapshotLedger
from server.generate.subjects import (
    SUBJECTS,
    SubjectSpec,
    _scoped_client,
    resolved_payload_for_index,
)
from server.observability import record_generation_outcome
from src.common.generation_core import GenerationCancelled
from src.common.generation_events import (
    QuestionContext,
    RunContext,
    allocate_manifest,
    new_operation_scope,
    new_run_id,
)
from src.llm_client import LLMClient

logger = logging.getLogger(__name__)

# How long to wait for a pooled renderer before emitting a WARNING.
# Lowered in tests via monkeypatch.
RENDERER_POOL_WAIT_WARN_THRESHOLD_S: float = 5.0

# How long the worker thread waits for the per-question save coroutine to
# complete before giving up and publishing RESULT without a saved record.
# With SAVE_MAX_ATTEMPTS=3 and 2**0+2**1=3 s total backoff the save budget is
# well under 30 s on any reasonable DB.
_SAVE_TIMEOUT_S: float = 30.0
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
                        # subquestion_index is zero-based (0..N-1), matching the SSE stream
                        # convention. The frontend adds +1 to display as 第1小題..第N小題.
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
    exchange_recorders: list[Any]
    exchange_recorders_lock: threading.Lock
    retention_days: int
    session_factory: Any
    next_order: Any  # Callable[[], int]
    config: ServerConfig
    balanced_batch: bool
    cancel_event: threading.Event
    confirmed_cancel_event: threading.Event
    run_id: str
    manifest: tuple[QuestionContext, ...]
    publisher: GenerationPublisher
    snapshot_ledger: QuestionSnapshotLedger
    drain_telemetry: Any
    # issue #904: save-before-RESULT fields
    user_id: uuid.UUID | None  # None → no persistence (CLI / log-less runs)
    save_backoff_fn: Callable[[int], Awaitable[Any]] | None  # None → default exponential backoff
    # issue #911: resume support — question IDs already ended in a prior attempt
    skip_question_ids: frozenset  # frozenset[str]; empty on first attempt


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
    confirmed_cancel_event: threading.Event | None = None,
    user_id: uuid.UUID | None = None,
    save_backoff_fn: Callable[[int], Awaitable[Any]] | None = None,
    skip_question_ids: frozenset | None = None,
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
        exchange_recorders=[],
        exchange_recorders_lock=threading.Lock(),
        retention_days=config.llm_exchange_retention_days,
        session_factory=session_factory,
        next_order=_next_order,
        config=config,
        balanced_batch=balanced_batch,
        cancel_event=cancel_event if cancel_event is not None else threading.Event(),
        confirmed_cancel_event=(
            confirmed_cancel_event
            if confirmed_cancel_event is not None
            else threading.Event()
        ),
        run_id=_run_id,
        manifest=_manifest,
        publisher=_publisher,
        snapshot_ledger=_snapshot_ledger,
        drain_telemetry=get_drain(app_state),
        user_id=user_id,
        save_backoff_fn=save_backoff_fn,
        skip_question_ids=skip_question_ids if skip_question_ids is not None else frozenset(),
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
    resolution: _QuestionPositionResolution,
) -> dict[str, Any]:
    """Build a QuestionTerminalPayload dict; validated before returning.

    Thin composition point that delegates to three independently testable units:
      _compute_review, _compute_expected_delivered_missing, _compute_delivery_status.

    On any validation failure, returns a minimal 'unknown' delivery payload
    so the worker never crashes.
    """
    review = _compute_review(
        has_final=has_final,
        skip_verify=getattr(params, "skip_verify", False),
        question=question,
        final_revision=final_revision,
        unknown_reason=unknown_reason,
        verification_trail=resolution.verification_trail,
    )

    expected, delivered, missing = _compute_expected_delivered_missing(
        question_id=question_id,
        question=question,
        params=params,
        output_dir=output_dir,
        has_final=has_final,
        termination_reason=termination_reason,
        resolution=resolution,
    )

    delivery_status = _compute_delivery_status(
        has_final=has_final,
        termination_reason=termination_reason,
        missing=missing,
    )

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


def _publish_question_terminal(
    ctx: _RunContext,
    *,
    index: int,
    payload: dict[str, Any],
) -> None:
    """Seal ledger and publisher before delivering one terminal summary."""
    question = ctx.manifest[index]
    ctx.snapshot_ledger.seal_terminal(question.question_id, payload)
    ctx.publisher.publish(
        SSEEventName.QUESTION_TERMINAL,
        question_id=question.question_id,
        index=index,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Issue #858 – per-question worker split: setup, execution, shared finalize
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _WorkerRecorderSetup:
    """Bundle of per-question recording and trail-capture seams.

    Returned by _setup_worker_recorders.  The trail lists grow in-place during
    generation; the callable fields are closures that reference ctx and the
    lists.  Callers must NOT replace the list fields after construction.
    """

    emit_question_update: Any   # Callable[[Any, str], int]
    capture_trail_entry: Any    # Callable[..., None]
    capture_figure_policy_entry: Any    # Callable[..., None]
    capture_reference_example_entry: Any    # Callable[..., None]
    verification_trail: list    # list[dict[str, Any]] – mutated by capture_trail_entry
    figure_policy_trail: list   # list[dict[str, Any]] – mutated by capture_figure_policy_entry
    reference_example_entries: list  # list[dict[str, Any]] – mutated by capture_reference_example_entry  # noqa: E501


def _setup_worker_recorders(
    i: int,
    question_client: LLMClient,
    ctx: _RunContext,
) -> _WorkerRecorderSetup:
    """Create the exchange recorder, observer, and trail-capture callbacks for one worker.

    Registers the exchange recorder with ctx.exchange_recorders and wires the
    LLM observer onto question_client.  Returns a _WorkerRecorderSetup bundle
    that can be exercised in tests without running generation (issue #858
    acceptance criterion 2).
    """
    worker_recorder = make_exchange_recorder(
        generation_log_id=ctx.generation_log_id,
        retention_days=ctx.retention_days,
        loop=ctx.loop,
        session_factory=ctx.session_factory,
        next_order=ctx.next_order,
    )
    if worker_recorder is not None:
        with ctx.exchange_recorders_lock:
            ctx.exchange_recorders.append(worker_recorder)
    figure_policy_recorder = ctx.figure_policy_recorder
    reference_example_recorder = ctx.reference_example_recorder
    publisher_observer = make_publisher_observer(ctx.publisher, ctx.manifest[i])

    def observe_worker_event(event: dict[str, Any]) -> None:
        if event.get("type") == "plan":
            slots = event.get("slots")
            if isinstance(slots, list) and all(isinstance(slot, dict) for slot in slots):
                ctx.snapshot_ledger.record_slot_manifest(
                    ctx.manifest[i].question_id,
                    slots,
                )
        publisher_observer(event)

    question_client.set_observer(
        make_combined_observer(observe_worker_event, worker_recorder)
    )

    def emit_question_update(question: Any, phase: str) -> int:
        q_dict = json.loads(question.model_dump_json(exclude_none=True))
        rev, _ = ctx.snapshot_ledger.commit(q_dict, ctx.config.output_dir)
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
        return rev

    emit_trail_entry = make_publisher_trail_emitter(ctx.publisher, ctx.manifest[i])
    verification_trail: list[dict[str, Any]] = []
    figure_policy_trail: list[dict[str, Any]] = []
    reference_example_entries: list[dict[str, Any]] = []

    def capture_trail_entry(
        entry: Any,
        *,
        scope: Any = None,
        content_revision: int | None = None,
    ) -> None:
        if content_revision is not None and hasattr(entry, "model_copy"):
            entry = entry.model_copy(update={"content_revision": content_revision})
        payload = (
            entry.model_dump(mode="json")
            if hasattr(entry, "model_dump")
            else entry
        )
        verification_trail.append(payload)
        emit_trail_entry(entry, scope=scope)

    def capture_figure_policy_entry(
        entry: Any,
        *,
        scope: Any = None,
        content_revision: int | None = None,
    ) -> None:
        if content_revision is not None and hasattr(entry, "model_copy"):
            entry = entry.model_copy(update={"content_revision": content_revision})
        payload = (
            entry.model_dump(mode="json")
            if hasattr(entry, "model_dump")
            else entry
        )
        figure_policy_trail.append(payload)
        emit_trail_entry(entry, scope=scope)
        if figure_policy_recorder is not None:
            figure_policy_recorder(entry)

    def capture_reference_example_entry(entry: Any, *, scope: Any = None) -> None:
        payload = (
            entry.model_dump(mode="json")
            if hasattr(entry, "model_dump")
            else entry
        )
        reference_example_entries.append(payload)
        emit_trail_entry(entry, scope=scope)
        if reference_example_recorder is not None:
            reference_example_recorder(entry)

    return _WorkerRecorderSetup(
        emit_question_update=emit_question_update,
        capture_trail_entry=capture_trail_entry,
        capture_figure_policy_entry=capture_figure_policy_entry,
        capture_reference_example_entry=capture_reference_example_entry,
        verification_trail=verification_trail,
        figure_policy_trail=figure_policy_trail,
        reference_example_entries=reference_example_entries,
    )


def _finalize_worker_terminal(
    ctx: _RunContext,
    *,
    index: int,
    question_id: str,
    already_sealed: bool = False,
    termination_reason: str = "",
    has_final: bool = False,
    final_revision: int | None = None,
    question: Any | None = None,
    rng_params: Any | None = None,
    verification_trail: list[dict[str, Any]] | None = None,
    unknown_reason: str | None = None,
) -> None:
    """Shared finalize path: seals the ledger and emits question_terminal.

    Every terminal exit in _worker_one_body and _wait_and_signal routes here
    (issue #858 acceptance criterion 1).

    When already_sealed is True (ledger sealed but publisher not yet confirmed)
    the immutable sealed payload is re-sent without re-building or re-sealing
    the terminal.  The other parameters are ignored in that case.
    """
    if already_sealed:
        sealed_payload = ctx.snapshot_ledger.get_terminal(question_id)
        if sealed_payload is not None:
            try:
                ctx.publisher.publish(
                    SSEEventName.QUESTION_TERMINAL,
                    question_id=question_id,
                    index=index,
                    payload=sealed_payload,
                )
            except Exception as retry_exc:  # noqa: BLE001 — terminal remains sealed
                logger.warning(
                    "sealed terminal delivery failed for %s: %s",
                    question_id,
                    type(retry_exc).__name__,
                )
        return

    resolution = _QuestionPositionResolution(
        announced_slots=ctx.snapshot_ledger.get_slot_manifest(question_id),
        verification_trail=verification_trail,
        resolved_subquestion_configs=(
            getattr(rng_params, "subquestion_configs", None)
            if rng_params is not None
            else None
        ),
        resolved_subquestion_count=(
            getattr(rng_params, "sub_question_count", None)
            if rng_params is not None
            else None
        ),
        has_per_question_resolution=rng_params is not None,
    )
    payload = _build_question_terminal_payload(
        question_id=question_id,
        termination_reason=termination_reason,
        has_final=has_final,
        final_revision=final_revision,
        question=question,
        params=ctx.params,
        output_dir=ctx.config.output_dir,
        unknown_reason=unknown_reason,
        resolution=resolution,
    )
    _publish_question_terminal(ctx, index=index, payload=payload)


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
    """Run the v2 worker body inside the drain telemetry wrapper.

    Structured in three single-responsibility phases (issue #858):
      1. _setup_worker_recorders – recorder + observer + trail-capture setup.
      2. Generation execution    – resolves params, calls do_generate, publishes result.
      3. _finalize_worker_terminal – shared finalize path for every exit kind.
    """
    question_id = ctx.manifest[i].question_id
    if ctx.publisher.is_terminal_sealed(question_id):
        logger.warning("worker %s was submitted after terminal sealing", question_id)
        return

    # Phase 1 – recorder & trail-capture setup (testable without generation).
    setup = _setup_worker_recorders(i, question_client, ctx)

    # Phase 2 – generation execution.
    ctx.emit_pipeline("question_start", index=i, total=ctx.count)
    with ctx.prior_scopes_lock:
        prior_snapshot = list(ctx.prior_scopes)
    rng_params: Any | None = None
    question: Any | None = None
    final_published_revision: int | None = None
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
            on_question_update=setup.emit_question_update,
            on_trail_entry=None if ctx.params.skip_verify else setup.capture_trail_entry,
            on_figure_policy_entry=setup.capture_figure_policy_entry,
            on_reference_example_entry=setup.capture_reference_example_entry,
            prior_scopes=prior_snapshot,
            balanced_batch=ctx.balanced_batch,
            is_cancelled=ctx.cancel_event.is_set,
            question_context=ctx.manifest[i],
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
        # Commit the final question to the ledger (unchanged content keeps revision).
        _q_final_dict = json.loads(question.model_dump_json(exclude_none=True))
        _final_revision, _ = ctx.snapshot_ledger.commit(
            _q_final_dict, ctx.config.output_dir
        )
        _result_payload = question_to_event(question, ctx.config)
        # ---- issue #904: save-before-RESULT --------------------------------
        # Persist the generation record in this worker thread (before RESULT is
        # published) so a disconnected observer cannot cause the record to be lost.
        # The save runs on the event loop via run_coroutine_threadsafe; the worker
        # blocks on future.result(timeout) so the save completes before RESULT is
        # published.  Sidecars are consumed here and are no longer included in the
        # queue envelope.
        if ctx.user_id is not None:
            _reference_example_record_json: dict[str, Any] = {
                "disabled": bool(ctx.params.disable_reference_fewshot),
                "entries": setup.reference_example_entries,
            }
            _save_coro = persist_generation_record(
                user_id=ctx.user_id,
                generation_log_id=ctx.generation_log_id,
                subject=ctx.params.subject,
                params=ctx.params,
                payload=_result_payload,
                session_factory=ctx.session_factory,
                verification_trail_json=(
                    setup.verification_trail if setup.verification_trail else None
                ),
                figure_policy_trail_json=(
                    setup.figure_policy_trail if setup.figure_policy_trail else None
                ),
                reference_example_record_json=_reference_example_record_json,
                max_attempts=SAVE_MAX_ATTEMPTS,
                backoff_fn=ctx.save_backoff_fn,
                report_exhaustion=True,
            )
            try:
                _save_future = asyncio.run_coroutine_threadsafe(_save_coro, ctx.loop)
                try:
                    _save_future.result(timeout=_SAVE_TIMEOUT_S)
                except Exception as _save_exc:  # noqa: BLE001 — timeout or other bridge error
                    # Intentional: on timeout the save coroutine may still
                    # finish later (it is not cancelled). RESULT is published
                    # regardless so the worker never blocks indefinitely; the
                    # record will still land if the coroutine completes after
                    # the timeout window. See FLOW.md step 9.
                    logger.warning(
                        "save-before-RESULT failed for %s: %s",
                        question_id,
                        type(_save_exc).__name__,
                    )
            except Exception as _sched_exc:  # noqa: BLE001 — loop closed or other scheduling error
                _save_coro.close()
                logger.warning(
                    "save-before-RESULT scheduling failed for %s: %s",
                    question_id,
                    type(_sched_exc).__name__,
                )
        # Publish RESULT after the save (sidecars no longer in the envelope).
        ctx.publisher.publish(
            SSEEventName.RESULT,
            question_id=question_id,
            index=i,
            content_revision=_final_revision,
            payload=_result_payload,
        )
        final_published_revision = _final_revision
        # Phase 3 – normal terminal: published AFTER the result event.
        _finalize_worker_terminal(
            ctx,
            index=i,
            question_id=question_id,
            termination_reason="normal",
            has_final=True,
            final_revision=_final_revision,
            question=question,
            rng_params=rng_params,
            verification_trail=setup.verification_trail,
        )
    except GenerationCancelled:
        # A client disconnect is not proof that cancellation was confirmed by
        # the generation boundary.  Only an explicit internal confirmation may
        # produce the cancelled terminal conclusion.
        if not ctx.confirmed_cancel_event.is_set():
            return
        # Phase 3 – confirmed-cancellation terminal.
        _finalize_worker_terminal(
            ctx,
            index=i,
            question_id=ctx.manifest[i].question_id,
            termination_reason="cancelled",
            has_final=False,
            final_revision=None,
            question=None,
            rng_params=rng_params,
            verification_trail=None,
            unknown_reason="cancelled before completion",
        )
    except Exception as exc:
        if ctx.publisher.is_terminal_sealed(question_id):
            logger.warning(
                "worker %s raised after its terminal was sealed: %s",
                question_id,
                type(exc).__name__,
            )
            return
        if ctx.snapshot_ledger.is_terminal_sealed(question_id):
            # The ledger and publisher are separate guards.  If the publisher
            # failed after the ledger sealed, retry the exact immutable summary
            # once so a transient enqueue failure cannot turn a normal final
            # into a contradictory failure.  No new error event is emitted.
            # Phase 3 – resend of already-sealed summary.
            _finalize_worker_terminal(
                ctx,
                index=i,
                question_id=question_id,
                already_sealed=True,
            )
            return
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
        # Phase 3 – final-failure terminal.
        _finalize_worker_terminal(
            ctx,
            index=i,
            question_id=question_id,
            termination_reason="failed",
            has_final=final_published_revision is not None,
            final_revision=final_published_revision,
            question=question if final_published_revision is not None else None,
            rng_params=rng_params,
            verification_trail=setup.verification_trail,
            unknown_reason=(
                "no final content"
                if final_published_revision is None
                else "terminal completion failed after final delivery"
            ),
        )


def _track_active_run(
    stream_fn: Callable[..., AsyncIterator[dict[str, Any]]],
) -> Callable[..., AsyncIterator[dict[str, Any]]]:
    """Track the whole async stream, including all setup before its first yield."""

    @functools.wraps(stream_fn)
    async def tracked_stream(
        params: GenerateParams,
        config: ServerConfig,
        app_state: Any,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        drain = get_drain(app_state)
        with drain.ctx_active_run():
            inner_stream = stream_fn(
                params,
                config,
                app_state,
                *args,
                **kwargs,
            )
            try:
                async for event in inner_stream:
                    yield event
            finally:
                await inner_stream.aclose()

    return tracked_stream


@_track_active_run
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
    confirmed_cancel_event: threading.Event | None = None,
    skip_question_ids: frozenset | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding SSE event dicts for one or more questions.

    Injectable collaborators (keyword-only, all default to production singletons):
      subjects        — the subject-spec registry; defaults to SUBJECTS.
      session_factory — async session maker; defaults to AsyncSessionLocal.
      client_factory  — LLMClient constructor; defaults to LLMClient.
      confirmed_cancel_event — internal cancellation confirmation seam; unset
        for ordinary disconnects.
    """
    _subjects = subjects if subjects is not None else SUBJECTS
    _session_factory = session_factory if session_factory is not None else AsyncSessionLocal
    _client_factory = client_factory if client_factory is not None else LLMClient

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _drain = get_drain(app_state)
    _drain.register_queue(queue)
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
        confirmed_cancel_event=confirmed_cancel_event,
        publisher=_publisher,
        run_id=_run_id,
        user_id=user_id,
        skip_question_ids=skip_question_ids,
    )

    _started_payload: dict[str, Any] = {
        "protocol_version": 2,
        "total": ctx.count,
        "questions": [
            {"index": qc.index, "question_id": qc.question_id}
            for qc in ctx.manifest
        ],
        "generation_log_id": str(generation_log_id) if generation_log_id is not None else None,
    }
    try:
        StartedPayload.model_validate(_started_payload)
    except ValidationError as exc:
        logger.warning(
            "started payload validation failed; rejecting generation (%s)",
            type(exc).__name__,
        )
        ctx.publisher.publish(
            SSEEventName.ERROR,
            payload=build_sse_error("started_invalid", "generation manifest validation failed"),
        )
        await asyncio.sleep(0)
        yield queue.get_nowait()
        _drain.unregister_queue(queue)
        return

    ctx.publisher.publish(SSEEventName.STARTED, payload=_started_payload)
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
    planner_scope = new_operation_scope(
        RunContext(ctx.run_id),
        kind="batch_planner",
    )
    ctx.publisher.publish(
        SSEEventName.STAGE,
        operation_id=planner_scope.operation_id,
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
    if planner_recorder is not None:
        with ctx.exchange_recorders_lock:
            ctx.exchange_recorders.append(planner_recorder)
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
            operation_scope=planner_scope,
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

    batch_fatal_error: Exception | None = None
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
            try:
                batch_briefs = await planning_task
            except Exception as exc:  # noqa: BLE001 — batch failure is explicit below
                batch_fatal_error = exc
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

    if batch_fatal_error is None:
        ctx.publisher.publish(
            SSEEventName.STAGE,
            operation_id=planner_scope.operation_id,
            payload={
                "type": "stage",
                "agent": "planner",
                "stage": "batch_briefs",
                "status": "end",
                "ts": time.time(),
            },
        )
    else:
        ctx.publisher.publish(
            SSEEventName.STAGE,
            operation_id=planner_scope.operation_id,
            payload={
                "type": "stage",
                "agent": "planner",
                "stage": "batch_briefs",
                "status": "error",
                "message": f"Batch planning failed ({type(batch_fatal_error).__name__})",
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
    if batch_fatal_error is None:
        question_clients = [
            _scoped_client(_client_factory, ctx.client_config, ctx.manifest[i])
            for i in range(ctx.count)
        ]
        futures = []
        for i in range(ctx.count):
            qid = ctx.manifest[i].question_id
            # Issue #911: skip already-ended questions on resume.
            if qid in ctx.skip_question_ids:
                logger.debug("resume: skipping already-ended question %s", qid)
                continue
            futures.append(
                loop.run_in_executor(
                    None, functools.partial(_worker_one, i, question_clients[i], ctx, batch_briefs),
                )
            )
    else:
        futures = []

    async def _flush_generation_recorders() -> None:
        """Finish best-effort generation-log staging before publishing done."""
        with ctx.exchange_recorders_lock:
            exchange_recorders = tuple(ctx.exchange_recorders)
        recorders = tuple(
            recorder
            for recorder in (
                ctx.figure_policy_recorder,
                ctx.reference_example_recorder,
                *exchange_recorders,
            )
            if recorder is not None
        )
        outcomes = await asyncio.gather(
            *(recorder.flush() for recorder in recorders),
            return_exceptions=True,
        )
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                logger.warning("generation recorder flush failed: %s", type(outcome).__name__)
        # Publisher callbacks use call_soon_threadsafe; let the event loop run
        # them before the final pipeline/done markers are enqueued.
        await asyncio.sleep(0)

    async def _wait_and_signal() -> None:
        if batch_fatal_error is not None:
            ctx.publisher.publish(
                SSEEventName.ERROR,
                payload=build_sse_error(
                    "batch_generation_failed",
                    f"Batch planning failed ({type(batch_fatal_error).__name__})",
                ),
            )
            for i, question in enumerate(ctx.manifest):
                # Phase 3 – batch-planning-failure terminal (shared finalize path).
                _finalize_worker_terminal(
                    ctx,
                    index=i,
                    question_id=question.question_id,
                    termination_reason="failed",
                    has_final=False,
                    final_revision=None,
                    question=None,
                    rng_params=None,
                    verification_trail=None,
                    unknown_reason="batch failed before question generation",
                )
        else:
            outcomes = await asyncio.gather(*futures, return_exceptions=True)
            for i, outcome in enumerate(outcomes):
                if not isinstance(outcome, BaseException):
                    continue
                question = ctx.manifest[i]
                if ctx.publisher.is_terminal_sealed(question.question_id):
                    continue
                logger.error(
                    "question worker exited outside its boundary (index=%d, type=%s)",
                    i,
                    type(outcome).__name__,
                )
                ctx.publisher.publish(
                    SSEEventName.ERROR,
                    question_id=question.question_id,
                    index=i,
                    payload=build_sse_error(
                        "generation_failed",
                        f"Question generation failed ({type(outcome).__name__})",
                    ),
                )
                # Phase 3 – worker-unexpected-exit terminal (shared finalize path).
                _finalize_worker_terminal(
                    ctx,
                    index=i,
                    question_id=question.question_id,
                    termination_reason="failed",
                    has_final=False,
                    final_revision=None,
                    question=None,
                    rng_params=None,
                    verification_trail=None,
                    unknown_reason="question worker exited before final content",
                )
        await _flush_generation_recorders()
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
            # issue #904: persistence moved to _worker_one_body (save-before-RESULT).
            # Sidecars are no longer in the queue envelope.
            yield event
            # A question error is terminal only for that manifest slot.  Keep
            # draining the shared queue so sibling questions can still publish
            # their drafts, results, and terminals.
            if event_name == SSEEventName.DONE:
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
                if signal_task is not None:
                    await signal_task
            except Exception as exc:  # noqa: BLE001 — cleanup must continue
                logger.warning("generation signal cleanup failed: %s", type(exc).__name__)
            finally:
                try:
                    await _flush_generation_recorders()
                except Exception as exc:  # noqa: BLE001 — defensive cleanup boundary
                    logger.warning("generation recorder cleanup failed: %s", type(exc).__name__)
                _drain.unregister_queue(queue)
