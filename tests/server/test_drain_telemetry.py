"""Slice 1: DrainTelemetry counter tests (task 8.2 core).

Uses fake SubjectSpecs following test_generate_cancel.py patterns and
the _run_stream style from test_generate_service_coverage.py.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras")

from pydantic import BaseModel

from server.config import ServerConfig
from server.generate.drain import DrainTelemetry
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SubjectSpec

# ---------------------------------------------------------------------------
# Shared fake question model
# ---------------------------------------------------------------------------


class _FQ(BaseModel):
    id: str
    圖片: str | None = None


class _FP:
    pass


def _make_spec(do_generate_fn) -> SubjectSpec:
    def coerce_overrides(p, a):
        return {}

    def plan_all_batch_briefs(*a, **kw):
        return []

    def params_from_resolved_payload(payload, overrides):
        return _FP()

    def extract_prior_scope(q):
        return None

    def plan_core_questions(client, topic, **kw):  # pragma: no cover
        return []

    def load_planner_stage(cfg, grade):  # pragma: no cover
        return "第四學習階段"

    def build_schemas(cfg, grade):  # pragma: no cover
        return {}

    return SubjectSpec(
        key="fake",
        question_id_prefix="fake_",
        exam_question_cls=_FQ,
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        params_from_resolved_payload=params_from_resolved_payload,
        do_generate=do_generate_fn,
        extract_prior_scope=extract_prior_scope,
        patch_metadata=None,
        plan_core_questions=plan_core_questions,
        load_planner_stage=load_planner_stage,
        build_schemas=build_schemas,
    )


def _fast_spec() -> SubjectSpec:
    def do_generate(rng_params, overrides, **kw):
        return _FQ(id=kw["question_id"])

    return _make_spec(do_generate)


def _config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )


def _params(count: int = 1) -> GenerateParams:
    return GenerateParams(subject="fake", count=count, skip_verify=True)


def _app_state(drain: DrainTelemetry) -> SimpleNamespace:
    ns = SimpleNamespace(renderer_pool=None)
    ns.drain_telemetry = drain
    return ns


# ---------------------------------------------------------------------------
# (a) Idle snapshot is quiescent with identity fields
# ---------------------------------------------------------------------------


def test_idle_snapshot_is_quiescent():
    drain = DrainTelemetry()
    snap = drain.snapshot()

    # Identity fields present
    assert isinstance(snap["instance_id"], str)
    assert len(snap["instance_id"]) > 0
    assert isinstance(snap["hostname"], str)
    assert isinstance(snap["pid"], int)
    assert isinstance(snap["started_at"], str)
    assert "supported_stream_versions" in snap
    assert 1 in snap["supported_stream_versions"]
    assert "captured_at" in snap

    # All counters zero
    assert snap["active_runs"] == 0
    assert snap["active_workers"] == 0
    assert snap["open_streams"] == 0
    assert snap["pending_deliveries"] == 0
    assert snap["pending_persistence"] == 0
    assert snap["renderer_leases_held"] == 0

    assert snap["quiescent"] is True

    # No question/prompt/user content in values
    for key in snap:
        if key in ("instance_id", "hostname", "started_at", "captured_at", "app_version"):
            continue


# ---------------------------------------------------------------------------
# (b) Workers blocked → active_runs/active_workers nonzero; after release → zero
# ---------------------------------------------------------------------------


def test_blocked_workers_show_nonzero_then_quiescent(tmp_path):
    # Both workers signal they've entered, then wait for release
    workers_entered = threading.Event()
    workers_released = threading.Event()
    worker_entry_count = [0]
    entry_lock = threading.Lock()

    drain = DrainTelemetry()

    def do_generate(rng_params, overrides, **kw):
        with entry_lock:
            worker_entry_count[0] += 1
            if worker_entry_count[0] >= 2:
                workers_entered.set()
        workers_released.wait(timeout=10)
        return _FQ(id=kw["question_id"])

    spec = _make_spec(do_generate)
    app_state = _app_state(drain)

    stream_done = threading.Event()

    async def run_stream():
        async for _ in generate_question_stream(
            _params(count=2), _config(tmp_path), app_state,
            subjects={"fake": spec},
        ):
            pass
        stream_done.set()

    def run_in_thread():
        asyncio.run(run_stream())

    t = threading.Thread(target=run_in_thread, daemon=True)
    t.start()

    # Wait until both workers are blocking
    assert workers_entered.wait(timeout=10), "workers did not enter in time"

    # Now check: active_runs should be 1, active_workers 2
    snap = drain.snapshot()
    assert snap["active_runs"] >= 1, f"expected active_runs>=1, got {snap}"
    assert snap["active_workers"] == 2, f"expected active_workers=2, got {snap}"
    assert snap["quiescent"] is False

    # Release workers
    workers_released.set()

    # Wait for stream to finish
    assert stream_done.wait(timeout=10), "stream did not finish"
    t.join(timeout=5)

    # Wait for all finally blocks to complete
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snap = drain.snapshot()
        if snap["quiescent"]:
            break
        time.sleep(0.05)

    snap = drain.snapshot()
    assert snap["active_runs"] == 0, f"active_runs still nonzero: {snap}"
    assert snap["active_workers"] == 0, f"active_workers still nonzero: {snap}"
    assert snap["quiescent"] is True


# ---------------------------------------------------------------------------
# (c) A worker that raises still decrements active_workers
# ---------------------------------------------------------------------------


def test_raising_worker_still_decrements(tmp_path):
    drain = DrainTelemetry()

    def do_generate(rng_params, overrides, **kw):
        raise RuntimeError("simulated worker failure")

    spec = _make_spec(do_generate)
    app_state = _app_state(drain)

    async def run_stream():
        async for _ in generate_question_stream(
            _params(count=1), _config(tmp_path), app_state,
            subjects={"fake": spec},
        ):
            pass

    asyncio.run(run_stream())

    snap = drain.snapshot()
    assert snap["active_workers"] == 0, f"raising worker left active_workers nonzero: {snap}"
    assert snap["active_runs"] == 0


# ---------------------------------------------------------------------------
# (d) A recorder flush that raises in the run's finally still releases active_runs
# ---------------------------------------------------------------------------


def test_recorder_flush_raises_still_releases_active_runs(tmp_path):
    drain = DrainTelemetry()
    spec = _fast_spec()

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

    app_state = _app_state(drain)
    gen_log_id = uuid.uuid4()

    async def run():
        async for _ in generate_question_stream(
            _params(count=1), _config(tmp_path), app_state,
            subjects={"fake": spec},
            generation_log_id=gen_log_id,
            session_factory=bad_session_factory,
        ):
            pass

    asyncio.run(run())

    snap = drain.snapshot()
    assert snap["active_runs"] == 0, f"active_runs leaked after bad flush: {snap}"


# ---------------------------------------------------------------------------
# (e) renderer_leases_held increments while rendering blocks, decrements after
# ---------------------------------------------------------------------------


def test_renderer_lease_held_then_released():
    drain = DrainTelemetry()
    assert drain.snapshot()["renderer_leases_held"] == 0

    with drain.ctx_renderer_lease():
        assert drain.snapshot()["renderer_leases_held"] == 1
        assert drain.snapshot()["quiescent"] is False

    assert drain.snapshot()["renderer_leases_held"] == 0


def test_renderer_lease_exception_still_decrements():
    drain = DrainTelemetry()
    try:
        with drain.ctx_renderer_lease():
            raise RuntimeError("render failed")
    except RuntimeError:
        pass
    assert drain.snapshot()["renderer_leases_held"] == 0


# ---------------------------------------------------------------------------
# (f) pending_deliveries reflects events sitting in the queue
# ---------------------------------------------------------------------------


def test_pending_deliveries_reflects_queue_contents():
    drain = DrainTelemetry()
    q: asyncio.Queue = asyncio.Queue()

    drain.register_queue(q)
    assert drain.snapshot()["pending_deliveries"] == 0

    q.put_nowait({"event": "result", "data": {}})
    q.put_nowait({"event": "result", "data": {}})
    assert drain.snapshot()["pending_deliveries"] == 2

    q.get_nowait()
    assert drain.snapshot()["pending_deliveries"] == 1

    drain.unregister_queue(q)
    assert drain.snapshot()["pending_deliveries"] == 0


# ---------------------------------------------------------------------------
# pending_persistence counter
# ---------------------------------------------------------------------------


def test_pending_persistence_counter():
    drain = DrainTelemetry()
    assert drain.snapshot()["pending_persistence"] == 0
    drain.inc_pending_persistence()
    assert drain.snapshot()["pending_persistence"] == 1
    assert drain.snapshot()["quiescent"] is False
    drain.dec_pending_persistence()
    assert drain.snapshot()["pending_persistence"] == 0
    assert drain.snapshot()["quiescent"] is True

    # Should not go negative
    drain.dec_pending_persistence()
    assert drain.snapshot()["pending_persistence"] == 0
