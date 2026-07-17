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
import random
import threading
import traceback
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from server.config import ServerConfig
from server.db import AsyncSessionLocal
from server.generate.exchange_recorder import ExchangeRecorder
from server.generate.models import GenerateParams
from server.models import GenerationRecord, LLMExchange
from src.batch_sampler import BatchSampler
from src.cli import generate_with_corrections as math_generate_with_corrections
from src.common.batch_dedup import (
    PriorScope,
    extract_math_prior_scope,
    extract_ns_prior_scope,
    extract_ss_prior_scope,
)
from src.llm_client import LLMClient, LLMObserver
from src.natural_sciences.cli import generate_with_corrections as ns_generate_with_corrections
from src.natural_sciences.sampler import sample_params as ns_sample_params
from src.natural_sciences.schemas import (
    ExamQuestion as NSExamQuestion,
)
from src.natural_sciences.schemas import (
    QuestionContext as NSQuestionContext,
)
from src.natural_sciences.schemas import (
    QuestionSetType as NSQuestionSetType,
)
from src.natural_sciences.schemas import (
    QuestionSubContext as NSQuestionSubContext,
)
from src.natural_sciences.schemas import (
    QuestionType as NSQuestionType,
)
from src.natural_sciences.schemas import (
    ScienceCompetency as NSScienceCompetency,
)
from src.sampler import sample_params as math_sample_params
from src.schemas import (
    ExamQuestion as MathExamQuestion,
)
from src.schemas import (
    QuestionContext as MathQuestionContext,
)
from src.schemas import (
    QuestionSetType as MathQuestionSetType,
)
from src.schemas import (
    QuestionStyle as MathQuestionStyle,
)
from src.schemas import (
    QuestionType as MathQuestionType,
)
from src.social_studies.cli import _plan_batch_briefs as ss_plan_batch_briefs
from src.social_studies.cli import generate_with_corrections as ss_generate_with_corrections
from src.social_studies.sampler import sample_params as ss_sample_params
from src.social_studies.schemas import (
    CreativeBrief as SSCreativeBrief,
)
from src.social_studies.schemas import (
    ExamQuestion as SSExamQuestion,
)
from src.social_studies.schemas import (
    QuestionContext as SSQuestionContext,
)
from src.social_studies.schemas import (
    QuestionMetadata,
)
from src.social_studies.schemas import (
    QuestionSetType as SSQuestionSetType,
)
from src.social_studies.schemas import (
    QuestionSubject as SSQuestionSubject,
)
from src.social_studies.schemas import (
    QuestionType as SSQuestionType,
)

logger = logging.getLogger(__name__)


