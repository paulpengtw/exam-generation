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
        and isinstance(e.get("payload", e.get("data")), dict)
        and e.get("payload", e.get("data", {})).get("event_name") == "pipeline_start"
    ]
    assert pipeline_start_events, "expected at least one pipeline_start event"

    result_events = [e for e in events if e["event"] == "result"]
    assert len(result_events) == 1, f"expected 1 result event; got {len(result_events)}"

    assert pool_size_ok, "pool should hold exactly 1 item after the run"
    assert sentinel_ok, "the returned item must be the same sentinel object"


# ---------------------------------------------------------------------------
# Test 3 — green: aborted run keeps renderer until its worker exits
# ---------------------------------------------------------------------------


def test_aborted_run_does_not_hold_renderer_while_worker_is_blocked(tmp_path: Path) -> None:
    """Per-render lease: a worker blocked in a non-render call never borrows the renderer.

    The pool stays FULL while the worker is stuck inside a blocking do_generate
    call that never calls html_renderer.render().  This is the key improvement over
    option 1 (stream-level hold), where the renderer was held for the entire duration
    of the worker's blocking call (150–230 s in the staging gpt_image scenario).

    Replaces the old ``test_aborted_run_keeps_renderer_until_its_worker_exits``
    test which documented the old (now-removed) stream-level hold behaviour.
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
        # _make_blocking_spec's do_generate blocks but never calls html_renderer.render(),
        # so the RendererLease never borrows from the pool.
        fake_spec = _make_blocking_spec(first_call_started, first_call_release)

        stream = generate_question_stream(
            params, config, app_state, subjects={"fake": fake_spec}
        )

        # Consume until pipeline_start; by then the worker is in the executor.
        async for evt in stream:
            if (
                evt["event"] == "pipeline"
                and isinstance(evt.get("payload", evt.get("data")), dict)
                and evt.get("payload", evt.get("data", {})).get("event_name") == "pipeline_start"
            ):
                break

        # Wait for the worker to actually start inside do_generate.
        started_ok = await asyncio.get_event_loop().run_in_executor(
            None, lambda: first_call_started.wait(15.0)
        )
        assert started_ok, "timed out waiting for worker to enter do_generate"

        # The pool must be FULL while the worker is blocked — the per-render lease
        # means a non-rendering worker never borrows from the pool.
        assert pool.qsize() == 1, (
            "pool should stay full while the blocking worker is not rendering; "
            "with the per-render lease, a non-rendering worker never borrows from the pool"
        )

        # Simulate disconnect.
        aclose_task = asyncio.create_task(stream.aclose())

        # Poll for 0.5 s verifying the pool stays full throughout.
        deadline = asyncio.get_event_loop().time() + 0.5
        all_checks_full = True
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            if pool.qsize() != 1:
                all_checks_full = False
                break

        assert all_checks_full, (
            "pool should stay full while the blocking worker is not rendering"
        )

        # Release the worker; aclose completes without any renderer borrow.
        first_call_release.set()
        await aclose_task

        assert pool.qsize() == 1, "pool must remain full after worker exits"
        assert pool.get_nowait() is sentinel, "sentinel must be the same object"

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
                    and isinstance(evt.get("payload", evt.get("data")), dict)
                    and evt.get("payload", evt.get("data", {})).get("event_name") == "pipeline_start"  # noqa: E501
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
        and isinstance(e.get("payload", e.get("data")), dict)
        and e.get("payload", e.get("data", {})).get("agent") == "planner"
        and e.get("payload", e.get("data", {})).get("stage") == "batch_briefs"
    ]
    assert len(planner_stages) == 2, (
        f"expected 2 planner/batch_briefs stage events (start + end); got {len(planner_stages)}"
    )
    assert planner_stages[0].get("payload", planner_stages[0].get("data", {})).get("status") == "start", (  # noqa: E501
        f"first planner/batch_briefs event should have status 'start'; "
        f"got {planner_stages[0].get('payload', planner_stages[0].get('data', {})).get('status')!r}"
    )
    assert planner_stages[1].get("payload", planner_stages[1].get("data", {})).get("status") == "end", (  # noqa: E501
        f"second planner/batch_briefs event should have status 'end'; "
        f"got {planner_stages[1].get('payload', planner_stages[1].get('data', {})).get('status')!r}"
    )

    # Both stage events must appear before pipeline_start
    pipeline_start_indices = [
        i
        for i, e in enumerate(events)
        if e["event"] == "pipeline"
        and isinstance(e.get("payload", e.get("data")), dict)
        and e.get("payload", e.get("data", {})).get("event_name") == "pipeline_start"
    ]
    assert pipeline_start_indices, "expected at least one pipeline_start event"
    first_pipeline_start_idx = pipeline_start_indices[0]

    for stage_evt in planner_stages:
        stage_idx = events.index(stage_evt)
        assert stage_idx < first_pipeline_start_idx, (
            f"planner/batch_briefs stage event (status={stage_evt.get('payload', stage_evt.get('data', {})).get('status')!r}) "  # noqa: E501
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
    """When a per-render lease wait exceeds the threshold, exactly one WARNING is logged.

    The warning now lives in server.generate.renderer_lease (per-render lease design),
    but RENDERER_POOL_WAIT_WARN_THRESHOLD_S stays in server.generate.service and is
    read lazily by RendererLease.render() at call time — monkeypatching the service
    constant is sufficient.

    A spec whose do_generate calls html_renderer.render() is used so the lease
    actually waits for a pool item.
    """
    import server.generate.service as svc  # noqa: PLC0415

    threshold = 0.05  # seconds — monkeypatched well below the default
    monkeypatch.setattr(svc, "RENDERER_POOL_WAIT_WARN_THRESHOLD_S", threshold)

    render_calls: list[str] = []

    def _make_rendering_spec() -> SubjectSpec:
        """Spec whose do_generate calls html_renderer.render() once."""

        def coerce_overrides(params: Any, app_state: Any) -> dict:
            return {}

        def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
            return []

        def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
            return _FakeParams()

        def do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
            hr = kw.get("html_renderer")
            if hr is not None:
                result = hr.render("<p>test</p>", tmp_path / "out.png")
                render_calls.append(str(result))
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

    class _FakeRenderer:
        """Fake renderer whose render() records calls and returns a sentinel path."""

        def render(self, html: str, output_path: Any, width: int = 800) -> str:
            return str(output_path)

    async def run() -> None:
        pool: asyncio.Queue = asyncio.Queue()  # starts empty
        app_state = SimpleNamespace(renderer_pool=pool)
        config = ServerConfig(
            api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
        )
        params = GenerateParams(subject="fake", count=1, skip_verify=True)

        # Schedule putting a renderer in the pool after the threshold fires.
        fake_renderer = _FakeRenderer()

        async def put_after_threshold() -> None:
            await asyncio.sleep(threshold * 4)
            await pool.put(fake_renderer)

        putter = asyncio.create_task(put_after_threshold())

        async for _ in generate_question_stream(
            params, config, app_state,
            subjects={"fake": _make_rendering_spec()},
        ):
            pass

        await putter

    with caplog.at_level(logging.WARNING, logger="server.generate.renderer_lease"):
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
    # Confirm the render actually executed (lease acquired and returned the renderer).
    assert len(render_calls) == 1, (
        f"expected exactly 1 render call after acquiring the lease; got {render_calls}"
    )


# ---------------------------------------------------------------------------
# Test 6 — aclose after acquire/end returns renderer (issue #700 leak window)
# ---------------------------------------------------------------------------


def test_aclose_early_does_not_lose_renderer(tmp_path: Path) -> None:
    """Calling aclose() at any point before pipeline_start must not lose a renderer.

    With the per-render lease design, there is no stream-level renderer hold, so
    calling aclose() immediately after ``started`` or after any planning stage event
    cannot leak the renderer — the pool always stays intact.

    Replaces ``test_aclose_after_acquire_end_returns_renderer_to_pool`` which
    assumed the old stream-level acquire/end stage event (removed in option 2).
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

        # started — pool is still full (no stream-level hold)
        e1 = await stream.__anext__()
        assert e1["event"] == "started"
        assert pool.qsize() == 1, "pool must be full right after started (no stream-level hold)"

        # Next event is planner/batch_briefs/start (not renderer/acquire/start)
        e2 = await stream.__anext__()
        assert e2["event"] == "stage"
        assert e2.get("payload", e2.get("data", {})).get("agent") == "planner", (
            f"first stage event after started must be planner; got {e2.get('payload', e2.get('data', {})).get('agent')!r}"  # noqa: E501
        )
        assert pool.qsize() == 1, "pool must stay full before planning (no stream-level hold)"

        # Disconnect before pipeline_start — pool must stay intact
        await stream.aclose()

        assert pool.qsize() == 1, (
            "pool must remain full after aclose() early — with per-render lease, "
            "the stream never holds a renderer outside of an actual render call"
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
