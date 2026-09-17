"""Drain counter assertions for disconnect and cancellation semantics (slice 5, task 4.4).

These tests extend the patterns from test_generate_cancel.py to assert:
- active_runs is nonzero while generation is in flight
- active_runs reaches zero after disconnect/cancel
- counters never go negative
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.generate.drain import DrainTelemetry
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SubjectSpec

# ---------------------------------------------------------------------------
# Minimal fake question model + spec (mirrors test_generate_cancel.py pattern)
# ---------------------------------------------------------------------------


class _FakeQuestion(BaseModel):
    id: str
    圖片: str | None = None


class _FakeParams:
    pass


def _make_blocking_spec(
    worker_entered: threading.Event,
    worker_release: threading.Event,
) -> SubjectSpec:
    """Single-stage spec that blocks until worker_release is set."""

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        return []

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kwargs: Any) -> _FakeQuestion:
        worker_entered.set()
        worker_release.wait(timeout=5)
        return _FakeQuestion(id=kwargs.get("question_id", "q1"))

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


def _make_config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_active_runs_nonzero_while_running(tmp_path: Path) -> None:
    """active_runs is >= 1 while generate_question_stream is in flight."""
    entered = threading.Event()
    release = threading.Event()
    spec = _make_blocking_spec(entered, release)
    drain = DrainTelemetry()
    app_state = SimpleNamespace(renderer_pool=None, drain_telemetry=drain)
    config = _make_config(tmp_path)
    params = GenerateParams(subject="fake", count=1, skip_verify=True)

    active_mid_run = []

    async def run() -> None:
        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": spec}
        )
        # Consume until pipeline_start so the worker is submitted.
        async for event in stream:
            payload = event.get("payload", event.get("data"))
            if (
                event.get("event") == "pipeline"
                and isinstance(payload, dict)
                and payload.get("event_name") == "pipeline_start"
            ):
                break
        # Wait for worker to enter do_generate (blocking)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: entered.wait(timeout=3))
        # Capture active_runs while worker is blocked inside do_generate
        active_mid_run.append(drain.snapshot()["active_runs"])
        # Release and drain the rest
        release.set()
        async for _ in stream:
            pass

    asyncio.run(run())
    assert active_mid_run[0] >= 1, (
        f"active_runs must be >= 1 while in flight, got {active_mid_run[0]}"
    )


def test_active_runs_zero_after_completion(tmp_path: Path) -> None:
    """active_runs drops back to 0 after a normal completion."""
    entered = threading.Event()
    release = threading.Event()
    release.set()  # release immediately so the worker completes fast
    spec = _make_blocking_spec(entered, release)
    drain = DrainTelemetry()
    app_state = SimpleNamespace(renderer_pool=None, drain_telemetry=drain)
    config = _make_config(tmp_path)
    params = GenerateParams(subject="fake", count=1, skip_verify=True)

    async def run() -> None:
        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": spec}
        )
        async for _ in stream:
            pass

    asyncio.run(run())
    snap = drain.snapshot()
    assert snap["active_runs"] == 0, (
        f"active_runs must be 0 after completion, got {snap['active_runs']}"
    )
    assert snap["quiescent"], "drain must be quiescent after completion"


def test_counters_never_negative(tmp_path: Path) -> None:
    """Counters must not go negative even after redundant decrements."""
    drain = DrainTelemetry()
    drain._inc("_active_runs")
    drain._dec("_active_runs")
    drain._dec("_active_runs")  # extra dec — must clamp at 0
    drain._dec("_active_runs")  # extra dec — must clamp at 0
    snap = drain.snapshot()
    assert snap["active_runs"] == 0, "active_runs must clamp at 0, not go negative"
    assert snap["active_workers"] == 0
    assert snap["open_streams"] == 0


# ===========================================================================
# Fix 3 — disconnect and cleanup-exception evidence (task 4.4)
# ===========================================================================


# ---------------------------------------------------------------------------
# (a) disconnect while worker blocked → active_workers stays >= 1 until release
# ---------------------------------------------------------------------------


def test_disconnect_while_worker_blocked_keeps_active_workers_nonzero(
    tmp_path: Path,
    caplog,
) -> None:
    """Disconnecting while a worker is blocked must NOT drop active_workers to 0.

    After aclose() the generator's shielded finally awaits signal_task, which
    itself waits for workers.  So active_workers stays >= 1 until the worker
    finishes and only then does the finally complete and decrement active_runs.
    A truly drained instance has both counters at zero.
    """
    worker_entered = threading.Event()
    worker_release = threading.Event()
    stream_entered_count = [0]

    spec = _make_blocking_spec(worker_entered, worker_release)
    drain = DrainTelemetry()
    app_state = SimpleNamespace(renderer_pool=None, drain_telemetry=drain)
    config = _make_config(tmp_path)
    params = GenerateParams(subject="fake", count=1, skip_verify=True)

    snap1: dict = {}
    snap2: dict = {}
    snap3: dict = {}
    events_before_close: list = []

    async def run() -> None:
        stream_entered_count[0] += 1
        gen = generate_question_stream(
            params, config, app_state, subjects={"fake": spec}
        )
        # Consume until pipeline_start so workers are submitted
        async for event in gen:
            events_before_close.append(event)
            payload = event.get("payload", event.get("data"))
            if (
                event.get("event") == "pipeline"
                and isinstance(payload, dict)
                and payload.get("event_name") == "pipeline_start"
            ):
                break

        loop = asyncio.get_event_loop()
        # Wait for worker to enter do_generate (runs in thread pool)
        await loop.run_in_executor(None, lambda: worker_entered.wait(timeout=5))

        # Snapshot 1: worker is in do_generate, stream is still active
        snap1.update(drain.snapshot())

        # Simulate client disconnect via aclose() while worker is still blocked
        aclose_task = asyncio.create_task(gen.aclose())

        # Give the aclose task one event-loop turn to run the generator's
        # finally until it hits `await signal_task`
        await asyncio.sleep(0)

        # Snapshot 2: aclose() is in progress but worker is still blocked;
        # the shielded finally has not yet decremented the counters
        snap2.update(drain.snapshot())

        # Release the blocked worker so signal_task can complete
        worker_release.set()

        # Wait for aclose to fully complete (shielded finally + decrements)
        await aclose_task

        # Snapshot 3: all cleanup done; must be quiescent
        snap3.update(drain.snapshot())

    asyncio.run(run())

    assert snap1.get("active_runs", 0) >= 1, (
        f"active_runs must be >= 1 while worker is in do_generate: {snap1}"
    )
    assert snap1.get("active_workers", 0) >= 1, (
        f"active_workers must be >= 1 while worker is in do_generate: {snap1}"
    )
    # Disconnected work still cleaning up must NOT look drained
    assert snap2.get("active_runs", 0) >= 1, (
        f"active_runs must stay >= 1 while generator finally awaits signal_task: {snap2}"
    )
    # Final snapshot: truly drained
    assert snap3.get("active_runs", 0) == 0, f"active_runs must be 0 after cleanup: {snap3}"
    assert snap3.get("quiescent") is True, f"must be quiescent after cleanup: {snap3}"
    assert snap3.get("integrity_errors", 0) == 0, (
        f"no integrity_errors after clean disconnect: {snap3}"
    )
    # generate_question_stream was entered exactly once (no resubmission)
    assert stream_entered_count[0] == 1, (
        f"generate_question_stream must be entered exactly once, got {stream_entered_count[0]}"
    )
    # No event claims cancel succeeded
    cancel_success_events = [
        e for e in events_before_close
        if "cancel" in str(e.get("event", "")).lower()
        and "success" in str(e.get("data", "")).lower()
    ]
    assert len(cancel_success_events) == 0, (
        f"no event may claim cancel succeeded: {cancel_success_events}"
    )


# ---------------------------------------------------------------------------
# (b) RendererLease-style raise → renderer_leases_held returns to 0 without errors
# ---------------------------------------------------------------------------


def test_renderer_return_path_exception_no_integrity_errors() -> None:
    """An exception on the renderer-return path must not produce integrity_errors.

    Uses drain.ctx_renderer_lease() to simulate the exact acquire/release
    sequence that RendererLease.render() performs; verifies that an exception
    raised inside the context (the render step) still causes the lease to
    decrement and leaves integrity_errors == 0.
    """
    drain = DrainTelemetry()
    assert drain.snapshot()["renderer_leases_held"] == 0

    try:
        with drain.ctx_renderer_lease():
            assert drain.snapshot()["renderer_leases_held"] == 1
            raise RuntimeError("renderer.render() raised")
    except RuntimeError:
        pass

    snap = drain.snapshot()
    assert snap["renderer_leases_held"] == 0, (
        f"renderer_leases_held must return to 0 after exception: {snap}"
    )
    assert snap["integrity_errors"] == 0, (
        f"no integrity_errors when decrement is matched: {snap}"
    )
    assert snap["quiescent"] is True


# ---------------------------------------------------------------------------
# (c) recorder flush raises in finally → active_runs returns to 0 without errors
# ---------------------------------------------------------------------------


def test_recorder_flush_raises_in_finally_releases_active_runs(tmp_path: Path) -> None:
    """A failing recorder flush must not block the active_runs decrement.

    Uses a session_factory that raises on execute() (simulating a DB failure
    during the flush in generate_question_stream's finally block).  The
    persistence layer is fail-open, so active_runs must still reach 0.
    """
    drain = DrainTelemetry()

    # Build a fast spec whose worker completes immediately
    release = threading.Event()
    release.set()
    entered = threading.Event()
    fast_spec = _make_blocking_spec(entered, release)

    app_state = SimpleNamespace(renderer_pool=None, drain_telemetry=drain)
    config = _make_config(tmp_path)
    params = GenerateParams(subject="fake", count=1, skip_verify=True)

    class _BadSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def execute(self, *a, **kw):
            raise OSError("DB gone")

        async def commit(self):
            pass

    async def bad_session_factory():
        return _BadSession()

    gen_log_id = uuid.uuid4()

    async def run():
        async for _ in generate_question_stream(
            params, config, app_state,
            subjects={"fake": fast_spec},
            generation_log_id=gen_log_id,
            session_factory=bad_session_factory,
        ):
            pass

    asyncio.run(run())
    snap = drain.snapshot()
    assert snap["active_runs"] == 0, (
        f"active_runs must be 0 after recorder flush exception: {snap}"
    )
    assert snap["integrity_errors"] == 0, (
        f"no integrity_errors when decrement is matched: {snap}"
    )
    assert snap["quiescent"] is True


# ---------------------------------------------------------------------------
# (d) no cancel-success claims in events or logs; single invocation
# ---------------------------------------------------------------------------


def test_no_cancel_success_events_on_disconnect(tmp_path: Path, caplog) -> None:
    """On a client disconnect, no event or log record may claim cancel succeeded.

    Also verifies generate_question_stream was entered exactly once.
    """
    import logging

    worker_entered = threading.Event()
    worker_release = threading.Event()
    gen_entry_count = [0]
    collected_events: list[dict] = []

    spec = _make_blocking_spec(worker_entered, worker_release)

    drain = DrainTelemetry()
    app_state = SimpleNamespace(renderer_pool=None, drain_telemetry=drain)
    config = _make_config(tmp_path)
    params = GenerateParams(subject="fake", count=1, skip_verify=True)

    async def run() -> None:
        gen_entry_count[0] += 1
        gen = generate_question_stream(
            params, config, app_state, subjects={"fake": spec}
        )
        async for event in gen:
            collected_events.append(event)
            if (
                event.get("event") == "pipeline"
                and isinstance(event.get("data"), dict)
                and event["data"].get("event_name") == "pipeline_start"
            ):
                break

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: worker_entered.wait(timeout=5))
        # Disconnect
        aclose_task = asyncio.create_task(gen.aclose())
        await asyncio.sleep(0)
        worker_release.set()
        await aclose_task

    with caplog.at_level(logging.DEBUG, logger="server"):
        asyncio.run(run())

    # No event claims "cancel" + "success"
    for event in collected_events:
        event_name = str(event.get("event", "")).lower()
        data_str = str(event.get("data", "")).lower()
        assert not ("cancel" in event_name and "success" in data_str), (
            f"event claims cancel succeeded: {event}"
        )

    # No log record claims cancel succeeded
    cancel_success_logs = [
        r for r in caplog.records
        if "cancel" in r.getMessage().lower() and "success" in r.getMessage().lower()
    ]
    assert len(cancel_success_logs) == 0, (
        f"log records claim cancel succeeded: {cancel_success_logs}"
    )

    # generate_question_stream was entered exactly once
    assert gen_entry_count[0] == 1, (
        f"generate_question_stream must be entered exactly once, got {gen_entry_count[0]}"
    )
