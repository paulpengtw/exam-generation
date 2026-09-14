"""Slice 6 – question_terminal event tests.

Tests ensure _worker_one emits a question_terminal event at each exit:
- success: after the result event, with delivery_status="delivered"
- error:   after the error event, with delivery_status="failed"
- cancel:  when GenerationCancelled, with delivery_status="cancelled"
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch


def _build_ctx(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> Any:
    """Build a minimal _RunContext suitable for _worker_one unit tests."""
    from server.config import ServerConfig
    from server.generate.service import _build_run_context
    from server.generate.subjects import SUBJECTS
    from tests.server.generate_test_utils import resolved_generate_params

    params = resolved_generate_params(
        {
            "subject": "math",
            "seed": 41,
            "grade": 8,
            "context": ["個人"],
            "set_type": "單一題",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "math_thinking": ["形成"],
            "learning_content": ["A-7-7"],
            "learning_performance": ["s-IV-12"],
            "core_competency": ["數-J-A2"],
            "content_type": "純文字",
            "count": 1,
            "skip_verify": True,
        }
    )
    spec = SUBJECTS["math"]
    config = ServerConfig(api_key="x", gemini_api_key="x")
    app_state = MagicMock()
    return _build_run_context(
        params,
        config,
        app_state=app_state,
        spec=spec,
        session_factory=None,
        generation_log_id=None,
        loop=loop,
        queue=queue,
        html_renderer=None,
    )


def _drain_queue(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> list[dict]:
    async def _collect() -> list[dict]:
        items = []
        while not queue.empty():
            items.append(await queue.get())
        return items

    return loop.run_until_complete(_collect())


# ---------------------------------------------------------------------------
# question_terminal on success
# ---------------------------------------------------------------------------


def test_question_terminal_emitted_on_success() -> None:
    """question_terminal with delivery_status=delivered must appear after result."""
    from server.generate.service import _worker_one
    from src.schemas import ExamQuestion

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)

    fake_question = MagicMock(spec=ExamQuestion)
    fake_question.__class__ = ctx.spec.exam_question_cls

    with (
        patch.object(ctx.spec, "do_generate", return_value=fake_question),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch("server.generate.service.question_to_event", return_value={"fake": True}),
        patch("server.generate.service.record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    # Events may be v1 {event: ...} or v2 {context: {event: ...}, payload: {...}}
    def _event_name(e: dict) -> str | None:
        if "context" in e:
            return e["context"].get("event")
        return e.get("event")
    event_names = [_event_name(e) for e in events]
    assert "question_terminal" in event_names, f"missing question_terminal; got {event_names}"

    terminal = next(e for e in events if _event_name(e) == "question_terminal")
    payload = terminal.get("payload", terminal)
    assert payload.get("delivery_status") == "delivered"


# ---------------------------------------------------------------------------
# question_terminal on error
# ---------------------------------------------------------------------------


def test_question_terminal_emitted_on_error() -> None:
    """question_terminal with delivery_status=failed must appear after error."""
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)

    with (
        patch.object(ctx.spec, "do_generate", side_effect=RuntimeError("boom")),
        patch("server.generate.service.record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    # Events may be v1 {event: ...} or v2 {context: {event: ...}, payload: {...}}
    def _event_name(e: dict) -> str | None:
        if "context" in e:
            return e["context"].get("event")
        return e.get("event")
    event_names = [_event_name(e) for e in events]
    assert "question_terminal" in event_names, f"missing question_terminal; got {event_names}"

    terminal = next(e for e in events if _event_name(e) == "question_terminal")
    payload = terminal.get("payload", terminal)
    assert payload.get("delivery_status") == "failed"


# ---------------------------------------------------------------------------
# question_terminal on cancel
# ---------------------------------------------------------------------------


def test_question_terminal_emitted_on_cancel() -> None:
    """question_terminal with delivery_status=cancelled must appear on GenerationCancelled."""
    from server.generate.service import _worker_one
    from src.common.generation_core import GenerationCancelled

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)

    with (
        patch.object(ctx.spec, "do_generate", side_effect=GenerationCancelled()),
        patch("server.generate.service.record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    # Events may be v1 {event: ...} or v2 {context: {event: ...}, payload: {...}}
    def _event_name(e: dict) -> str | None:
        if "context" in e:
            return e["context"].get("event")
        return e.get("event")
    event_names = [_event_name(e) for e in events]
    assert "question_terminal" in event_names, f"missing question_terminal; got {event_names}"

    terminal = next(e for e in events if _event_name(e) == "question_terminal")
    payload = terminal.get("payload", terminal)
    assert payload.get("delivery_status") == "cancelled"
