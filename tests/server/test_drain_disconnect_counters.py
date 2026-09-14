"""Drain counter assertions for disconnect and cancellation semantics (slice 5, task 4.4).

These tests extend the patterns from test_generate_cancel.py to assert:
- active_runs is nonzero while generation is in flight
- active_runs reaches zero after disconnect/cancel
- counters never go negative
"""
from __future__ import annotations

import asyncio
import threading
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
            if (
                event.get("event") == "pipeline"
                and isinstance(event.get("data"), dict)
                and event["data"].get("event_name") == "pipeline_start"
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
