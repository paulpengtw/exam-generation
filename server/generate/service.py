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

from server.config import ServerConfig
from server.db import AsyncSessionLocal
from server.generate.marshalling import (
    SSEEventName,
    make_combined_observer,
    make_pipeline_emitter,
    make_question_update_emitter,
    make_queue_observer,
    make_trail_emitter,
    question_to_event,
)
from server.generate.models import (
    GenerateParams,
    build_sse_error,
    decode_per_question_params,
)
from server.generate.persistence import make_exchange_recorder, persist_generation_record
from server.generate.subjects import SUBJECTS, SubjectSpec
from server.observability import record_generation_outcome
from src.llm_client import LLMClient

logger = logging.getLogger(__name__)


def _sample_worker_params(
    i: int,
    params: GenerateParams,
    spec: SubjectSpec,
    overrides: dict,
    decoded_subquestion_configs: list[dict] | None,
    decoded_per_question_params: list[dict[str, Any]] | None = None,
    app_state: Any = None,
) -> Any:
    """Resolve the sampled parameters for one submit/preview worker index."""
    worker_params = params
    worker_overrides = overrides
    worker_subquestion_configs = decoded_subquestion_configs
    if decoded_per_question_params is not None:
        worker_data = params.model_dump()
        worker_data["per_question_params"] = None
        worker_params = GenerateParams.model_validate(
            {**worker_data, **decoded_per_question_params[i]}
        )
        worker_overrides = spec.coerce_overrides(worker_params, app_state)
        worker_subquestion_configs = _decode_subquestion_configs(
            worker_params.subquestion_configs
        )
    has_explicit_worker_seed = (
        decoded_per_question_params is not None
        and decoded_per_question_params[i].get("seed") is not None
    )
    seed = (
        worker_params.seed
        if has_explicit_worker_seed
        else (worker_params.seed + i) if worker_params.seed is not None else None
    )
    return spec.do_sample_params(
        worker_params,
        worker_overrides,
        seed=seed,
        subquestion_configs_decoded=worker_subquestion_configs,
    )


def build_prompt_previews(
    params: GenerateParams,
    config: ServerConfig,
    app_state: Any,
) -> list[dict[str, Any]]:
    """Resolve parameters and build first-stage prompts without an LLM client."""
    spec = SUBJECTS[params.subject]
    overrides = spec.coerce_overrides(params, app_state)
    decoded_configs = _decode_subquestion_configs(params.subquestion_configs)
    decoded_per_question = decode_per_question_params(params.per_question_params)
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
        sampled = _sample_worker_params(
            i,
            params,
            spec,
            overrides,
            decoded_configs,
            decoded_per_question,
            app_state,
        )
        assert spec.build_generation_prompts is not None
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
    decoded_per_question_params: list[dict[str, Any]] | None
    app_state: Any
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    prior_scopes: list  # mutated by workers; frozen prevents field reassignment only
    prior_scopes_lock: threading.Lock
    emit_pipeline: Any  # Callable[..., None] from make_pipeline_emitter
    generation_log_id: uuid.UUID | None
    retention_days: int
    session_factory: Any
    next_order: Any  # Callable[[], int]
    config: ServerConfig
    balanced_batch: bool


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
        decoded_subquestion_configs=_decode_subquestion_configs(params.subquestion_configs, on_error=on_error),
        decoded_per_question_params=decode_per_question_params(
            params.per_question_params
        ),
        app_state=app_state,
        loop=loop,
        queue=queue,
        prior_scopes=[],
        prior_scopes_lock=threading.Lock(),
        emit_pipeline=make_pipeline_emitter(loop, queue),
        generation_log_id=generation_log_id,
        retention_days=config.llm_exchange_retention_days,
        session_factory=session_factory,
        next_order=_next_order,
        config=config,
        balanced_batch=balanced_batch,
    )


