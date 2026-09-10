"""Tests for issue #689: what can stall a stream between `started` and `pipeline_start`."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SubjectSpec

# ---------------------------------------------------------------------------
# Shared fake model / params
# ---------------------------------------------------------------------------


class _FakeQuestion(BaseModel):
    id: str
    圖片: str | None = None


class _FakeParams:
    """Opaque stand-in for sampled params; fake do_generate ignores it."""


# ---------------------------------------------------------------------------
# Spec factories
# ---------------------------------------------------------------------------


def _make_happy_spec() -> SubjectSpec:
    """Non-blocking fake spec: do_generate returns immediately."""

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        return []

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
        return _FakeQuestion(id=kw["question_id"])

    def extract_prior_scope(q: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kw: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(cfg: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(cfg: Any, grade: Any) -> dict:  # pragma: no cover
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


def _make_blocking_spec(
    first_call_started: threading.Event,
    first_call_release: threading.Event,
) -> SubjectSpec:
    """Fake spec: do_generate blocks on first_call_release; does not check is_cancelled.

    Used to model an aborted run whose worker is still inside a long LLM/image call.
    The lack of a cancel check means the worker will hold the renderer for the full
    duration of the blocking call, matching the #689 staging observation.
    """

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        return []

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
        first_call_started.set()
        first_call_release.wait(timeout=30)
        return _FakeQuestion(id=kw["question_id"])

    def extract_prior_scope(q: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kw: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(cfg: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(cfg: Any, grade: Any) -> dict:  # pragma: no cover
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


def _make_slow_plan_spec() -> SubjectSpec:
    """plan_all_batch_briefs sleeps 0.6 s on the event loop (stand-in for a sync LLM call)."""

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        time.sleep(0.6)  # stand-in for a synchronous LLM planning call on the event loop
        return []

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
        return _FakeQuestion(id=kw["question_id"])

    def extract_prior_scope(q: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kw: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(cfg: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(cfg: Any, grade: Any) -> dict:  # pragma: no cover
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
# Test 1 — xfail: empty renderer pool stalls after `started`
# ---------------------------------------------------------------------------


def test_empty_renderer_pool_stalls_after_started_with_no_client_visible_event(
    tmp_path: Path,
) -> None:
    """An empty renderer pool causes the stream to stall indefinitely after `started`.

    Desired behaviour (after fix): a client-visible event must arrive within 1 s
    even when no renderer is available.  Current behaviour: the generator blocks
    at ``await renderer_pool.get()`` so only ``: ping`` comments reach the client.
    The strict xfail captures the bug; remove the marker when the fix lands.
    """

    async def run() -> None:
        # Pool created inside the running loop; empty — no renderer available.
        pool: asyncio.Queue = asyncio.Queue()
        app_state = SimpleNamespace(renderer_pool=pool)
        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)
        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": _make_happy_spec()}
        )

        first = await stream.__anext__()
        assert first["event"] == "started"

        stalled = False
        try:
            await asyncio.wait_for(stream.__anext__(), timeout=1.0)
        except asyncio.TimeoutError:
            stalled = True
        finally:
            # aclose() here is before the generator's try/finally (the signal_task
            # was never created because the generator stalled before it), so
            # GeneratorExit propagates cleanly without hanging.
            await stream.aclose()

        # DESIRED: the next event should arrive within 1 s even with an empty pool.
        assert not stalled, (
            "expected a client-visible event within 1 s while the renderer pool is empty"
        )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 2 — green: renderer is returned to pool after a normal run
# ---------------------------------------------------------------------------


def test_renderer_is_returned_to_pool_after_run_completes(tmp_path: Path) -> None:
    """Green characterisation: the renderer sentinel is put back after a normal run."""

    async def run() -> tuple[list[dict], bool, bool]:
        sentinel = object()
        pool: asyncio.Queue = asyncio.Queue()
        pool.put_nowait(sentinel)
        app_state = SimpleNamespace(renderer_pool=pool)
        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)

        events: list[dict] = []
        async for evt in generate_question_stream(
            params, config, app_state, subjects={"fake": _make_happy_spec()}
        ):
            events.append(evt)

        pool_size_ok = pool.qsize() == 1
        sentinel_ok = pool.get_nowait() is sentinel
        return events, pool_size_ok, sentinel_ok

    events, pool_size_ok, sentinel_ok = asyncio.run(run())

    event_names = [e["event"] for e in events]
    assert event_names[0] == "started", f"first event must be 'started'; got {event_names[0]!r}"
    assert event_names[-1] == "done", f"last event must be 'done'; got {event_names[-1]!r}"

    pipeline_start_events = [
        e
        for e in events
        if e["event"] == "pipeline"
        and isinstance(e.get("data"), dict)
        and e["data"].get("event_name") == "pipeline_start"
    ]
    assert pipeline_start_events, "expected at least one pipeline_start event"

    result_events = [e for e in events if e["event"] == "result"]
    assert len(result_events) == 1, f"expected 1 result event; got {len(result_events)}"

    assert pool_size_ok, "pool should hold exactly 1 item after the run"
    assert sentinel_ok, "the returned item must be the same sentinel object"


# ---------------------------------------------------------------------------
# Test 3 — green: aborted run keeps renderer until its worker exits
# ---------------------------------------------------------------------------


def test_aborted_run_keeps_renderer_until_its_worker_exits(tmp_path: Path) -> None:
    """Green characterisation of the #689 root cause.

    The generator's finally block calls ``await signal_task`` before
    ``renderer_pool.put(html_renderer)``.  signal_task waits for all workers to
    finish.  A worker still inside a blocking call therefore holds the renderer
    for the full duration of that call.

    Note: with the #683 cancel signal the worker exits at the next stage
    boundary, so the hold is now bounded by one LLM/image call, not eliminated.
    """
    first_call_started = threading.Event()
    first_call_release = threading.Event()

    async def run() -> None:
        sentinel = object()
        pool: asyncio.Queue = asyncio.Queue()
        pool.put_nowait(sentinel)
        app_state = SimpleNamespace(renderer_pool=pool)
        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)
        fake_spec = _make_blocking_spec(first_call_started, first_call_release)

        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": fake_spec}
        )

        # Consume until pipeline_start; by then the worker is submitted to the executor.
        async for evt in stream:
            if (
                evt["event"] == "pipeline"
                and isinstance(evt.get("data"), dict)
                and evt["data"].get("event_name") == "pipeline_start"
            ):
                break

        # Wait for the worker to actually start inside do_generate.
        started_ok = await asyncio.get_event_loop().run_in_executor(
            None, lambda: first_call_started.wait(15.0)
        )
        assert started_ok, "timed out waiting for worker to enter do_generate"

        # Simulate a client disconnect: GeneratorExit is thrown at the `yield event`
        # suspend point, entering the finally block which does `await signal_task`.
        # signal_task cannot finish until the worker exits, so the pool stays empty.
        aclose_task = asyncio.create_task(stream.aclose())

        # Poll for 0.5 s, verifying the renderer stays held throughout.
        deadline = asyncio.get_event_loop().time() + 0.5
        all_checks_ok = True
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            if pool.qsize() != 0 or aclose_task.done():
                all_checks_ok = False
                break

        assert all_checks_ok, (
            "pool should stay empty and aclose_task should stay pending "
            "while the blocking worker holds the renderer"
        )

        # Release the worker; the renderer is returned only after the worker exits.
        first_call_release.set()
        await aclose_task

        assert pool.qsize() == 1, "renderer must be returned to pool after worker exits"
        assert pool.get_nowait() is sentinel, "returned item must be the original sentinel"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 4 — xfail: plan_all_batch_briefs blocks the event loop
# ---------------------------------------------------------------------------


def test_batch_brief_planning_does_not_block_event_loop(tmp_path: Path) -> None:
    """plan_all_batch_briefs must not block the event loop (issue #689 candidate 1).

    On current code the call runs directly on the event-loop thread.  For
    social_studies with creative_planning=True it makes a synchronous LLM call;
    the fake spec uses time.sleep(0.6) as a stand-in.

    A heartbeat task increments a counter every 0.05 s.  If the loop is blocked
    for 0.6 s, the counter barely advances between ``started`` and
    ``pipeline_start``.  On current code the difference is ~0-1 ticks, so
    ``assert … >= 5`` fails and the strict xfail passes.  After a fix (e.g. moving
    the call to a thread), the loop stays free and >= 5 ticks accumulate.
    """

    async def run() -> None:
        ticks = 0
        ticks_at_started: int | None = None
        ticks_at_pipeline_start: int | None = None

        async def heartbeat() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)
        # renderer_pool=None: pool acquisition is skipped, so only the planning
        # call can block the loop between `started` and `pipeline_start`.
        app_state = SimpleNamespace(renderer_pool=None)
        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": _make_slow_plan_spec()}
        )

        hb = asyncio.create_task(heartbeat())
        try:
            async for evt in stream:
                if evt["event"] == "started":
                    ticks_at_started = ticks
                elif (
                    evt["event"] == "pipeline"
                    and isinstance(evt.get("data"), dict)
                    and evt["data"].get("event_name") == "pipeline_start"
                ):
                    ticks_at_pipeline_start = ticks
                    break  # measurement complete; drain the rest below
        finally:
            hb.cancel()
            try:
                await hb
            except asyncio.CancelledError:
                pass
            await stream.aclose()

        assert ticks_at_started is not None, "did not see `started` event"
        assert ticks_at_pipeline_start is not None, "did not see `pipeline_start` event"

        diff = ticks_at_pipeline_start - ticks_at_started
        assert diff >= 5, (
            f"heartbeat only ticked {diff} time(s) between `started` and `pipeline_start`; "
            f"expected >= 5 to indicate the event loop was not blocked. "
            f"On current code plan_all_batch_briefs blocks the loop so ticks stay near 0."
        )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 4b — batch_briefs stage events bracket the planning call
# ---------------------------------------------------------------------------


def test_batch_briefs_stage_events_emitted_before_pipeline_start(tmp_path: Path) -> None:
    """Stream yields planner/batch_briefs/start before planning and planner/batch_briefs/end
    after it returns, both before pipeline_start, for every subject.

    The events are yielded directly from the generator (not drained from the queue),
    so they arrive before any pipeline event.
    """

    async def run() -> list[dict]:
        sentinel = object()
        pool: asyncio.Queue = asyncio.Queue()
        pool.put_nowait(sentinel)
        app_state = SimpleNamespace(renderer_pool=pool)
        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)
        events: list[dict] = []
        async for evt in generate_question_stream(
            params, config, app_state, subjects={"fake": _make_happy_spec()}
        ):
            events.append(evt)
        return events

    events = asyncio.run(run())

    # Extract stage events for the planner agent
    planner_stages = [
        e
        for e in events
        if e["event"] == "stage"
        and isinstance(e.get("data"), dict)
        and e["data"].get("agent") == "planner"
        and e["data"].get("stage") == "batch_briefs"
    ]
    assert len(planner_stages) == 2, (
        f"expected 2 planner/batch_briefs stage events (start + end); got {len(planner_stages)}"
    )
    assert planner_stages[0]["data"]["status"] == "start", (
        f"first planner/batch_briefs event should have status 'start'; "
        f"got {planner_stages[0]['data']['status']!r}"
    )
    assert planner_stages[1]["data"]["status"] == "end", (
        f"second planner/batch_briefs event should have status 'end'; "
        f"got {planner_stages[1]['data']['status']!r}"
    )

    # Both stage events must appear before pipeline_start
    pipeline_start_indices = [
        i
        for i, e in enumerate(events)
        if e["event"] == "pipeline"
        and isinstance(e.get("data"), dict)
        and e["data"].get("event_name") == "pipeline_start"
    ]
    assert pipeline_start_indices, "expected at least one pipeline_start event"
    first_pipeline_start_idx = pipeline_start_indices[0]

    for stage_evt in planner_stages:
        stage_idx = events.index(stage_evt)
        assert stage_idx < first_pipeline_start_idx, (
            f"planner/batch_briefs stage event (status={stage_evt['data']['status']!r}) "
            f"at index {stage_idx} must appear before pipeline_start at "
            f"index {first_pipeline_start_idx}"
        )


# ---------------------------------------------------------------------------
# Test 4c — cancel during planning: no worker starts, renderer returns
# ---------------------------------------------------------------------------


def _make_cancellable_plan_spec(
    plan_started: threading.Event,
    plan_release: threading.Event,
    generate_called: list[bool],
) -> SubjectSpec:
    """Spec whose plan_all_batch_briefs blocks until plan_release is set.

    do_generate appends True to generate_called so the test can assert it
    was never invoked after a disconnect during planning.
    """

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        plan_started.set()
        plan_release.wait(timeout=30)
        return []

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
        generate_called.append(True)
        return _FakeQuestion(id=kw["question_id"])

    def extract_prior_scope(q: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kw: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(cfg: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(cfg: Any, grade: Any) -> dict:  # pragma: no cover
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


def test_cancel_during_planning_does_not_start_workers_and_returns_renderer(
    tmp_path: Path,
) -> None:
    """When aclose() is called while plan_all_batch_briefs is running in its thread,
    no worker (do_generate) must start afterwards and the renderer must be returned.

    This covers the #700 guarantee: even when signal_task was never created (workers
    never submitted), the outer finally always returns the renderer.
    """
    plan_started = threading.Event()
    plan_release = threading.Event()
    generate_called: list[bool] = []

    async def run() -> None:
        sentinel = object()
        pool: asyncio.Queue = asyncio.Queue()
        pool.put_nowait(sentinel)
        app_state = SimpleNamespace(renderer_pool=pool)
        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)
        spec = _make_cancellable_plan_spec(plan_started, plan_release, generate_called)
        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": spec}
        )

        # Drive the stream in a task so we can disconnect concurrently.
        drain_events: list[dict] = []

        async def drain() -> None:
            async for evt in stream:
                drain_events.append(evt)

        drain_task = asyncio.create_task(drain())

        # Wait for the planning thread to actually start blocking.
        started_ok = await asyncio.get_event_loop().run_in_executor(
            None, lambda: plan_started.wait(15.0)
        )
        assert started_ok, "timed out waiting for plan_all_batch_briefs to start"

        # Disconnect: cancel the drain task (simulates a client disconnect while the
        # generator is suspended inside await asyncio.to_thread(...)).
        drain_task.cancel()
        try:
            await drain_task
        except (asyncio.CancelledError, Exception):
            pass

        # Release the planning thread after disconnect (simulates LLM returning).
        plan_release.set()

        # Give the thread and generator cleanup a moment to finish.
        await asyncio.sleep(0.2)

        assert pool.qsize() == 1, (
            "renderer must be returned to pool after aclose() during planning"
        )
        assert pool.get_nowait() is sentinel, "returned item must be the original sentinel"
        assert generate_called == [], (
            f"do_generate must not be called after disconnect during planning; "
            f"was called {len(generate_called)} time(s)"
        )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 5 — pool wait exceeds threshold → one WARNING logged
# ---------------------------------------------------------------------------


def test_pool_wait_timeout_logs_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the renderer pool wait exceeds the threshold, exactly one WARNING is logged.

    The module-level RENDERER_POOL_WAIT_WARN_THRESHOLD_S constant is monkeypatched
    to a small value so the test does not have to wait seconds for the warning.
    """
    import server.generate.service as svc  # noqa: PLC0415

    threshold = 0.05  # seconds — monkeypatched well below the default
    monkeypatch.setattr(svc, "RENDERER_POOL_WAIT_WARN_THRESHOLD_S", threshold)

    async def run() -> None:
        sentinel = object()
        pool: asyncio.Queue = asyncio.Queue()  # starts empty
        app_state = SimpleNamespace(renderer_pool=pool)
        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)
        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": _make_happy_spec()}
        )

        # Consume "started"
        first = await stream.__anext__()
        assert first["event"] == "started"

        # Consume "renderer/acquire/start" (emitted before pool.get())
        second = await stream.__anext__()
        assert second["event"] == "stage"
        assert second["data"]["agent"] == "renderer"
        assert second["data"]["status"] == "start"

        # Schedule putting an item in the pool after the threshold fires
        async def put_after_threshold() -> None:
            await asyncio.sleep(threshold * 4)
            await pool.put(sentinel)

        putter = asyncio.create_task(put_after_threshold())

        # This __anext__() call runs renderer_pool.get() (blocks until pool has item).
        # asyncio.wait_for inside the generator times out after `threshold`, logging
        # the warning, then waits again; put_after_threshold unblocks it.
        third = await stream.__anext__()
        assert third["event"] == "stage"
        assert third["data"]["agent"] == "renderer"
        assert third["data"]["status"] == "end"

        await putter

        # Drain remaining events
        async for _ in stream:
            pass

    with caplog.at_level(logging.WARNING, logger="server.generate.service"):
        asyncio.run(run())

    warning_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "renderer" in r.message.lower()
    ]
    assert len(warning_records) == 1, (
        f"expected exactly 1 WARNING about renderer pool wait; got {len(warning_records)}: "
        + ", ".join(r.message for r in warning_records)
    )


