"""SSE streaming wrapper around `src.cli.generate_one()`.

Mirrors the Tkinter GUI's stderr-redirection pattern (see `run.py:373-390` in
the legacy GUI): stderr is redirected to a queue while `generate_one()` runs in
a worker thread, and the async generator drains the queue and emits SSE event
dicts.

A module-level `_GEN_LOCK` serializes concurrent generation requests because
`sys.stderr` redirection is process-global. `_QUEUE_DEPTH` tracks how many
requests are waiting or active so callers receive a `queued` event with a
`jobs_ahead` count before the lock is acquired.

Note: the counter and lock are in-process only. Multi-worker deployments need a
shared counter (e.g. Redis) for accurate queue depth across workers.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
import traceback
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from src.cli import generate_with_corrections as math_generate_with_corrections
from src.llm_client import LLMClient, LLMObserver
from src.sampler import sample_params as math_sample_params
from src.schemas import (
    ExamQuestion as MathExamQuestion,
    QuestionContext as MathQuestionContext,
    QuestionSetType as MathQuestionSetType,
    QuestionStyle as MathQuestionStyle,
    QuestionType as MathQuestionType,
)
from src.social_studies.cli import generate_with_corrections as ss_generate_with_corrections
from src.social_studies.sampler import sample_params as ss_sample_params
from src.social_studies.schemas import (
    ExamQuestion as SSExamQuestion,
    QuestionContext as SSQuestionContext,
    QuestionSetType as SSQuestionSetType,
    QuestionStyle as SSQuestionStyle,
    QuestionSubject as SSQuestionSubject,
    QuestionType as SSQuestionType,
)

from server.config import ServerConfig
from server.generate.models import GenerateParams

logger = logging.getLogger(__name__)

_GEN_LOCK = asyncio.Lock()
_QUEUE_TOTAL = 0   # monotonically increasing; each request claims the next number
_QUEUE_DONE = 0    # how many requests have fully completed
_QUEUE_CHANGED = asyncio.Event()  # set() when _QUEUE_DONE increments


class _QueueWriter:
    """File-like object that pushes writes onto an asyncio.Queue.

    Used to redirect `sys.stderr` from a worker thread into the async
    generator's queue. `loop.call_soon_threadsafe()` bridges thread → loop.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
        self._loop = loop
        self._queue = queue

    def write(self, s: str) -> int:
        if s:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, {"event": "progress", "data": s}
            )
        return len(s)

    def flush(self) -> None:  # pragma: no cover - file-like contract
        return None


def _resolve_enum(value: str | None, enum_cls: type) -> Any:
    if value is None:
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    raise ValueError(f"Invalid value '{value}' for {enum_cls.__name__}")


def _question_to_event(
    question: MathExamQuestion | SSExamQuestion,
    config: ServerConfig,
) -> dict[str, Any]:
    """Serialize an ExamQuestion to a result-event payload, embedding PNG if present."""
    payload = json.loads(question.model_dump_json(exclude_none=True))
    if question.圖片:
        png_path = config.output_dir / question.圖片
        if png_path.exists():
            payload["image_base64"] = base64.b64encode(png_path.read_bytes()).decode("ascii")
    return payload