def _worker_one(
    i: int,
    question_client: LLMClient,
    ctx: _RunContext,
    batch_briefs: list,
) -> None:
    """Execute one question-generation worker; enqueues result/error events."""
    worker_recorder = make_exchange_recorder(
        generation_log_id=ctx.generation_log_id,
        retention_days=ctx.retention_days,
        loop=ctx.loop,
        session_factory=ctx.session_factory,
        next_order=ctx.next_order,
    )
    question_client.set_observer(
        make_combined_observer(make_queue_observer(ctx.loop, ctx.queue), worker_recorder)
    )
    emit_question_update = make_question_update_emitter(i, ctx.loop, ctx.queue, ctx.config)
    emit_trail_entry = make_trail_emitter(ctx.loop, ctx.queue)
    verification_trail: list[dict[str, Any]] = []

    def capture_trail_entry(entry: Any) -> None:
        payload = (
            entry.model_dump(mode="json")
            if hasattr(entry, "model_dump")
            else entry
        )
        verification_trail.append(payload)
        emit_trail_entry(entry)

    ctx.emit_pipeline("question_start", index=i, total=ctx.count)
    with ctx.prior_scopes_lock:
        prior_snapshot = list(ctx.prior_scopes)
    try:
        rng_params = _sample_worker_params(
            i,
            ctx.params,
            ctx.spec,
            ctx.overrides,
            ctx.decoded_subquestion_configs,
            ctx.decoded_per_question_params,
            ctx.app_state,
        )

        # Site 2: apply creative brief when available (SS only in practice)
        if i < len(batch_briefs) and batch_briefs[i] is not None:
            rng_params = rng_params.model_copy(
                update={"creative_brief": batch_briefs[i]},
            )

        # Site 3: generate via registry (replaces if/elif generate calls)
        question_id = f"{ctx.spec.question_id_prefix}{ctx.timestamp}_{i+1:03d}"
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
            core_question_callback=ctx.params.core_question_callback,
            on_question_update=emit_question_update,
            on_trail_entry=None if ctx.params.skip_verify else capture_trail_entry,
            prior_scopes=prior_snapshot,
            balanced_batch=ctx.balanced_batch,
        )

        # Site 4: metadata patching (SS only; other specs have patch_metadata=None)
        if ctx.spec.patch_metadata is not None:
            question = ctx.spec.patch_metadata(question, ctx.params.coverage_mode)

        assert isinstance(question, ctx.spec.exam_question_cls)

        # Site 5: prior-scope extraction via registry
        new_scope = ctx.spec.extract_prior_scope(question)
        if new_scope is not None:
            with ctx.prior_scopes_lock:
                ctx.prior_scopes.append(new_scope)
        ctx.emit_pipeline("question_end", index=i, total=ctx.count)
        record_generation_outcome(ctx.params.subject, "success")
        result_event: dict[str, Any] = {
            "event": SSEEventName.RESULT,
            "data": question_to_event(question, ctx.config),
        }
        if verification_trail:
            result_event["verification_trail"] = verification_trail
        ctx.loop.call_soon_threadsafe(
            ctx.queue.put_nowait,
            result_event,
        )
    except Exception as exc:
        record_generation_outcome(ctx.params.subject, "failure")
        ctx.loop.call_soon_threadsafe(
            ctx.queue.put_nowait,
            {
                "event": SSEEventName.ERROR,
                "data": build_sse_error(
                    "generation_failed",
                    f"Question generation failed ({type(exc).__name__})",
                ),
            },
        )
        logger.exception("worker_one error (index=%d)", i)


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

    yield {"event": SSEEventName.STARTED, "data": ""}

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    renderer_pool = getattr(app_state, "renderer_pool", None)
    html_renderer = await renderer_pool.get() if renderer_pool else None

    config.output_dir.mkdir(parents=True, exist_ok=True)
    spec = _subjects[params.subject]
    def _emit_sq_config_error(msg: str) -> None:
        queue.put_nowait({
            "event": SSEEventName.STAGE,
            "data": {
                "type": "stage",
                "agent": "generator",
                "stage": "subquestion_configs",
                "status": "error",
                "message": msg,
                "ts": time.time(),
            },
        })

    ctx = _build_run_context(
        params, config, app_state,
        spec=spec,
        session_factory=_session_factory,
        generation_log_id=generation_log_id,
        loop=loop,
        queue=queue,
        html_renderer=html_renderer,
        on_error=_emit_sq_config_error,
    )

    # Site 2 (creative-brief / coverage planning): delegated to spec.
    # SS: plans briefs when creative_planning=True; returns [None]*count otherwise.
    # Math / NS: always returns [] so the brief-application check is a no-op.
    batch_briefs = spec.plan_all_batch_briefs(
        params, ctx.count, ctx.base_seed, ctx.overrides, config,
        config.creative_planning, ctx.decoded_subquestion_configs,
        client_factory=_client_factory,
    )

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
        # _direct=True: already on the event loop — call_soon_threadsafe would
        # defer pipeline_end by one tick, placing it after done in the queue.
        ctx.emit_pipeline("pipeline_end", total=ctx.count, _direct=True)
        queue.put_nowait({"event": SSEEventName.DONE, "data": ""})

    signal_task = asyncio.create_task(_wait_and_signal())
    try:
        while True:
            event = await queue.get()
            if (
                event["event"] == SSEEventName.RESULT
                and user_id is not None
                and isinstance(event["data"], dict)
            ):
                await persist_generation_record(
                    user_id=user_id,
                    generation_log_id=generation_log_id,
                    subject=params.subject,
                    params=params,
                    payload=event["data"],
                    session_factory=_session_factory,
                    verification_trail_json=event.get("verification_trail"),
                )
            yield event
            if event["event"] in (SSEEventName.DONE, SSEEventName.ERROR):
                break
    finally:
        await signal_task
        if renderer_pool is not None and html_renderer is not None:
            await renderer_pool.put(html_renderer)