def _resolve_enum(value: str | None, enum_cls: type) -> Any:
    if value is None:
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    raise ValueError(f"Invalid value '{value}' for {enum_cls.__name__}")


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
    is_social_studies = params.subject == "social_studies"
    is_natural_sciences = params.subject == "natural_sciences"

    if is_social_studies:
        context_override = (
            [_resolve_enum(v, SSQuestionContext) for v in params.context]
            if params.context else None
        )
        set_type_override = _resolve_enum(params.set_type, SSQuestionSetType)
        q_type_override = (
            [_resolve_enum(v, SSQuestionType) for v in params.q_type]
            if params.q_type else None
        )
        subject_override = (
            [SSQuestionSubject(v) for v in params.subject_filter]
            if params.subject_filter else None
        )
    elif is_natural_sciences:
        context_override = (
            [_resolve_enum(v, NSQuestionContext) for v in params.context]
            if params.context else None
        )
        sub_context_override = _resolve_enum(params.sub_context, NSQuestionSubContext)
        set_type_override = _resolve_enum(params.set_type, NSQuestionSetType)
        q_type_override = (
            [_resolve_enum(v, NSQuestionType) for v in params.q_type]
            if params.q_type else None
        )
        science_competency_override = (
            [_resolve_enum(v, NSScienceCompetency) for v in params.science_competency]
            if params.science_competency else None
        )
    else:
        curriculum = app_state.curriculum
        performance = app_state.performance
        intro_text = app_state.intro_text
        grade_content = app_state.grade_content
        style_override = (
            [MathQuestionStyle(v) for v in params.style] if params.style else None
        )
        context_override = (
            [_resolve_enum(v, MathQuestionContext) for v in params.context]
            if params.context else None
        )
        set_type_override = _resolve_enum(params.set_type, MathQuestionSetType)
        q_type_override = (
            [_resolve_enum(v, MathQuestionType) for v in params.q_type]
            if params.q_type else None
        )

    # --- Balanced-coverage planning (SS only, count > 1, balanced mode) -----
    ss_batch_sampler: BatchSampler | None = None
    ss_batch_user_pinned_lc = False
    if (
        is_social_studies
        and params.count > 1
        and params.coverage_mode == "balanced"
    ):
        batch_rng = random.Random(params.seed if params.seed is not None else 0)
        # Interaction rule: only balance dimensions the user left random.
        user_pinned_qtype = bool(params.q_type) or bool(params.subquestion_configs)
        user_pinned_lc = bool(params.learning_content)
        ss_batch_user_pinned_lc = user_pinned_lc
        q_pool = (
            [SSQuestionType(v) for v in params.q_type]
            if user_pinned_qtype and params.q_type
            else list(SSQuestionType)
        )
        # 學習內容 pool: keyed by 跨科 (the full cross-subject union) when the
        # user didn't pin subject_filter. This is a pragmatic stand-in since
        # the per-question 科目 isn't known at batch-planning time; per-question
        # sampling may therefore draw an out-of-subject code — known v1 limitation.
        from src.social_studies.curriculum_loader import (
            allowed_learning_content,
            load_learning_content,
        )
        from src.social_studies.sampler import _LEARNING_STAGE as _SS_STAGE

        subj_key = (
            params.subject_filter[0] if params.subject_filter else "跨科"
        )
        lc_entries = (
            allowed_learning_content(load_learning_content(), _SS_STAGE, subj_key)
            if not user_pinned_lc
            else []
        )
        lc_pool = [e["value"] for e in lc_entries] if not user_pinned_lc else []

        ss_batch_sampler = BatchSampler(
            count=params.count,
            # Always pass the full q_type pool: when user_pinned_qtype is True,
            # sample_params() ignores these batch-planned q_type assignments and
            # uses the user's pinned q_type/subquestion_configs instead, so the
            # pool value here is a no-op in that case.
            q_type_pool=q_pool,
            learning_content_pool=lc_pool,
            rng=batch_rng,
        )

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
            if is_social_studies:
                assigned_qt = (
                    ss_batch_sampler.q_type_assignments[i]
                    if ss_batch_sampler is not None else None
                )
                assigned_lc = (
                    ss_batch_sampler.learning_content_assignments[i]
                    if ss_batch_sampler is not None and not ss_batch_user_pinned_lc
                    else None
                )
                rng_params = ss_sample_params(
                    grade=params.grade,
                    context=context_override,
                    set_type=set_type_override,
                    q_type=q_type_override,
                    subject=subject_override,
                    content_type=params.content_type,
                    learning_content=params.learning_content,
                    learning_performance=params.learning_performance,
                    seed=seed,
                    sub_question_count=params.sub_question_count,
                    question_word_limit=params.question_word_limit,
                    option_word_limit=params.option_word_limit,
                    subquestion_configs=_decode_subquestion_configs(
                        params.subquestion_configs,
                    ),
                    assigned_q_type=assigned_qt,
                    assigned_learning_content=assigned_lc,
                )
                if i < len(ss_batch_briefs) and ss_batch_briefs[i] is not None:
                    rng_params = rng_params.model_copy(
                        update={"creative_brief": ss_batch_briefs[i]},
                    )
                question_id = f"ss_{timestamp}_{i+1:03d}"
                question = ss_generate_with_corrections(
                    config=client_config,
                    client=question_client,
                    params=rng_params,
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
            elif is_natural_sciences:
                rng_params = ns_sample_params(
                    grade=params.grade,
                    context=context_override,
                    sub_context=sub_context_override,
                    set_type=set_type_override,
                    q_type=q_type_override,
                    science_competency=science_competency_override,
                    content_type=params.content_type,
                    learning_content=params.learning_content,
                    learning_performance=params.learning_performance,
                    seed=seed,
                    sub_question_count=params.sub_question_count,
                    question_word_limit=params.question_word_limit,
                    option_word_limit=params.option_word_limit,
                    subquestion_configs=_decode_subquestion_configs(
                        params.subquestion_configs,
                    ),
                )
                question_id = f"ns_{timestamp}_{i+1:03d}"
                question = ns_generate_with_corrections(
                    config=client_config,
                    client=question_client,
                    params=rng_params,
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
            else:
                # math sampler accepts a single 科目 string; take first if list provided
                math_subject_filter: str | None = None
                if params.subject_filter:
                    math_subject_filter = params.subject_filter[0]
                rng_params = math_sample_params(
                    grade_content=grade_content,
                    grade=params.grade,
                    style=style_override,
                    context=context_override,
                    set_type=set_type_override,
                    q_type=q_type_override,
                    seed=seed,
                    core_competency=params.core_competency,
                    learning_content=params.learning_content,
                    learning_performance=params.learning_performance,
                    content_type=params.content_type,
                    subject_filter=math_subject_filter,
                )
                question_id = f"q_{timestamp}_{i+1:03d}"
                question = math_generate_with_corrections(
                    config=client_config,
                    client=question_client,
                    curriculum=curriculum,
                    performance=performance,
                    intro_text=intro_text,
                    grade_content=grade_content,
                    params=rng_params,
                    question_id=question_id,
                    max_retries=max_retries,
                    skip_verify=params.skip_verify,
                    html_renderer=html_renderer,
                    image_generation_mode=params.image_generation_mode,
                    user_topic=params.topic or "",
                    user_passage=params.passage or "",
                    user_options=params.options,
                    user_core_question=params.core_question or "",
                    on_question_update=emit_question_update,
                    prior_scopes=prior_snapshot,
                )
            if is_social_studies and isinstance(question, SSExamQuestion):
                effective_mode = (
                    "balanced" if ss_batch_sampler is not None else "random"
                )
                if question.metadata is None:
                    fallback_model = getattr(config, "model_execute", "unknown")
                    question.metadata = QuestionMetadata(
                        grade=rng_params.grade,
                        model=fallback_model,
                        coverage_mode_used=effective_mode,
                    )
                else:
                    question.metadata = question.metadata.model_copy(
                        update={"coverage_mode_used": effective_mode}
                    )
            assert isinstance(
                question,
                (MathExamQuestion, SSExamQuestion, NSExamQuestion),
            )
            if is_social_studies:
                new_scope = extract_ss_prior_scope(question)
            elif is_natural_sciences:
                new_scope = extract_ns_prior_scope(question)
            else:
                new_scope = extract_math_prior_scope(question)
            if new_scope is not None:
                with prior_scopes_lock:
                    prior_scopes.append(new_scope)
            _emit_pipeline("question_end", index=i, total=count)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"event": "result", "data": _question_to_event(question, config)},
            )
        except Exception as exc:
            tb = traceback.format_exc()
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"event": "error", "data": f"{type(exc).__name__}: {exc}\n\n{tb}"},
            )
            logger.exception("worker_one error (index=%d)", i)

    # #114: for SS batches, plan creative briefs once before spawning workers.
    ss_batch_briefs: list[SSCreativeBrief | None] = []
    if is_social_studies and count >= 1 and config.creative_planning:
        # Sample all SS params up front so plan_context_angles sees the actual
        # 情境 and 學習內容 pool that the workers will use. Workers re-sample
        # with the same seed and receive the corresponding brief.
        pre_params_list = []
        for i in range(count):
            seed = (base_seed + i) if base_seed is not None else None
            pre_params_list.append(
                ss_sample_params(
                    grade=params.grade,
                    context=context_override,
                    set_type=set_type_override,
                    q_type=q_type_override,
                    subject=subject_override,
                    content_type=params.content_type,
                    learning_performance=params.learning_performance,
                    seed=seed,
                    sub_question_count=params.sub_question_count,
                    question_word_limit=params.question_word_limit,
                    option_word_limit=params.option_word_limit,
                    subquestion_configs=_decode_subquestion_configs(
                        params.subquestion_configs,
                    ),
                ),
            )
        # Use a dedicated planning client so worker observers stay clean.
        planning_client = LLMClient(config)
        ss_batch_briefs = ss_plan_batch_briefs(planning_client, config, pre_params_list)
    elif is_social_studies:
        ss_batch_briefs = [None] * count

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