async def generate_question_stream(
    params: GenerateParams,
    config: ServerConfig,
    app_state: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding SSE event dicts for one or more questions.

    Event shapes:
      - {"event": "queued",   "data": {"jobs_ahead": int}}  (only when waiting)
      - {"event": "started",  "data": ""}
      - {"event": "progress", "data": str}
      - {"event": "result",   "data": dict}
      - {"event": "error",    "data": str}
      - {"event": "done",     "data": ""}
    """
    global _QUEUE_TOTAL, _QUEUE_DONE
    _QUEUE_TOTAL += 1
    my_order = _QUEUE_TOTAL  # fixed ordinal for this request; never changes

    try:
        # Notify waiting clients of their position and update as others finish.
        while True:
            jobs_ahead = my_order - 1 - _QUEUE_DONE
            if jobs_ahead <= 0:
                break
            yield {"event": "queued", "data": {"jobs_ahead": jobs_ahead}}
            _QUEUE_CHANGED.clear()
            await _QUEUE_CHANGED.wait()

        async with _GEN_LOCK:
            yield {"event": "started", "data": ""}

            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            client = LLMClient(config)
            html_renderer = getattr(app_state, "html_renderer", None)
            is_social_studies = params.subject == "social_studies"

            if is_social_studies:
                style_override = (
                    [SSQuestionStyle(v) for v in params.style] if params.style else None
                )
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

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_seed = params.seed
            count = max(1, params.count)
            max_retries = params.max_retries

            config.output_dir.mkdir(parents=True, exist_ok=True)

            _EVENT_TYPE_MAP = {
                "llm_request": "llm_request",
                "llm_reasoning_delta": "llm_thinking",
                "llm_content_delta": "llm_content",
                "llm_response": "llm_response",
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

            def worker() -> None:
                saved_stderr = sys.stderr
                sys.stderr = _QueueWriter(loop, queue)
                client.set_observer(_make_queue_observer(loop, queue))
                try:
                    for i in range(count):
                        seed = (base_seed + i) if base_seed is not None else None
                        if is_social_studies:
                            rng_params = ss_sample_params(
                                grade=params.grade,
                                style=style_override,
                                context=context_override,
                                set_type=set_type_override,
                                q_type=q_type_override,
                                subject=subject_override,
                                seed=seed,
                            )
                            question_id = f"ss_{timestamp}_{i+1:03d}"
                            try:
                                question = ss_generate_with_corrections(
                                    config=config,
                                    client=client,
                                    params=rng_params,
                                    question_id=question_id,
                                    max_retries=max_retries,
                                    skip_verify=params.skip_verify,
                                    html_renderer=html_renderer,
                                    image_generation_mode=params.image_generation_mode,
                                )
                            except Exception as exc:
                                tb = traceback.format_exc()
                                loop.call_soon_threadsafe(
                                    queue.put_nowait,
                                    {"event": "error", "data": f"{type(exc).__name__}: {exc}\n\n{tb}"},
                                )
                                logger.exception("worker ss_generate error")
                                return
                        else:
                            rng_params = math_sample_params(
                                grade_content=grade_content,
                                grade=params.grade,
                                style=style_override,
                                context=context_override,
                                set_type=set_type_override,
                                q_type=q_type_override,
                                seed=seed,
                            )
                            question_id = f"q_{timestamp}_{i+1:03d}"
                            try:
                                question = math_generate_with_corrections(
                                    config=config,
                                    client=client,
                                    curriculum=curriculum,
                                    performance=performance,
                                    intro_text=intro_text,
                                    grade_content=grade_content,
                                    params=rng_params,
                                    question_id=question_id,
                                    max_retries=max_retries,
                                    skip_verify=params.skip_verify,
                                    html_renderer=html_renderer,
                                )
                            except Exception as exc:
                                tb = traceback.format_exc()
                                loop.call_soon_threadsafe(
                                    queue.put_nowait,
                                    {"event": "error", "data": f"{type(exc).__name__}: {exc}\n\n{tb}"},
                                )
                                logger.exception("worker math_generate error")
                                return

                        assert isinstance(question, (MathExamQuestion, SSExamQuestion))
                        payload = _question_to_event(question, config)
                        loop.call_soon_threadsafe(
                            queue.put_nowait, {"event": "result", "data": payload}
                        )
                finally:
                    sys.stderr = saved_stderr
                    loop.call_soon_threadsafe(
                        queue.put_nowait, {"event": "done", "data": ""}
                    )

            future = loop.run_in_executor(None, worker)

            try:
                while True:
                    event = await queue.get()
                    yield event
                    if event["event"] in ("done", "error"):
                        break
            finally:
                await future
    finally:
        _QUEUE_DONE += 1
        _QUEUE_CHANGED.set()
