"""Event marshalling for the generate SSE stream.

Owns all concerns related to converting internal objects to SSE event dicts:
  - SSEEventName: single source of truth for every event name the stream emits.
  - question_to_event: serialize ExamQuestion → result-event payload with PNG embedding.
  - extract_image_files / strip_image_base64: payload helpers used by persistence.
  - make_queue_observer / make_combined_observer: LLMObserver factories.
  - make_pipeline_emitter / make_question_update_emitter: queue-write helpers.

No threads are created here and no database is accessed — every function is
unit-testable in isolation.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from server.config import ServerConfig

# ---------------------------------------------------------------------------
# Event-name vocabulary — single source of truth (issue #162 will derive TS)
# ---------------------------------------------------------------------------

class SSEEventName(str, Enum):
    """Canonical set of SSE event names emitted by generate_question_stream.

    This is the single source of truth referenced by issue #162 for TypeScript
    type generation.  Every ``"event"`` key in a yielded dict must be a member.

    str-mixin means SSEEventName.DONE == "done" is True, so all existing
    string comparisons in routes.py and tests continue to work without change.
    """

    STARTED = "started"
    # Declared for wire-contract completeness so issue #162 TS generation captures
    # the full vocabulary — but NEVER emitted by the current server code.
    # The frontend still branches on it: web/src/hooks/useGenerate.ts:386.
    # If the server ever starts emitting it, add "progress" to _EMITTED_EVENTS in
    # tests/server/test_marshalling.py.
    PROGRESS = "progress"
    QUESTION_UPDATE = "question_update"
    RESULT = "result"
    ERROR = "error"
    DONE = "done"
    PIPELINE = "pipeline"
    # Six names mapped from LLM-observer event types:
    LLM_REQUEST = "llm_request"
    LLM_THINKING = "llm_thinking"
    LLM_CONTENT = "llm_content"
    LLM_RESPONSE = "llm_response"
    STAGE = "stage"
    PLAN = "plan"
    TRAIL = "trail"
    QUESTION_TERMINAL = "question_terminal"


# Canonical set of event names the server actually emits at runtime.
# PROGRESS is declared in SSEEventName (for wire-contract completeness, issue #162)
# but deliberately omitted here because the server never produces it.
# If "progress" starts being emitted, add it here and update test_marshalling.py.
EMITTED_EVENT_NAMES: frozenset[str] = frozenset({
    "started",
    "question_update",
    "result",
    "error",
    "done",
    "pipeline",
    "llm_request",
    "llm_thinking",
    "llm_content",
    "llm_response",
    "stage",
    "plan",
    "trail",
    "question_terminal",
})


# Maps internal LLM-observer event ``type`` fields to SSE event names.
_OBSERVER_TYPE_MAP: dict[str, SSEEventName] = {
    "llm_request": SSEEventName.LLM_REQUEST,
    "llm_reasoning_delta": SSEEventName.LLM_THINKING,
    "llm_content_delta": SSEEventName.LLM_CONTENT,
    "llm_response": SSEEventName.LLM_RESPONSE,
    "stage": SSEEventName.STAGE,
    "plan": SSEEventName.PLAN,
}

# ---------------------------------------------------------------------------
# ExamQuestion → SSE payload
# ---------------------------------------------------------------------------

def question_to_event(
    question: Any,
    config: ServerConfig,
) -> dict[str, Any]:
    """Serialize an ExamQuestion to a result-event payload, embedding PNG if present.

    Reads top-level ``圖片`` and every ``subquestions[*].圖片`` from
    ``config.output_dir``; missing files are silently skipped.
    """
    payload: dict[str, Any] = json.loads(question.model_dump_json(exclude_none=True))
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


def extract_image_files(payload: dict[str, Any]) -> list[str]:
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


def strip_image_base64(payload: dict[str, Any]) -> dict[str, Any]:
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


def embed_image_base64(payload: dict[str, Any], config: ServerConfig) -> dict[str, Any]:
    """Copy *payload* and embed existing PNG files without rendering them."""
    embedded = copy.deepcopy(payload)

    def embed(container: dict[str, Any]) -> None:
        if container.get("image_base64"):
            return
        image_name = container.get("圖片")
        if not isinstance(image_name, str) or not image_name:
            return
        image_path = config.output_dir / image_name
        if image_path.exists():
            container["image_base64"] = base64.b64encode(
                image_path.read_bytes()
            ).decode("ascii")

    embed(embedded)
    subquestions = embedded.get("subquestions")
    if isinstance(subquestions, list):
        for subquestion in subquestions:
            if isinstance(subquestion, dict):
                embed(subquestion)
    return embedded


# ---------------------------------------------------------------------------
# Observer factories
# ---------------------------------------------------------------------------

LLMObserver = Callable[[dict], None]


def make_queue_observer(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
) -> LLMObserver:
    """Return an LLMObserver that maps observer events to SSE events on *queue*.

    Thread-safe: uses ``loop.call_soon_threadsafe`` so the observer can be
    called from background ThreadPoolExecutor workers.
    """
    def observer(event: dict) -> None:
        sse_event = _OBSERVER_TYPE_MAP.get(event.get("type", ""))
        if sse_event:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"event": sse_event, "data": event}
            )
    return observer


def make_combined_observer(
    queue_obs: LLMObserver,
    recorder: Any | None,
) -> LLMObserver:
    """Combine a queue observer and an optional exchange recorder into one.

    Both halves are called; individual failures are swallowed so a broken
    recorder never kills the queue observer and vice versa.
    """
    def observer(event: dict) -> None:
        try:
            queue_obs(event)
        except Exception:  # noqa: BLE001 — defensive
            pass
        if recorder is not None:
            try:
                recorder(event)
            except Exception:  # noqa: BLE001 — defensive
                pass
    return observer


def make_publisher_observer(
    publisher: Any,
    question_context: Any | None,
) -> LLMObserver:
    """Return an LLMObserver that publishes through *publisher* using v2 envelopes.

    When *question_context* (a QuestionContext) is given, every event carries
    question_id and index (question scope).  When None, events are batch-scope.
    """
    def observer(event: dict) -> None:
        sse_event = _OBSERVER_TYPE_MAP.get(event.get("type", ""))
        if not sse_event:
            return
        if question_context is not None:
            publisher.publish(
                sse_event,
                question_id=question_context.question_id,
                index=question_context.index,
                payload=dict(event),
            )
        else:
            publisher.publish(sse_event, payload=dict(event))

    return observer


# ---------------------------------------------------------------------------
# Queue-write helpers
# ---------------------------------------------------------------------------

def make_pipeline_emitter(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
) -> Callable[..., None]:
    """Return a ``_emit_pipeline(event_name, *, _direct=False, **data)`` closure.

    Pass ``_direct=True`` when the caller is already on the event loop
    (e.g. inside ``_wait_and_signal``).  That uses ``queue.put_nowait``
    directly instead of ``loop.call_soon_threadsafe``, so the event lands
    in the queue immediately rather than being deferred by one tick.
    """
    def _emit_pipeline(event_name: str, *, _direct: bool = False, **data: object) -> None:
        payload = {"event_name": event_name, "ts": time.time(), **data}
        envelope = {"event": SSEEventName.PIPELINE, "data": payload}
        if _direct:
            queue.put_nowait(envelope)
        else:
            loop.call_soon_threadsafe(queue.put_nowait, envelope)
    return _emit_pipeline


def make_question_update_emitter(
    index: int,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    config: ServerConfig,
) -> Callable[[Any, str], None]:
    """Return an ``emit_question_update(question, phase)`` closure for worker *index*."""
    def emit_question_update(question: Any, phase: str) -> None:
        payload = {
            "index": index,
            "phase": phase,
            "question": question_to_event(question, config),
        }
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"event": SSEEventName.QUESTION_UPDATE, "data": payload},
        )
    return emit_question_update


def make_trail_emitter(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
) -> Callable[[Any], None]:
    """Return a thread-safe emitter for one typed trail entry."""
    def emit_trail(entry: Any) -> None:
        payload = (
            entry.model_dump(mode="json")
            if hasattr(entry, "model_dump")
            else entry
        )
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"event": SSEEventName.TRAIL, "data": payload},
        )

    return emit_trail
