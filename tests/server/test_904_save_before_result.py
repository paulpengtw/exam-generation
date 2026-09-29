"""Issue #904 – save each question's record before its result is published.

TDD tests: these fail on current code and pass after the fix.

Acceptance criteria:
  AC1 – A question worker saves its record before RESULT is published.
  AC2 – A RESULT that is never consumed by the stream is still saved.
  AC3 – A failing session factory causes N retries, Sentry capture, then RESULT
         still published and the question is NOT reported as saved.

These tests run _worker_one_body directly (stub-context style from
tests/server/test_858_worker_split_units.py) with a fake session factory
injected via _RunContext.session_factory and a running event loop in a
background thread so asyncio.run_coroutine_threadsafe works.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.generate.marshalling import SSEEventName
from server.generate.service import _build_run_context
from server.generate.subjects import SUBJECTS
from src.llm_client import LLMClient
from tests.server.generate_test_utils import resolved_generate_params

# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------

_MATH_PARAMS: dict[str, Any] = {
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


def _build_ctx(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    *,
    user_id: uuid.UUID | None = None,
    session_factory: Any = None,
    output_dir: Path | None = None,
    save_backoff_fn: Any | None = None,
) -> Any:
    """Build a _RunContext with persistence fields for worker-save unit tests."""
    params = resolved_generate_params(_MATH_PARAMS)
    spec = SUBJECTS["math"]
    cfg_kwargs: dict[str, Any] = {"api_key": "x", "gemini_api_key": "x"}
    if output_dir is not None:
        cfg_kwargs["output_dir"] = output_dir
    config = ServerConfig(**cfg_kwargs)
    app_state = MagicMock()

    ctx = _build_run_context(
        params,
        config,
        app_state=app_state,
        spec=spec,
        session_factory=session_factory,
        generation_log_id=uuid.uuid4(),
        loop=loop,
        queue=queue,
        html_renderer=None,
        user_id=user_id,
        save_backoff_fn=save_backoff_fn,
    )
    return ctx


def _make_client() -> Any:
    client = MagicMock(spec=LLMClient)
    client.set_observer.return_value = None
    return client


def _make_do_generate(question_id: str) -> Any:
    """Return a fake do_generate that produces a minimal valid math question."""

    def do_generate(rng_params: Any, _overrides: Any, **kwargs: Any) -> Any:
        from server.generate.subjects import SUBJECTS

        spec = SUBJECTS["math"]
        q = MagicMock(spec=spec.exam_question_cls)
        q.__class__ = spec.exam_question_cls
        q.model_dump_json.return_value = json.dumps({"id": question_id})
        q.圖片 = None
        q.subquestions = []
        q.chart_spec = None
        q.verification = None
        return q

    return do_generate


def _run_worker(ctx: Any, do_generate_fn: Any) -> None:
    """Run _worker_one_body with the patched spec."""
    from server.generate.service import _worker_one_body

    spec = dataclasses.replace(SUBJECTS["math"], do_generate=do_generate_fn)
    ctx_patched = dataclasses.replace(ctx, spec=spec)
    client = _make_client()
    _worker_one_body(0, client, ctx_patched, [])


def _flush_loop(loop: asyncio.AbstractEventLoop, timeout: float = 5.0) -> None:
    """Wait for all pending loop callbacks to run."""
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(timeout=timeout)


# ---------------------------------------------------------------------------
# AC1 – record saved BEFORE RESULT is published
# ---------------------------------------------------------------------------


class TestSaveBeforeResult:
    """The generation record is saved before the RESULT event enters the queue."""

    def setup_method(self) -> None:
        self.loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(
            target=self.loop.run_forever, daemon=True
        )
        self.loop_thread.start()
        self.queue: asyncio.Queue = asyncio.Queue()

    def teardown_method(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.loop_thread.join(timeout=5)
        self.loop.close()

    def test_record_saved_before_result_published(self, tmp_path: Path) -> None:
        """Save must complete before RESULT is enqueued."""
        op_order: list[str] = []

        @asynccontextmanager
        async def session_factory() -> Any:
            class FakeSession:
                def add(self, obj: Any) -> None:
                    pass

                async def commit(self) -> None:
                    op_order.append("save")

            yield FakeSession()

        # Instant backoff so tests stay fast.
        async def instant_backoff(attempt: int) -> None:
            await asyncio.sleep(0)

        user_id = uuid.uuid4()
        ctx = _build_ctx(
            self.loop,
            self.queue,
            user_id=user_id,
            session_factory=session_factory,
            output_dir=tmp_path,
            save_backoff_fn=instant_backoff,
        )

        # Intercept queue.put_nowait to track when RESULT lands.
        original_put = self.queue.put_nowait

        def tracking_put(item: Any) -> None:
            if isinstance(item, dict) and item.get("event") == SSEEventName.RESULT:
                op_order.append("result")
            original_put(item)

        self.queue.put_nowait = tracking_put  # type: ignore[method-assign]

        question_id = ctx.manifest[0].question_id
        _run_worker(ctx, _make_do_generate(question_id))
        _flush_loop(self.loop)

        assert "save" in op_order, "record must be saved"
        assert "result" in op_order, "RESULT must be published"
        assert op_order.index("save") < op_order.index("result"), (
            "save must complete before RESULT is published"
        )

    def test_result_never_dequeued_is_still_saved(self, tmp_path: Path) -> None:
        """A RESULT that is never consumed by the stream consumer is still saved."""
        rows: list[Any] = []

        @asynccontextmanager
        async def session_factory() -> Any:
            class FakeSession:
                def add(self, obj: Any) -> None:
                    rows.append(obj)

                async def commit(self) -> None:
                    pass

            yield FakeSession()

        async def instant_backoff(attempt: int) -> None:
            await asyncio.sleep(0)

        user_id = uuid.uuid4()
        ctx = _build_ctx(
            self.loop,
            self.queue,
            user_id=user_id,
            session_factory=session_factory,
            output_dir=tmp_path,
            save_backoff_fn=instant_backoff,
        )

        question_id = ctx.manifest[0].question_id
        _run_worker(ctx, _make_do_generate(question_id))
        # Deliberately do NOT drain the queue.
        _flush_loop(self.loop)

        assert len(rows) == 1, (
            "record must be saved even if the RESULT event is never dequeued"
        )


# ---------------------------------------------------------------------------
# AC3 – failing save retries, then Sentry, then RESULT still published
# ---------------------------------------------------------------------------


class TestSaveRetryAndSentry:
    """Exhausted retries report to Sentry; RESULT is still published."""

    def setup_method(self) -> None:
        self.loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(
            target=self.loop.run_forever, daemon=True
        )
        self.loop_thread.start()
        self.queue: asyncio.Queue = asyncio.Queue()

    def teardown_method(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.loop_thread.join(timeout=5)
        self.loop.close()

    def test_failing_save_retries_n_times_then_sentry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failing session factory → N retries → Sentry → RESULT still published."""
        import server.generate.persistence as persistence_module

        attempt_count = [0]

        @asynccontextmanager
        async def failing_factory() -> Any:
            attempt_count[0] += 1
            raise RuntimeError("DB is down")
            yield  # type: ignore[misc]  # unreachable — satisfies async context manager

        captured_exceptions: list[Exception] = []
        fake_sentry = SimpleNamespace(
            capture_exception=lambda exc: captured_exceptions.append(exc)
        )
        monkeypatch.setattr(persistence_module, "sentry_sdk", fake_sentry)

        async def instant_backoff(attempt: int) -> None:
            await asyncio.sleep(0)

        user_id = uuid.uuid4()
        ctx = _build_ctx(
            self.loop,
            self.queue,
            user_id=user_id,
            session_factory=failing_factory,
            output_dir=tmp_path,
            save_backoff_fn=instant_backoff,
        )

        question_id = ctx.manifest[0].question_id
        _run_worker(ctx, _make_do_generate(question_id))
        _flush_loop(self.loop)

        from server.generate.persistence import SAVE_MAX_ATTEMPTS

        assert attempt_count[0] == SAVE_MAX_ATTEMPTS, (
            f"must retry exactly {SAVE_MAX_ATTEMPTS} times, got {attempt_count[0]}"
        )
        assert len(captured_exceptions) == 1, (
            "Sentry must be notified once when retries are exhausted"
        )

        # RESULT must still be published even after save failure.
        _flush_loop(self.loop)
        events: list[dict] = []
        while not self.queue.empty():
            events.append(self.queue.get_nowait())
        result_events = [e for e in events if e.get("event") == SSEEventName.RESULT]
        assert len(result_events) == 1, (
            "RESULT must be published even after save failure"
        )

        # Question is NOT reported as saved: RESULT payload must NOT contain
        # generation_record_id or saved=True.
        result_payload = result_events[0].get("payload", {})
        assert "generation_record_id" not in result_payload, (
            "failed save must not populate generation_record_id in RESULT"
        )
        assert result_payload.get("saved") is not True, (
            "failed save must not set saved=True in RESULT payload"
        )


