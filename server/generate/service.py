"""SSE streaming wrapper around subject-specific generate_with_corrections functions.

Each request runs concurrently in its own ThreadPoolExecutor thread with its own
LLMObserver, so multiple questions can generate in parallel.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import itertools
import json
import logging
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from server.config import ServerConfig
from server.db import AsyncSessionLocal
from server.generate.exchange_recorder import ExchangeRecorder
from server.generate.models import GenerateParams, build_sse_error
from server.generate.subjects import SUBJECTS
from server.models import GenerationRecord, LLMExchange
from src.cli import (
    generate_with_corrections as math_generate_with_corrections,  # noqa: F401 — monkeypatch seam
)
from src.common.batch_dedup import PriorScope
from src.llm_client import LLMClient, LLMObserver
from src.natural_sciences.cli import (
    generate_with_corrections as ns_generate_with_corrections,  # noqa: F401 — monkeypatch seam
)
from src.natural_sciences.sampler import (
    sample_params as ns_sample_params,  # noqa: F401 — monkeypatch seam
)
from src.natural_sciences.schemas import ExamQuestion as NSExamQuestion
from src.sampler import sample_params as math_sample_params  # noqa: F401 — monkeypatch seam
from src.schemas import ExamQuestion as MathExamQuestion
from src.social_studies.cli import (
    _plan_batch_briefs as ss_plan_batch_briefs,  # noqa: F401 — monkeypatch seam
)
from src.social_studies.cli import (
    generate_with_corrections as ss_generate_with_corrections,  # noqa: F401 — monkeypatch seam
)
from src.social_studies.sampler import (
    sample_params as ss_sample_params,  # noqa: F401 — monkeypatch seam
)
from src.social_studies.schemas import ExamQuestion as SSExamQuestion

logger = logging.getLogger(__name__)


def _decode_subquestion_configs(raw: str | None) -> list[dict] | None:
    """Decode social-studies per-subquestion configs from the GET query string."""
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("subquestion_configs JSON parse failed, ignoring: %s", exc)
        return None
    if not isinstance(decoded, list):
        logger.warning("subquestion_configs JSON must be an array, ignoring")
        return None
    return [item for item in decoded if isinstance(item, dict)]


def _question_to_event(
    question: MathExamQuestion | SSExamQuestion | NSExamQuestion,
    config: ServerConfig,
) -> dict[str, Any]:
    """Serialize an ExamQuestion to a result-event payload, embedding PNG if present."""
    payload = json.loads(question.model_dump_json(exclude_none=True))
    if question.圖片:
        png_path = config.output_dir / question.圖片
        if png_path.exists():
            payload["image_base64"] = base64.b64encode(png_path.read_bytes()).decode("ascii")
    for index, sub in enumerate(getattr(question, "subquestions", []) or []):
        if not getattr(sub, "圖片", None):
            continue
        png_path = config.output_dir / sub.圖片
        if png_path.exists() and index < len(payload.get("subquestions", [])):
            payload["subquestions"][index]["image_base64"] = base64.b64encode(
                png_path.read_bytes()
            ).decode("ascii")
    return payload


def _extract_image_files(payload: dict[str, Any]) -> list[str]:
    """Collect top-level + per-subquestion image filenames (no base64)."""
    files: list[str] = []
    top = payload.get("圖片")
    if top:
        files.append(top)
    for sub in payload.get("subquestions", []) or []:
        if isinstance(sub, dict):
            sub_img = sub.get("圖片")
            if sub_img:
                files.append(sub_img)
    return files


def _strip_image_base64(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a result-event payload with all image_base64 fields removed."""
    cleaned = {k: v for k, v in payload.items() if k != "image_base64"}
    subs = cleaned.get("subquestions")
    if isinstance(subs, list):
        cleaned["subquestions"] = [
            {k: v for k, v in sub.items() if k != "image_base64"}
            if isinstance(sub, dict)
            else sub
            for sub in subs
        ]
    return cleaned


async def _persist_generation_record(
    *,
    user_id: uuid.UUID,
    generation_log_id: uuid.UUID | None,
    subject: str,
    params: GenerateParams,
    payload: dict[str, Any],
) -> None:
    """Insert one generation_records row; log-and-swallow on failure so
    persistence never breaks generation."""
    try:
        record = GenerationRecord(
            user_id=user_id,
            generation_log_id=generation_log_id,
            subject=subject,
            question_id=payload.get("id", ""),
            params_json=params.model_dump(mode="json"),
            question_json=_strip_image_base64(payload),
            image_files=_extract_image_files(payload),
        )
        async with AsyncSessionLocal() as session:
            session.add(record)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort persistence
        logger.warning("failed to persist generation_record: %s", exc)


