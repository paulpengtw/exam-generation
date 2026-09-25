"""Tests for the per-render renderer lease (issue #700 option 2).

Slices:
  1. Aborted run whose worker is blocked in a non-render call does not hold a
     renderer: pool stays full while the worker is still blocked.
  2. Worker HTML render borrows a renderer for exactly the render and returns it:
     pool is one short during the fake render and full afterwards.
  3. Two concurrent streams whose fake workers never render both reach
     pipeline_start promptly (pool of 1 does not cap concurrent generations).
  4. Empty pool: worker render emits renderer/acquire/start within 1 s, emits
     renderer/acquire/end once a renderer is added, renders; a lowered threshold
     produces exactly one WARNING.
  5. Empty pool, cancel during wait: worker stops waiting, skips render, exits;
     putting a renderer back afterwards leaves it there (no lost renderer).
  6. Existing tests that assumed stream-level hold are updated in
     test_generate_started_stall.py (see that module's revision notes).
     This module tests only at the seam described by the brief:
     generate_question_stream driven with injected fake subjects and an
     asyncio.Queue pool holding sentinel/fake renderer objects.
"""
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
# Shared fakes
# ---------------------------------------------------------------------------


class _FakeQuestion(BaseModel):
    id: str
    圖片: str | None = None


class _FakeParams:
    """Opaque stand-in for sampled params."""