# ---------------------------------------------------------------------------
# Test 6 — aclose after acquire/end returns renderer (issue #700 leak window)
# ---------------------------------------------------------------------------


def test_aclose_after_acquire_end_returns_renderer_to_pool(tmp_path: Path) -> None:
    """Calling aclose() after consume of acquire/end (but before pipeline_start)
    must still return the renderer to the pool.

    Without the fix, GeneratorExit at the acquire/end yield exits the generator
    before any finally that puts the renderer back, so the renderer leaks.
    """

    async def run() -> None:
        sentinel = object()
        pool: asyncio.Queue = asyncio.Queue()
        pool.put_nowait(sentinel)
        app_state = SimpleNamespace(renderer_pool=pool)
        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)
        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": _make_happy_spec()}
        )

        # started
        e1 = await stream.__anext__()
        assert e1["event"] == "started"

        # renderer/acquire/start
        e2 = await stream.__anext__()
        assert e2["event"] == "stage"
        assert e2["data"]["agent"] == "renderer"
        assert e2["data"]["status"] == "start"

        # renderer/acquire/end  (renderer is now held; pool is empty)
        e3 = await stream.__anext__()
        assert e3["event"] == "stage"
        assert e3["data"]["agent"] == "renderer"
        assert e3["data"]["status"] == "end"

        # Client disconnects before pipeline_start
        await stream.aclose()

        assert pool.qsize() == 1, (
            "renderer must be returned to pool after aclose() at acquire/end"
        )
        assert pool.get_nowait() is sentinel, "returned item must be the original sentinel"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 7 — plan_all_batch_briefs raises returns renderer (issue #700 leak window)
# ---------------------------------------------------------------------------


class _FakePlanError(RuntimeError):
    """Sentinel exception raised by plan_all_batch_briefs in test 7."""


def _make_failing_plan_spec() -> SubjectSpec:
    """Spec whose plan_all_batch_briefs always raises _FakePlanError."""

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        raise _FakePlanError("plan_all_batch_briefs failed (test 7)")

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(  # pragma: no cover
        rng_params: Any, overrides: dict, **kw: Any
    ) -> _FakeQuestion:
        return _FakeQuestion(id=kw["question_id"])

    def extract_prior_scope(q: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kw: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(cfg: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(cfg: Any, grade: Any) -> dict:  # pragma: no cover
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


def test_plan_all_batch_briefs_raises_returns_renderer_to_pool(tmp_path: Path) -> None:
    """If plan_all_batch_briefs raises, the renderer must still be returned.

    Without the fix, the exception exits the generator before the finally that
    puts the renderer back, so the renderer leaks permanently.
    """

    async def run() -> None:
        sentinel = object()
        pool: asyncio.Queue = asyncio.Queue()
        pool.put_nowait(sentinel)
        app_state = SimpleNamespace(renderer_pool=pool)
        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)
        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": _make_failing_plan_spec()}
        )

        # Drain the stream; expect the _FakePlanError to propagate through __anext__
        try:
            async for _evt in stream:
                pass
        except _FakePlanError:
            pass  # expected

        assert pool.qsize() == 1, (
            "renderer must be returned to pool even when plan_all_batch_briefs raises"
        )
        assert pool.get_nowait() is sentinel, "returned item must be the original sentinel"

    asyncio.run(run())