async def generate_question_stream(
    params: GenerateParams,
    config: ServerConfig,
    app_state: Any,
    user_id: uuid.UUID | None = None,
    generation_log_id: uuid.UUID | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding SSE event dicts for one or more questions.

    Event shapes:
      - {"event": "started",  "data": ""}
      - {"event": "progress", "data": str}
      - {"event": "question_update", "data": {"index": int, "phase": str, "question": dict}}
      - {"event": "result",   "data": dict}
      - {"event": "error",    "data": str}
      - {"event": "done",     "data": ""}
    """
    yield {"event": "started", "data": ""}

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    renderer_pool = getattr(app_state, "renderer_pool", None)
    html_renderer = await renderer_pool.get() if renderer_pool else None

    # --- Registry lookup — replaces all is_social_studies / is_natural_sciences checks ---
    spec = SUBJECTS[params.subject]

    # Site 1: enum coercion + subject-specific app_state extraction
    overrides = spec.coerce_overrides(params, app_state)

    # Site 2 (partial): balanced-coverage batch-sampler setup (SS only; others return (None, False))
    batch_sampler, batch_user_pinned_lc = spec.setup_batch_sampler(params, overrides)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_seed = params.seed
    count = max(1, params.count)
    max_retries = params.max_retries

    config.output_dir.mkdir(parents=True, exist_ok=True)

    prior_scopes: list[PriorScope] = []
    prior_scopes_lock = threading.Lock()

    _EVENT_TYPE_MAP = {
        "llm_request": "llm_request",
        "llm_reasoning_delta": "llm_thinking",
        "llm_content_delta": "llm_content",
        "llm_response": "llm_response",
        "stage": "stage",
    }

    def _make_queue_observer(
        _loop: asyncio.AbstractEventLoop,
        _queue: asyncio.Queue,
    ) -> LLMObserver:
        def observer(event: dict) -> None:
            sse_event = _EVENT_TYPE_MAP.get(event.get("type", ""))
            if sse_event:
                _loop.call_soon_threadsafe(
                    _queue.put_nowait, {"event": sse_event, "data": event}
                )
        return observer

    order_counter = itertools.count(1)
    order_lock = threading.Lock()

    def _next_order() -> int:
        with order_lock:
            return next(order_counter)

    def _make_recorder() -> ExchangeRecorder | None:
        if generation_log_id is None or config.llm_exchange_retention_days <= 0:
            return None

        async def _insert(row: dict[str, Any]) -> None:
            async with AsyncSessionLocal() as sess:
                sess.add(LLMExchange(**row))
                await sess.commit()

        def _write_row(row: dict[str, Any]) -> None:
            future = asyncio.run_coroutine_threadsafe(_insert(row), loop)
            try:
                future.result(timeout=10)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("llm_exchanges insert failed: %s", exc)

        return ExchangeRecorder(generation_log_id, _write_row, next_order=_next_order)

    def _make_observer(
        queue_obs: LLMObserver,
        recorder: ExchangeRecorder | None,
    ) -> LLMObserver:
        def observer(event: dict) -> None:
            try:
                queue_obs(event)
            except Exception:
                pass
            if recorder is not None:
                try:
                    recorder(event)
                except Exception:
                    pass
        return observer

    def _emit_pipeline(event_name: str, **data: object) -> None:
        import time as _time

        payload = {"event_name": event_name, "ts": _time.time(), **data}
        loop.call_soon_threadsafe(
            queue.put_nowait, {"event": "pipeline", "data": payload}
        )

    def _make_question_update_emitter(index: int):
        def emit_question_update(
            question: MathExamQuestion | SSExamQuestion | NSExamQuestion,
            phase: str,
        ) -> None:
            payload = {
                "index": index,
                "phase": phase,
                "question": _question_to_event(question, config),
            }
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"event": "question_update", "data": payload},
            )

        return emit_question_update

    decoded_subquestion_configs = _decode_subquestion_configs(params.subquestion_configs)

    def worker_one(i: int, question_client: LLMClient) -> None:
        seed = (base_seed + i) if base_seed is not None else None
        worker_recorder = _make_recorder()
        question_client.set_observer(
            _make_observer(_make_queue_observer(loop, queue), worker_recorder)
        )
        emit_question_update = _make_question_update_emitter(i)
        _emit_pipeline("question_start", index=i, total=count)
        with prior_scopes_lock:
            prior_snapshot = list(prior_scopes)
        try:
            # Site 1+3: sample params via registry (replaces if/elif per-subject sampler calls)
            assigned_qt = batch_sampler.q_type_assignments[i] if batch_sampler is not None else None
            assigned_lc = (
                batch_sampler.learning_content_assignments[i]
                if batch_sampler is not None and not batch_user_pinned_lc
                else None
            )
            rng_params = spec.do_sample_params(
                params,
                overrides,
                seed=seed,
                assigned_q_type=assigned_qt,
                assigned_lc=assigned_lc,
                subquestion_configs_decoded=decoded_subquestion_configs,
            )

            # Site 2: apply creative brief when available (SS only in practice)
            if i < len(batch_briefs) and batch_briefs[i] is not None:
                rng_params = rng_params.model_copy(
                    update={"creative_brief": batch_briefs[i]},
                )

            # Site 3: generate via registry (replaces if/elif generate calls)
            question_id = f"{spec.question_id_prefix}{timestamp}_{i+1:03d}"
            question = spec.do_generate(
                rng_params,
                overrides,
                config=client_config,
                client=question_client,
                question_id=question_id,
                max_retries=max_retries,
                skip_verify=params.skip_verify,
                disable_reference_fewshot=params.disable_reference_fewshot,
                html_renderer=html_renderer,
                image_generation_mode=params.image_generation_mode,
                user_passage=params.passage,
                text_word_limit=params.text_word_limit,
                user_options=params.options,
                user_topic=params.topic,
                user_core_question=params.core_question,
                on_question_update=emit_question_update,
                prior_scopes=prior_snapshot,
            )

            # Site 4: metadata patching (SS only; other specs have patch_metadata=None)
            if spec.patch_metadata is not None:
                question = spec.patch_metadata(question, batch_sampler)

            assert isinstance(question, spec.exam_question_cls)

            # Site 5: prior-scope extraction via registry
            new_scope = spec.extract_prior_scope(question)
            if new_scope is not None:
                with prior_scopes_lock:
                    prior_scopes.append(new_scope)
            _emit_pipeline("question_end", index=i, total=count)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"event": "result", "data": _question_to_event(question, config)},
            )
        except Exception as exc:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "event": "error",
                    "data": build_sse_error(
                        "generation_failed",
                        f"Question generation failed ({type(exc).__name__})",
                    ),
                },
            )
            logger.exception("worker_one error (index=%d)", i)

    # Site 2 (creative-brief / coverage planning): delegated to spec
    # SS: plans briefs when creative_planning=True; returns [None]*count otherwise.
    # Math / NS: always returns [] so the brief-application check is a no-op.
    batch_briefs = spec.plan_all_batch_briefs(
        params,
        count,
        base_seed,
        overrides,
        config,
        config.creative_planning,
        decoded_subquestion_configs,
    )

    _emit_pipeline("pipeline_start", total=count)
    # #105: per-request model overrides are baked into each LLMClient's config so
    # downstream `client.generate*` / `client.plan` calls transparently use the
    # chosen model without changing subject-CLI signatures.
    client_config = dataclasses.replace(
        config,
        model_execute=params.model_execute or config.model_execute,
        model_plan=params.model_plan or config.model_plan,
    )
    question_clients = [LLMClient(client_config) for _ in range(count)]
    futures = [
        loop.run_in_executor(None, worker_one, i, question_clients[i])
        for i in range(count)
    ]

    async def _wait_and_signal() -> None:
        await asyncio.gather(*futures, return_exceptions=True)
        _emit_pipeline("pipeline_end", total=count)
        queue.put_nowait({"event": "done", "data": ""})

    signal_task = asyncio.create_task(_wait_and_signal())
    try:
        while True:
            event = await queue.get()
            if (
                event["event"] == "result"
                and user_id is not None
                and isinstance(event["data"], dict)
            ):
                await _persist_generation_record(
                    user_id=user_id,
                    generation_log_id=generation_log_id,
                    subject=params.subject,
                    params=params,
                    payload=event["data"],
                )
            yield event
            if event["event"] in ("done", "error"):
                break
    finally:
        await signal_task
        if renderer_pool is not None and html_renderer is not None:
            await renderer_pool.put(html_renderer)