def _base_spec_kwargs() -> dict:
    """Return the boilerplate SubjectSpec fields every factory needs."""

    def plan_core_questions(client: Any, topic: str, **kw: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(cfg: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(cfg: Any, grade: Any) -> dict:  # pragma: no cover
        return {}

    return {
        "key": "fake",
        "question_id_prefix": "fake_",
        "exam_question_cls": _FakeQuestion,
        "patch_metadata": None,
        "plan_core_questions": plan_core_questions,
        "load_planner_stage": load_planner_stage,
        "build_schemas": build_schemas,
    }


def _make_happy_spec() -> SubjectSpec:
    """Non-rendering spec: do_generate returns immediately without touching html_renderer."""

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

    return SubjectSpec(
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        params_from_resolved_payload=params_from_resolved_payload,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        **_base_spec_kwargs(),
    )


def _make_blocking_spec(
    started: threading.Event,
    release: threading.Event,
) -> SubjectSpec:
    """Spec whose do_generate blocks until release is set; never calls html_renderer."""

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        return []

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
        started.set()
        release.wait(timeout=30)
        return _FakeQuestion(id=kw["question_id"])

    def extract_prior_scope(q: Any) -> None:
        return None

    return SubjectSpec(
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        params_from_resolved_payload=params_from_resolved_payload,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        **_base_spec_kwargs(),
    )


class _FakeRenderer:
    """Fake PlaywrightRenderer that records render calls and returns a fixed path."""

    def __init__(self) -> None:
        self.render_calls: list[dict] = []

    def render(self, html: str, output_path: Any, width: int = 800) -> str:
        self.render_calls.append({"html": html, "output_path": str(output_path), "width": width})
        return str(output_path)


def _make_rendering_spec(
    fake_renderer: _FakeRenderer,
    pool: asyncio.Queue,
    render_started: threading.Event | None = None,
    render_release: threading.Event | None = None,
) -> SubjectSpec:
    """Spec whose do_generate calls html_renderer.render() once.

    If render_started / render_release are provided, the fake renderer's render()
    method sets render_started before calling the real fake_renderer, then waits
    for render_release after — allowing the test to inspect pool state mid-render.
    """

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        return []

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
        hr = kw.get("html_renderer")
        if hr is not None:
            if render_started is not None:
                # Signal test that render is starting; wait for release.
                class _InstrumentedLease:
                    def render(self, html: str, op: Any, width: int = 800) -> str:
                        render_started.set()
                        if render_release is not None:
                            render_release.wait(timeout=30)
                        return hr.render(html, op, width)

                _InstrumentedLease().render("<p>test</p>", Path("/tmp/out.png"))
            else:
                hr.render("<p>test</p>", Path("/tmp/out.png"))
        return _FakeQuestion(id=kw["question_id"])

    def extract_prior_scope(q: Any) -> None:
        return None

    return SubjectSpec(
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        params_from_resolved_payload=params_from_resolved_payload,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        **_base_spec_kwargs(),
    )


def _config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(
        api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
    )


# ---------------------------------------------------------------------------
# Slice 1 — aborted run whose worker is blocked does not hold the renderer
# ---------------------------------------------------------------------------


def test_slice1_aborted_run_does_not_hold_renderer(tmp_path: Path) -> None:
    """Pool stays FULL while a blocking non-rendering worker is running.

    Contrasts with the old option-1 behaviour where the pool was emptied for
    the entire lifetime of the worker thread.
    """
    started = threading.Event()
    release = threading.Event()

    async def run() -> None:
        sentinel = object()
        pool: asyncio.Queue = asyncio.Queue()
        pool.put_nowait(sentinel)
        app_state = SimpleNamespace(renderer_pool=pool)
        params = GenerateParams(subject="fake", count=1, skip_verify=True)
        spec = _make_blocking_spec(started, release)

        stream = generate_question_stream(
            params, _config(tmp_path), app_state, subjects={"fake": spec}
        )

        # Drain until pipeline_start.
        async for evt in stream:
            if (
                evt["event"] == "pipeline"
                and isinstance(evt.get("payload"), dict)
                and evt["payload"].get("event_name") == "pipeline_start"
            ):
                break

        # Wait for worker to enter do_generate.
        worker_in = await asyncio.get_event_loop().run_in_executor(
            None, lambda: started.wait(15.0)
        )
        assert worker_in, "timeout: worker never entered do_generate"

        # KEY ASSERTION (slice 1): pool stays full — worker never borrows.
        assert pool.qsize() == 1, (
            "pool must be full while blocking worker is not rendering"
        )

        # Disconnect; verify pool stays full throughout the aclose() wait.
        aclose_task = asyncio.create_task(stream.aclose())

        deadline = asyncio.get_event_loop().time() + 0.5
        all_full = True
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            if pool.qsize() != 1:
                all_full = False
                break

        assert all_full, "pool should stay full while non-rendering worker is blocked"

        release.set()
        await aclose_task

        assert pool.qsize() == 1, "pool must remain full after worker exits"
        assert pool.get_nowait() is sentinel

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Slice 2 — render borrows for exactly one render, returns after
# ---------------------------------------------------------------------------


def test_slice2_render_borrows_renderer_only_during_render(tmp_path: Path) -> None:
    """Pool is one short during the render and full before and after.

    Verifies that the RendererLease properly acquires and releases the renderer
    around exactly one render() call.

    The fake renderer's render() method sets render_started and then waits for
    render_release — it executes INSIDE the RendererLease's borrow window, so the
    pool is guaranteed empty when render_started is set.
    """
    render_started = threading.Event()
    render_release = threading.Event()

    pool_size_during_render: list[int] = []
    render_calls: list[str] = []

    async def run() -> None:
        # Blocking fake renderer: sets render_started inside the borrow window.
        class _BlockingRenderer:
            def render(self, html: str, output_path: Any, width: int = 800) -> str:
                render_started.set()
                render_release.wait(timeout=30)
                render_calls.append(str(output_path))
                return str(output_path)

        blocking_renderer = _BlockingRenderer()

        pool: asyncio.Queue = asyncio.Queue()
        pool.put_nowait(blocking_renderer)
        app_state = SimpleNamespace(renderer_pool=pool)
        params = GenerateParams(subject="fake", count=1, skip_verify=True)

        # Spec that calls html_renderer.render() once (via the RendererLease).
        def _do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
            hr = kw.get("html_renderer")
            if hr is not None:
                hr.render("<p>test</p>", Path("/tmp/out.png"))
            return _FakeQuestion(id=kw["question_id"])

        def _make_probe_spec() -> SubjectSpec:
            def coerce_overrides(p: Any, s: Any) -> dict:
                return {}

            def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
                return []

            def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
                return _FakeParams()

            def extract_prior_scope(q: Any) -> None:
                return None

            return SubjectSpec(
                coerce_overrides=coerce_overrides,
                plan_all_batch_briefs=plan_all_batch_briefs,
                params_from_resolved_payload=params_from_resolved_payload,
                do_generate=_do_generate,
                extract_prior_scope=extract_prior_scope,
                **_base_spec_kwargs(),
            )

        stream = generate_question_stream(
            params, _config(tmp_path), app_state, subjects={"fake": _make_probe_spec()}
        )

        # Launch drain in background task.
        drain_task = asyncio.create_task(_drain(stream))

        # Wait for render to start: blocking_renderer.render() is executing,
        # which means RendererLease has already borrowed the renderer from the pool.
        render_in = await asyncio.get_event_loop().run_in_executor(
            None, lambda: render_started.wait(15.0)
        )
        assert render_in, "timeout: render never started inside blocking renderer"

        # KEY ASSERTION (slice 2a): pool is empty because RendererLease borrowed it.
        pool_size_during_render.append(pool.qsize())

        # Release the blocking render.
        render_release.set()
        await drain_task

        # KEY ASSERTION (slice 2b): pool is full after the render.
        assert pool.qsize() == 1, "pool must be full after render completes"
        returned = pool.get_nowait()
        assert returned is blocking_renderer, "returned item must be the blocking renderer"

    asyncio.run(run())

    assert pool_size_during_render == [0], (
        f"pool must be 0 during render (RendererLease holds it); got {pool_size_during_render}"
    )
    assert len(render_calls) == 1, (
        f"expected 1 render call; got {render_calls}"
    )


async def _drain(stream: Any) -> None:
    """Drain an async generator to completion."""
    async for _ in stream:
        pass


# ---------------------------------------------------------------------------
# Slice 3 — two concurrent non-rendering streams both reach pipeline_start promptly
# ---------------------------------------------------------------------------


def test_slice3_two_non_rendering_streams_start_promptly(tmp_path: Path) -> None:
    """A pool of 1 renderer does not cap concurrent non-rendering generations.

    Two streams whose workers never call render() both reach pipeline_start
    within a tight deadline (no global serialisation through the pool).
    """
    started_1 = threading.Event()
    release_1 = threading.Event()
    started_2 = threading.Event()
    release_2 = threading.Event()

    async def run() -> None:
        sentinel = object()
        pool: asyncio.Queue = asyncio.Queue()
        pool.put_nowait(sentinel)
        app_state = SimpleNamespace(renderer_pool=pool)
        params = GenerateParams(subject="fake", count=1, skip_verify=True)

        t_pipeline_start: list[float] = []

        async def run_one(started_ev: threading.Event, release_ev: threading.Event) -> None:
            spec = _make_blocking_spec(started_ev, release_ev)
            t0 = time.monotonic()
            async for evt in generate_question_stream(
                params, _config(tmp_path), app_state, subjects={"fake": spec}
            ):
                if (
                    evt["event"] == "pipeline"
                    and isinstance(evt.get("payload"), dict)
                    and evt["payload"].get("event_name") == "pipeline_start"
                ):
                    t_pipeline_start.append(time.monotonic() - t0)
                    break
            # Release so the stream can finish cleanly.
            release_ev.set()
            async for _ in generate_question_stream(
                params, _config(tmp_path), app_state, subjects={"fake": spec}
            ):
                pass

        # Run both streams concurrently.
        task1 = asyncio.create_task(run_one(started_1, release_1))
        task2 = asyncio.create_task(run_one(started_2, release_2))
        await asyncio.gather(task1, task2)

        assert len(t_pipeline_start) == 2, (
            f"expected both streams to reach pipeline_start; only {len(t_pipeline_start)} did"
        )
        for i, t in enumerate(t_pipeline_start):
            assert t < 5.0, (
                f"stream {i+1} took {t:.2f} s to reach pipeline_start; "
                "expected < 5 s (pool of 1 should not gate non-rendering streams)"
            )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Slice 4 — empty pool: worker render emits acquire events, logs WARNING
# ---------------------------------------------------------------------------


def test_slice4_empty_pool_emits_acquire_events_and_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With an empty pool, a worker render emits acquire start within 1 s, then end.

    After a renderer is put into the pool the lease acquires it, emits end, and
    the render executes.  With a monkeypatched threshold, exactly one WARNING is
    logged.
    """
    import server.generate.service as svc  # noqa: PLC0415

    threshold = 0.05
    monkeypatch.setattr(svc, "RENDERER_POOL_WAIT_WARN_THRESHOLD_S", threshold)

    fake_renderer = _FakeRenderer()
    acquire_start_times: list[float] = []
    acquire_end_times: list[float] = []

    async def run() -> None:
        pool: asyncio.Queue = asyncio.Queue()  # empty
        app_state = SimpleNamespace(renderer_pool=pool)
        params = GenerateParams(subject="fake", count=1, skip_verify=True)

        spec = _make_rendering_spec(fake_renderer, pool)

        # Schedule putting the renderer after the threshold fires.
        async def put_after_threshold() -> None:
            await asyncio.sleep(threshold * 4)
            await pool.put(fake_renderer)

        putter = asyncio.create_task(put_after_threshold())
        t0 = time.monotonic()

        async for evt in generate_question_stream(
            params, _config(tmp_path), app_state, subjects={"fake": spec}
        ):
            if (
                evt["event"] == "stage"
                and isinstance(evt.get("payload"), dict)
                and evt["payload"].get("agent") == "renderer"
            ):
                if evt["payload"]["status"] == "start":
                    acquire_start_times.append(time.monotonic() - t0)
                elif evt["payload"]["status"] == "end":
                    acquire_end_times.append(time.monotonic() - t0)

        await putter

    with caplog.at_level(logging.WARNING, logger="server.generate.renderer_lease"):
        asyncio.run(run())

    # acquire/start must arrive within 1 s of stream start
    assert len(acquire_start_times) == 1, (
        f"expected exactly 1 renderer/acquire/start event; got {len(acquire_start_times)}"
    )
    assert acquire_start_times[0] < 1.0, (
        f"renderer/acquire/start took {acquire_start_times[0]:.3f} s; expected < 1 s"
    )

    # acquire/end must arrive (after start)
    assert len(acquire_end_times) == 1, (
        f"expected exactly 1 renderer/acquire/end event; got {len(acquire_end_times)}"
    )
    assert acquire_end_times[0] > acquire_start_times[0], (
        "renderer/acquire/end must come after acquire/start"
    )

    # Exactly one WARNING logged.
    warning_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "renderer" in r.message.lower()
    ]
    assert len(warning_records) == 1, (
        f"expected 1 WARNING about renderer pool wait; got {len(warning_records)}: "
        + ", ".join(r.message for r in warning_records)
    )

    # Render executed after acquiring.
    assert len(fake_renderer.render_calls) == 1, (
        f"expected 1 render call; got {len(fake_renderer.render_calls)}"
    )


# ---------------------------------------------------------------------------
# Slice 5 — cancel during pool wait: render skipped, no renderer lost
# ---------------------------------------------------------------------------


def test_slice5_cancel_during_pool_wait_skips_render_no_lost_renderer(
    tmp_path: Path,
) -> None:
    """Closing the stream while worker waits for a lease stops the wait.

    Afterwards, putting a renderer into the pool leaves it there (no leaked
    consumer that silently drains the pool).
    """
    fake_renderer = _FakeRenderer()
    render_attempted = threading.Event()

    async def run() -> None:
        pool: asyncio.Queue = asyncio.Queue()  # empty
        app_state = SimpleNamespace(renderer_pool=pool)
        params = GenerateParams(subject="fake", count=1, skip_verify=True)

        worker_started = threading.Event()

        def _do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
            hr = kw.get("html_renderer")
            worker_started.set()
            if hr is not None:
                render_attempted.set()
                # Try to render — this will block on the empty pool.
                # cancel_event will be set by stream.aclose(), ending the wait.
                hr.render("<p>cancel test</p>", Path("/tmp/cancel_test.png"))
            return _FakeQuestion(id=kw["question_id"])

        def _make_cancel_spec() -> SubjectSpec:
            def coerce_overrides(p: Any, s: Any) -> dict:
                return {}

            def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
                return []

            def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
                return _FakeParams()

            def extract_prior_scope(q: Any) -> None:
                return None

            return SubjectSpec(
                coerce_overrides=coerce_overrides,
                plan_all_batch_briefs=plan_all_batch_briefs,
                params_from_resolved_payload=params_from_resolved_payload,
                do_generate=_do_generate,
                extract_prior_scope=extract_prior_scope,
                **_base_spec_kwargs(),
            )

        stream = generate_question_stream(
            params, _config(tmp_path), app_state,
            subjects={"fake": _make_cancel_spec()},
        )

        # Drive until pipeline_start so workers are submitted.
        async for evt in stream:
            if (
                evt["event"] == "pipeline"
                and isinstance(evt.get("payload"), dict)
                and evt["payload"].get("event_name") == "pipeline_start"
            ):
                break

        # Wait for worker to start.
        w_ok = await asyncio.get_event_loop().run_in_executor(
            None, lambda: worker_started.wait(15.0)
        )
        assert w_ok, "timeout: worker never started"

        # Wait briefly for the worker to start waiting on the pool.
        # The pool is empty and cancel_event is not yet set, so the worker
        # is polling in RendererLease.render().
        await asyncio.sleep(0.2)

        # Close the stream: sets cancel_event, which stops the lease wait.
        await stream.aclose()

        # Give the worker thread time to observe cancel_event and exit.
        await asyncio.sleep(0.2)

        # Put a renderer into the now-empty pool.
        # N is the number of renderers that should exist in the pool: exactly the one
        # we just put back.  A leaked _acquire future would silently consume it.
        N = 1
        await pool.put(fake_renderer)

        # Wait briefly and check the pool still has the renderer.
        await asyncio.sleep(0.2)

        # KEY ASSERTION (slice 5): pool.qsize() == N (== 1) — no leak.
        assert pool.qsize() == N, (
            f"pool must hold {N} renderer(s) after cancel + put; "
            "a leaked wait future would silently consume the item and leave pool.qsize() == 0"
        )
        remaining = pool.get_nowait()
        assert remaining is fake_renderer, (
            f"item in pool must be fake_renderer; got {remaining!r}"
        )

        # Render was not called (lease wait was interrupted by cancel_event).
        assert len(fake_renderer.render_calls) == 0, (
            f"render must not be called after cancel; got {fake_renderer.render_calls}"
        )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Slice 6 — Race 1: busy event loop at fast-path does not leak a renderer
# ---------------------------------------------------------------------------


def test_slice6_busy_loop_does_not_lose_renderer(tmp_path: Path) -> None:
    """Event loop blocked >1 s at render start must not permanently lose a renderer.

    This is a deterministic test for Race 1 in the original buggy design::

        asyncio.run_coroutine_threadsafe(_get_nowait(pool), loop).result(timeout=1.0)

    If the loop is unresponsive for longer than 1 s, result() raises TimeoutError and
    the caller sets renderer=None -- but _get_nowait is still queued on the loop and
    runs later, silently consuming a renderer that nobody returns.

    Design:
      - Pool holds N_RENDERERS (2) renderers so the slow path can still acquire one
        even if the fast path already leaked a renderer, allowing the stream to finish.
      - The worker signals pre_render and sleeps 0.1 s before calling render(),
        giving the test time to schedule a 1.5 s blocking sleep on the event loop.
      - The blocking sleep fires before the worker's render() call, making the loop
        unresponsive for 1.5 s -- longer than any fast-path timeout.
      - After everything settles, pool.qsize() must equal N_RENDERERS.
        The buggy design leaks one renderer (qsize == 1); the fixed design does not.
    """
    N_RENDERERS = 2
    pre_render = threading.Event()
    render_count: list[int] = [0]

    async def run() -> None:
        class _CountingRenderer:
            def render(self, html: str, output_path: Any, width: int = 800) -> str:
                render_count[0] += 1
                return str(output_path)

        pool: asyncio.Queue = asyncio.Queue()
        for _ in range(N_RENDERERS):
            pool.put_nowait(_CountingRenderer())
        app_state = SimpleNamespace(renderer_pool=pool)
        params = GenerateParams(subject="fake", count=1, skip_verify=True)

        def do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
            hr = kw.get("html_renderer")
            if hr is not None:
                pre_render.set()
                time.sleep(0.1)  # give test time to schedule loop block before render
                hr.render("<p>race1</p>", Path("/tmp/race1.png"))
            return _FakeQuestion(id=kw["question_id"])

        def _make_spec() -> SubjectSpec:
            def coerce_overrides(p: Any, s: Any) -> dict:
                return {}

            def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
                return []

            def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
                return _FakeParams()

            def extract_prior_scope(q: Any) -> None:
                return None

            return SubjectSpec(
                coerce_overrides=coerce_overrides,
                plan_all_batch_briefs=plan_all_batch_briefs,
                params_from_resolved_payload=params_from_resolved_payload,
                do_generate=do_generate,
                extract_prior_scope=extract_prior_scope,
                **_base_spec_kwargs(),
            )

        loop = asyncio.get_running_loop()
        stream = generate_question_stream(
            params, _config(tmp_path), app_state, subjects={"fake": _make_spec()}
        )

        # Drive until pipeline_start so the worker is submitted.
        async for evt in stream:
            if (
                evt["event"] == "pipeline"
                and isinstance(evt.get("payload"), dict)
                and evt["payload"].get("event_name") == "pipeline_start"
            ):
                break

        # Wait for the worker to signal it is about to call render().
        pre_ok = await asyncio.get_event_loop().run_in_executor(
            None, lambda: pre_render.wait(15.0)
        )
        assert pre_ok, "timeout: worker never signalled pre_render"

        # Block the event loop for 1.5 s -- longer than the 1.0 s fast-path timeout.
        # call_soon places the blocking callback before asyncio.sleep(0)'s own resume
        # in the ready queue (FIFO), so time.sleep runs first and holds the loop.
        loop.call_soon(lambda: time.sleep(1.5))
        await asyncio.sleep(0)  # yield: time.sleep(1.5) fires, loop is blocked 1.5 s

        # Loop unblocked.  Any leaked _get_nowait coroutine has already run.
        # Drain remaining stream events to completion.
        async for _ in stream:
            pass

        # Give any lingering loop callbacks one final iteration to settle.
        await asyncio.sleep(0.1)

        # KEY ASSERTION: all N_RENDERERS must be back in the pool.
        # Buggy code leaks one (qsize == N_RENDERERS - 1); fixed code does not.
        assert pool.qsize() == N_RENDERERS, (
            f"pool must hold all {N_RENDERERS} renderers after render completes; "
            f"got {pool.qsize()} -- Race 1 leaks one, leaving pool at {N_RENDERERS - 1}"
        )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Slice 7 — publisher kwarg: stage events are v2 envelopes, batch-scoped
# ---------------------------------------------------------------------------


def test_slice7_renderer_lease_stage_events_are_v2_envelopes(tmp_path: Path) -> None:
    """RendererLease with a publisher emits v2 envelopes for acquire events.

    Constructs a RendererLease directly with a GenerationPublisher and an empty
    pool so the acquire wait fires.  Asserts the queued items are v2 envelopes
    {event, context, payload} with no question_id (batch scope) and no legacy
    'data' key.
    """

    class _TrivialRenderer:
        def render(self, html: str, output_path: Any, width: int = 800) -> str:
            return str(output_path)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        run_id = "test-run-v2-7"
        from server.generate.publisher import GenerationPublisher  # noqa: PLC0415
        from server.generate.renderer_lease import RendererLease  # noqa: PLC0415

        publisher = GenerationPublisher(run_id=run_id, loop=loop, queue=queue)
        pool: asyncio.Queue = asyncio.Queue()  # empty — forces acquire/start
        cancel_event = threading.Event()

        lease = RendererLease(pool, loop, cancel_event, queue, publisher=publisher)
        real_renderer = _TrivialRenderer()

        # Put the renderer into the pool after a short delay.
        async def put_renderer() -> None:
            await asyncio.sleep(0.15)
            await pool.put(real_renderer)

        putter = asyncio.create_task(put_renderer())

        # lease.render() is blocking; run it in a thread executor.
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: lease.render("<p>v2test</p>", Path("/tmp/v2test.png")),
        )
        await putter

        # Collect items from queue.
        items: list[dict] = []
        while not queue.empty():
            items.append(queue.get_nowait())

        # Filter to stage events from the renderer acquire.
        stage_items = [
            it for it in items
            if it.get("event") == "stage"
            and isinstance(it.get("payload"), dict)
            and it["payload"].get("agent") == "renderer"
        ]

        assert len(stage_items) >= 2, (
            f"expected at least 2 stage events (start + end); "
            f"got {len(stage_items)}: {[it.get('payload') for it in stage_items]}"
        )

        for item in stage_items:
            # Must be v2 envelope shape.
            assert "event" in item, f"missing 'event' key: {item}"
            assert "context" in item, f"missing 'context' key (v2 required): {item}"
            assert "payload" in item, f"missing 'payload' key (v2 required): {item}"
            assert "data" not in item, (
                f"legacy 'data' key must NOT be present in v2 envelope: {item}"
            )

            ctx = item["context"]
            assert ctx["run_id"] == run_id, (
                f"context.run_id must be {run_id!r}; got {ctx['run_id']!r}"
            )
            assert isinstance(ctx["event_seq"], int) and ctx["event_seq"] >= 1, (
                f"context.event_seq must be a positive int; got {ctx['event_seq']!r}"
            )
            assert "question_id" not in ctx, (
                "stage events are batch-scoped; question_id must NOT appear "
                f"in context: {ctx}"
            )

            pl = item["payload"]
            assert pl.get("type") == "stage", f"payload.type must be 'stage': {pl}"
            assert pl.get("agent") == "renderer", f"payload.agent must be 'renderer': {pl}"
            assert pl.get("stage") == "acquire", f"payload.stage must be 'acquire': {pl}"
            assert pl.get("status") in ("start", "end"), (
                f"payload.status must be 'start' or 'end': {pl}"
            )
            assert isinstance(pl.get("ts"), float), (
                f"payload.ts must be a float timestamp: {pl}"
            )

        # Verify monotonic event_seq.
        seqs = [it["context"]["event_seq"] for it in stage_items]
        assert seqs == sorted(seqs), (
            f"event_seq must be monotonically increasing; got {seqs}"
        )

    asyncio.run(run())