# ---------------------------------------------------------------------------
# AC4 – scheduling failure (loop closed) does not prevent RESULT publication
# ---------------------------------------------------------------------------


class TestSaveSchedulingFailure:
    """If asyncio.run_coroutine_threadsafe raises, RESULT must still be published."""

    def setup_method(self) -> None:
        self.loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(
            target=self.loop.run_forever, daemon=True
        )
        self.loop_thread.start()
        self.queue: asyncio.Queue = asyncio.Queue()

    def teardown_method(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.loop_thread.join(timeout=5)
        self.loop.close()

    def test_closed_loop_still_publishes_result(self, tmp_path: Path) -> None:
        """Scheduling failure (closed loop) is caught; RESULT is still published.

        Simulates asyncio.run_coroutine_threadsafe raising RuntimeError (which
        CPython raises when the target loop is closed).  The publisher uses a
        live loop via its own reference, so RESULT can still be enqueued.
        """

        class _ClosedLoop:
            """Fake loop whose call_soon_threadsafe always raises, simulating a
            closed event loop as seen by asyncio.run_coroutine_threadsafe."""

            def call_soon_threadsafe(self, *_args: Any, **_kwargs: Any) -> None:
                raise RuntimeError("Event loop is closed")

        user_id = uuid.uuid4()
        # Build ctx with the real loop so the publisher can enqueue RESULT.
        ctx = _build_ctx(
            self.loop,
            self.queue,
            user_id=user_id,
            session_factory=None,
            output_dir=tmp_path,
        )
        # Replace ctx.loop with a fake closed loop AFTER publisher is initialised
        # (publisher captured the real loop at construction time and is unaffected).
        ctx_closed = dataclasses.replace(ctx, loop=_ClosedLoop())  # type: ignore[arg-type]

        question_id = ctx.manifest[0].question_id
        _run_worker(ctx_closed, _make_do_generate(question_id))
        _flush_loop(self.loop)

        events: list[dict] = []
        while not self.queue.empty():
            events.append(self.queue.get_nowait())
        result_events = [e for e in events if e.get("event") == SSEEventName.RESULT]
        assert len(result_events) == 1, (
            "RESULT must be published even when the save loop is closed"
        )
