"""Tests for A1/A2/A3/A4: cancel signal stops workers on disconnect (issue #628)."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anyio
import anyio.to_thread
import pytest
from pydantic import BaseModel
from sqlalchemy.pool import StaticPool

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.generate import routes as _gen_routes
from server.generate import service as _gen_service
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SubjectSpec
from server.models import Base, User
from server.rate_limit import limiter

# ---------------------------------------------------------------------------
# Minimal question model for the fake spec.
# ---------------------------------------------------------------------------


class _FakeQuestion(BaseModel):
    id: str
    圖片: str | None = None


class _FakeParams:
    """Opaque stand-in for sampled params; fake do_generate ignores it."""


class _FailingFlushRecorder:
    """Recorder seam used to prove cleanup failures do not abort the stream."""

    def __init__(self) -> None:
        self.flush_calls = 0

    async def flush(self) -> None:
        self.flush_calls += 1
        raise RuntimeError("injected recorder cleanup failure")


# ---------------------------------------------------------------------------
# Helper: build a fake math spec that does not need app_state.curriculum
# ---------------------------------------------------------------------------


def _make_blocking_spec(
    stage_calls: list[str],
    first_call_started: threading.Event,
    first_call_release: threading.Event,
) -> SubjectSpec:
    """Two-stage fake spec:
    - Stage 1: blocks until first_call_release is set, records 'stage1'.
    - Between stages: checks is_cancelled(); if True raises GenerationCancelled.
    - Stage 2: records 'stage2' — MUST NOT run after a cancel.
    """

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(
        params: Any, count: int, base_seed: Any, overrides: dict,
        config: Any, creative_planning: bool,
        decoded_subquestion_configs: Any, **_kw: Any,
    ) -> list:
        return []

    def params_from_resolved_payload(payload: dict[str, Any], overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kwargs: Any) -> _FakeQuestion:
        # ── Stage 1 ────────────────────────────────────────────────────────
        stage_calls.append("stage1")
        first_call_started.set()
        first_call_release.wait(timeout=30)

        # ── Cancel boundary (mimics what generate_one_core / generate_one
        #   will do after the fix) ─────────────────────────────────────────
        is_cancelled = kwargs.get("is_cancelled")
        if is_cancelled is not None and is_cancelled():
            # Import at call time so the test works even before the class exists.
            from src.common.generation_core import GenerationCancelled  # type: ignore
            raise GenerationCancelled()

        # ── Stage 2 ────────────────────────────────────────────────────────
        stage_calls.append("stage2")
        return _FakeQuestion(id=kwargs["question_id"])

    def extract_prior_scope(question: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kwargs: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(config_server: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(config_server: Any, grade: Any) -> dict:  # pragma: no cover
        return {}

    return SubjectSpec(
        key="fake",
        question_id_prefix="fake_",
        exam_question_cls=_FakeQuestion,
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        params_from_resolved_payload=params_from_resolved_payload,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        patch_metadata=None,
        plan_core_questions=plan_core_questions,
        load_planner_stage=load_planner_stage,
        build_schemas=build_schemas,
    )


def _make_happy_spec(stage_calls: list[str]) -> SubjectSpec:
    """Non-blocking two-stage fake spec for the control test."""

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        return []

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kwargs: Any) -> _FakeQuestion:
        stage_calls.append("stage1")
        # No blocking — simulates a fast LLM call.
        stage_calls.append("stage2")
        return _FakeQuestion(id=kwargs["question_id"])

    def extract_prior_scope(question: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kwargs: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(config_server: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(config_server: Any, grade: Any) -> dict:  # pragma: no cover
        return {}

    return SubjectSpec(
        key="fake",
        question_id_prefix="fake_",
        exam_question_cls=_FakeQuestion,
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        params_from_resolved_payload=params_from_resolved_payload,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        patch_metadata=None,
        plan_core_questions=plan_core_questions,
        load_planner_stage=load_planner_stage,
        build_schemas=build_schemas,
    )


# ---------------------------------------------------------------------------
# A1 — Reproduce: worker must NOT start stage 2 after disconnect
# ---------------------------------------------------------------------------


def test_a1_cancel_stops_worker_before_next_stage(tmp_path: Path) -> None:
    """After disconnect, a worker that finished stage 1 must not start stage 2.

    This test MUST FAIL on current code (no cancel signal exists yet) because
    the fake do_generate's cancel check sees is_cancelled=None and proceeds to
    stage 2. After the fix, is_cancelled is set and stage 2 is skipped.
    """
    stage_calls: list[str] = []
    first_call_started = threading.Event()
    first_call_release = threading.Event()

    fake_spec = _make_blocking_spec(stage_calls, first_call_started, first_call_release)

    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    params = GenerateParams(subject="fake", count=1, skip_verify=True)
    app_state = SimpleNamespace(renderer_pool=None)

    async def run() -> None:
        stream = generate_question_stream(
            params,
            config,
            app_state,
            subjects={"fake": fake_spec},
        )

        # Consume until pipeline_start; by then the worker is submitted.
        async for event in stream:
            if (
                event["event"] == "pipeline"
                and isinstance(event.get("payload", event.get("data")), dict)
                and event.get("payload", event.get("data", {})).get("event_name") == "pipeline_start"  # noqa: E501
            ):
                break

        # Wait for stage 1 to actually start in the worker thread.
        got_started = await asyncio.get_event_loop().run_in_executor(
            None, lambda: first_call_started.wait(15.0)
        )
        assert got_started, "Timed out waiting for stage 1 to start in worker"

        # Release stage 1 shortly AFTER aclose() begins, so the cancel_event
        # is set before the worker checks it (via the service's finally block).
        def release_after_delay() -> None:
            time.sleep(0.20)
            first_call_release.set()

        t = threading.Thread(target=release_after_delay, daemon=True)
        t.start()

        # Simulate client disconnect: the generator's finally block runs here.
        # After the fix, that finally block sets cancel_event before awaiting
        # signal_task, so the worker will see is_cancelled()=True after stage 1.
        await stream.aclose()
        t.join(timeout=10)

    asyncio.run(run())

    assert stage_calls == ["stage1"], (
        f"Stage 2 must NOT run after disconnect. "
        f"stage_calls = {stage_calls!r}; expected ['stage1']. "
        f"This indicates the cancel signal is not being set on disconnect."
    )


# ---------------------------------------------------------------------------
# A2 — Control: a normal (non-cancelled) run still completes
# ---------------------------------------------------------------------------


def test_a2_normal_run_completes_with_both_stages(tmp_path: Path) -> None:
    """A run without disconnect emits all expected events and runs both stages."""
    stage_calls: list[str] = []
    fake_spec = _make_happy_spec(stage_calls)

    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    params = GenerateParams(subject="fake", count=1, skip_verify=True)
    app_state = SimpleNamespace(renderer_pool=None)

    async def collect() -> list[dict]:
        events: list[dict] = []
        async for evt in generate_question_stream(
            params,
            config,
            app_state,
            subjects={"fake": fake_spec},
        ):
            events.append(evt)
        return events

    events = asyncio.run(collect())
    event_types = [e["event"] for e in events]

    assert event_types[0] == "started", f"First event must be 'started'; got {event_types}"
    assert event_types[-1] == "done", f"Last event must be 'done'; got {event_types}"
    result_events = [e for e in events if e["event"] == "result"]
    assert len(result_events) == 1, f"Expected 1 result; got {len(result_events)}"

    # Both stages must have been called in a normal (non-cancelled) run.
    assert stage_calls == ["stage1", "stage2"], (
        f"Normal run must complete both stages; got stage_calls = {stage_calls!r}"
    )


def test_cleanup_recorder_failure_still_publishes_done(tmp_path: Path) -> None:
    """A recorder cleanup exception cannot replace the settled stream ending."""
    stage_calls: list[str] = []
    fake_spec = _make_happy_spec(stage_calls)
    failing_recorder = _FailingFlushRecorder()
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    params = GenerateParams(subject="fake", count=1, skip_verify=True)
    app_state = SimpleNamespace(renderer_pool=None)
    original_factory = _gen_service.make_figure_policy_trail_recorder
    _gen_service.make_figure_policy_trail_recorder = (  # type: ignore[assignment]
        lambda **_kwargs: failing_recorder
    )

    async def collect() -> list[dict]:
        events: list[dict] = []
        async for event in generate_question_stream(
            params,
            config,
            app_state,
            generation_log_id=uuid.uuid4(),
            subjects={"fake": fake_spec},
        ):
            events.append(event)
        return events

    try:
        events = asyncio.run(collect())
    finally:
        _gen_service.make_figure_policy_trail_recorder = original_factory  # type: ignore[assignment]

    assert events[-1]["event"] == "done"
    assert failing_recorder.flush_calls > 0


# ---------------------------------------------------------------------------
# A3 — Aborted run: no error SSE event is emitted on cancel (clean exit)
# ---------------------------------------------------------------------------


def test_a3_aborted_run_emits_no_error_event(tmp_path: Path) -> None:
    """After disconnect, the worker exits cleanly without emitting an error event.

    The route layer (routes.py) handles persisting 'aborted'; at the service seam
    we verify that GenerationCancelled does not propagate as an error event.
    """
    first_call_started = threading.Event()
    first_call_release = threading.Event()
    stage_calls: list[str] = []

    fake_spec = _make_blocking_spec(stage_calls, first_call_started, first_call_release)

    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    params = GenerateParams(subject="fake", count=1, skip_verify=True)
    app_state = SimpleNamespace(renderer_pool=None)

    collected_events: list[dict] = []

    async def run() -> None:
        stream = generate_question_stream(
            params,
            config,
            app_state,
            subjects={"fake": fake_spec},
        )

        async for event in stream:
            collected_events.append(event)
            if (
                event["event"] == "pipeline"
                and isinstance(event.get("payload", event.get("data")), dict)
                and event.get("payload", event.get("data", {})).get("event_name") == "pipeline_start"  # noqa: E501
            ):
                break

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: first_call_started.wait(15.0)
        )

        def release_later() -> None:
            time.sleep(0.20)
            first_call_release.set()

        t = threading.Thread(target=release_later, daemon=True)
        t.start()
        await stream.aclose()
        t.join(timeout=10)

    asyncio.run(run())

    error_events = [e for e in collected_events if e["event"] == "error"]
    assert error_events == [], (
        f"A clean cancel must not emit any error SSE events; got {error_events!r}"
    )
    assert [e for e in collected_events if e["event"] == "question_terminal"] == [], (
        "a disconnect is not confirmed cancellation and must not emit a terminal"
    )
    # Stage 1 ran; stage 2 did not (verified by A1).
    assert "stage1" in stage_calls

# ---------------------------------------------------------------------------
# A4 — HTTP route seam: HTTP disconnect must flow to stream.aclose()
# ---------------------------------------------------------------------------


def _make_polling_cancel_spec(
    stage_calls: list[str],
    first_call_started: threading.Event,
    worker_done: threading.Event,
) -> SubjectSpec:
    """Fake spec whose do_generate polls is_cancelled() every 50 ms.

    Unlike _make_blocking_spec this never waits on a release event — it exits
    only when is_cancelled() becomes True (cancel path) or a 10 s safety
    deadline passes (shouldn't happen in tests).  This makes the A4 route-seam
    test deterministic: the test closes the HTTP connection, the ASGI cancel
    chain sets cancel_event within a few hundred ms, and the worker picks it
    up on the next poll tick without any fixed sleep on the test side.

    worker_done is set in the finally block so the test knows when to assert.
    """
    from src.common.generation_core import GenerationCancelled  # noqa: PLC0415

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(
        params: Any,
        count: int,
        base_seed: Any,
        overrides: dict,
        config: Any,
        creative_planning: bool,
        decoded_subquestion_configs: Any,
        **_kw: Any,
    ) -> list:
        return []

    def params_from_resolved_payload(
        payload: dict[str, Any], overrides: dict
    ) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kwargs: Any) -> _FakeQuestion:
        try:
            stage_calls.append("stage1")
            first_call_started.set()
            is_cancelled = kwargs.get("is_cancelled")
            # Poll every 50 ms until cancelled or a 10 s safety deadline.
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if is_cancelled is not None and is_cancelled():
                    raise GenerationCancelled()
                time.sleep(0.05)
            # Safety-deadline path: behave as if not cancelled.
            stage_calls.append("stage2")
            return _FakeQuestion(id=kwargs["question_id"])
        finally:
            worker_done.set()

    def extract_prior_scope(question: Any) -> None:
        return None

    def plan_core_questions(
        client: Any, topic: str, **kwargs: Any
    ) -> list:  # pragma: no cover
        return []

    def load_planner_stage(
        config_server: Any, grade: Any
    ) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(
        config_server: Any, grade: Any
    ) -> dict:  # pragma: no cover
        return {}

    return SubjectSpec(
        key="fake",
        question_id_prefix="fake_",
        exam_question_cls=_FakeQuestion,
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        params_from_resolved_payload=params_from_resolved_payload,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        patch_metadata=None,
        plan_core_questions=plan_core_questions,
        load_planner_stage=load_planner_stage,
        build_schemas=build_schemas,
    )


def test_a4_route_seam_cancel_stops_worker(tmp_path: Path) -> None:
    """HTTP disconnect must flow: route CancelledError → aclose() → cancel_event.set()
    → worker exits at stage boundary without running stage 2.

    Design rationale
    ----------------
    Neither TestClient nor httpx.AsyncClient+ASGITransport reliably delivers
    ``http.disconnect`` while the ASGI app is still streaming (TestClient uses
    synchronous threading that doesn't propagate mid-stream disconnect;
    ASGITransport's receive() only fires http.disconnect after response_complete
    is set).

    This test drives the FastAPI app directly as an ASGI callable with a
    hand-rolled ``receive`` coroutine.  A ``disconnect_event`` (asyncio.Event)
    is held in the test; ``receive()`` races it against ``response_complete``
    and returns ``{"type": "http.disconnect"}`` as soon as either fires.  This
    perfectly mimics a real TCP client that drops the connection mid-stream.

    Cancel chain once disconnect_event is set:
      receive() returns http.disconnect
      → EventSourceResponse.listen_for_disconnect() cancels the generator task
      → asyncio.CancelledError raised in event_generator()
      → route: except CancelledError → await stream.aclose()
      → proxy wrapper finally: await inner.aclose()
      → generate_question_stream finally: cancel_event.set() + await signal_task
      → polling worker sees is_cancelled() == True within 50 ms
      → raises GenerationCancelled; stage 2 never runs

    ``worker_done`` (threading.Event) signals when the worker exits.
    No fixed sleep on the test side makes this deterministic.
    """
    stage_calls: list[str] = []
    first_call_started = threading.Event()
    worker_done = threading.Event()

    fake_spec = _make_polling_cancel_spec(stage_calls, first_call_started, worker_done)

    config = ServerConfig(
        api_key="x",
        gemini_api_key="x",
        jwt_secret="test-secret",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )

    # ── Build a fully resolved math payload → query-string bytes ───────────────
    import urllib.parse  # noqa: PLC0415

    from src.common.resolver import resolve as _resolve  # noqa: PLC0415

    partial: dict[str, Any] = {
        "subject": "math",
        "seed": 1,
        "skip_verify": True,
    }
    resolved = _resolve(partial).payload
    wire: dict[str, Any] = {k: v for k, v in resolved.items() if v is not None}
    wire["stream_version"] = 2  # #742: stream_version gate
    qs_bytes = urllib.parse.urlencode(wire, doseq=True).encode()

    original_stream = _gen_routes.generate_question_stream

    async def _run() -> None:
        # ── DB — single engine/pool for the lifetime of this event loop ────
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        _SessionLocal = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        test_user = User(id=uuid.uuid4(), email="route-cancel@example.com")
        async with _SessionLocal() as session:
            session.add(test_user)
            await session.commit()

        async def _override_session() -> Any:
            async with _SessionLocal() as sess:
                yield sess

        # ── Patch generate_question_stream at the route level ──────────────
        # The route calls stream.aclose() on disconnect, which throws
        # GeneratorExit into this proxy.  The proxy MUST explicitly call
        # inner.aclose() in its finally block so that generate_question_stream's
        # own finally block runs (setting cancel_event).  A bare
        # ``async for … yield`` loop does NOT propagate GeneratorExit to the
        # inner generator synchronously.
        async def _stream_with_fake(
            params: Any, config_: Any, app_state: Any, **kwargs: Any
        ) -> Any:
            fake_params = params.model_copy(update={"subject": "fake"})
            kwargs["subjects"] = {"fake": fake_spec}
            kwargs["session_factory"] = _SessionLocal
            inner = _gen_service.generate_question_stream(
                fake_params, config_, app_state, **kwargs
            )
            try:
                async for event in inner:
                    yield event
            finally:
                # Explicitly close the inner generator so its finally block
                # (cancel_event.set() + await signal_task) runs when
                # GeneratorExit is thrown into this proxy by route.
                await inner.aclose()

        _gen_routes.generate_question_stream = _stream_with_fake  # type: ignore
        limiter.reset()

        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: test_user
        app.dependency_overrides[get_async_session] = _override_session
        app.dependency_overrides[get_config] = lambda: config

        try:
            # ── ASGI primitives ────────────────────────────────────────────────
            disconnect_event = asyncio.Event()
            response_complete = asyncio.Event()

            scope: dict[str, Any] = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "headers": [
                    (b"accept", b"text/event-stream"),
                ],
                "scheme": "http",
                "path": "/api/generate",
                "raw_path": b"/api/generate",
                "query_string": qs_bytes,
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 12345),
                "root_path": "",
            }

            request_sent = False

            async def receive() -> dict[str, Any]:
                nonlocal request_sent
                if not request_sent:
                    request_sent = True
                    return {
                        "type": "http.request",
                        "body": b"",
                        "more_body": False,
                    }
                # Race disconnect vs. response complete — return as soon as
                # either fires.  This mimics a TCP client dropping mid-stream.
                loop = asyncio.get_event_loop()
                disc = loop.create_task(disconnect_event.wait())
                done_ev = loop.create_task(response_complete.wait())
                try:
                    await asyncio.wait(
                        {disc, done_ev}, return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    disc.cancel()
                    done_ev.cancel()
                return {"type": "http.disconnect"}

            async def send(message: dict[str, Any]) -> None:
                if message["type"] == "http.response.body":
                    if not message.get("more_body", False):
                        response_complete.set()

            # Run the ASGI app in a background task.
            route_task = asyncio.create_task(app(scope, receive, send))

            # Wait for stage 1 to start in the worker thread.
            started = await anyio.to_thread.run_sync(
                lambda: first_call_started.wait(15.0)
            )
            assert started, "Timed out waiting for stage 1 to start"

            # Signal HTTP disconnect while the route is still streaming.
            disconnect_event.set()

            # Wait for the polling worker to notice cancel_event and finish.
            done = await anyio.to_thread.run_sync(
                lambda: worker_done.wait(10.0)
            )
            assert done, "Worker did not finish within 10 s after disconnect"

            # Let the route task finish gracefully (it may be in the shielded
            # cleanup scope awaiting persist_aborted_once).
            try:
                await asyncio.wait_for(route_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                route_task.cancel()
                try:
                    await route_task
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            _gen_routes.generate_question_stream = original_stream  # type: ignore
            limiter.reset()
            await engine.dispose()

    anyio.run(_run)

    assert stage_calls == ["stage1"], (
        f"Stage 2 must NOT run after HTTP disconnect. "
        f"stage_calls = {stage_calls!r}; expected ['stage1']."
    )
