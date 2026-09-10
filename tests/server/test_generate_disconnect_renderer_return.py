"""Test: client disconnect must return the Playwright renderer to the pool (issue #689).

Diagnoses whether the renderer leak reproduces at the in-process ASGI seam or only
under a real uvicorn/proxy stack.

Symptom on staging: after two aborted GET /api/generate streams, every later request
stalls forever at ``await renderer_pool.get()`` right after emitting ``started``.
Root cause: generate_question_stream acquires one of the two pooled renderers before
dispatching workers and returns it in its ``finally``; on a real client disconnect that
finally is interrupted before renderer_pool.put runs, so the renderer is never returned.

This test checks the in-process ASGI seam (no uvicorn, no Railway edge).
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Blocking fake spec: stage 1 blocks until first_call_release is set,
# then checks is_cancelled() before proceeding to stage 2.
# ---------------------------------------------------------------------------


def _make_blocking_spec(
    stage_calls: list[str],
    first_call_started: threading.Event,
    first_call_release: threading.Event,
) -> SubjectSpec:
    """Two-stage fake spec.

    - Stage 1: blocks until first_call_release is set; records 'stage1'.
    - Between stages: checks is_cancelled(); if True raises GenerationCancelled.
    - Stage 2: records 'stage2'.

    Copied from test_generate_cancel.py to avoid importing private helpers.
    """

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
        # ── Stage 1 ────────────────────────────────────────────────────────
        stage_calls.append("stage1")
        first_call_started.set()
        first_call_release.wait(timeout=30)

        # ── Cancel boundary ────────────────────────────────────────────────
        is_cancelled = kwargs.get("is_cancelled")
        if is_cancelled is not None and is_cancelled():
            from src.common.generation_core import GenerationCancelled  # noqa: PLC0415

            raise GenerationCancelled()

        # ── Stage 2 ────────────────────────────────────────────────────────
        stage_calls.append("stage2")
        return _FakeQuestion(id=kwargs["question_id"])

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


# ---------------------------------------------------------------------------
# Route-seam test
# ---------------------------------------------------------------------------


def test_client_disconnect_returns_renderer_to_pool_after_worker_exits(
    tmp_path: Path,
) -> None:
    """After a client disconnect, generate_question_stream must return the renderer.

    The renderer (an asyncio.Queue sentinel) is acquired right after emitting
    ``started`` and must be returned in the generator's ``finally`` after
    ``await signal_task`` resolves (i.e., after all workers finish).

    OUTCOME: FAILS on current code — the leak REPRODUCES in-process at the ASGI seam.
    Root cause: anyio's SSE task-group cancel scope raises CancelledError at EVERY
    await point, including ``await signal_task`` inside generate_question_stream's
    finally block.  The finally block exits before renderer_pool.put runs, so the
    renderer is permanently leaked.  The route's ``anyio.CancelScope(shield=True)``
    around ``await stream.aclose()`` is a no-op because the generator is already
    closed (its finally already ran and failed) by the time the route's
    ``except asyncio.CancelledError`` handler executes.

    Diagnostic (observed): persist_aborted_generation_record is called ~0.001 s after
    disconnect (well before the worker finishes), confirming that stream.aclose()
    returned immediately without waiting for signal_task.

    Determinism: all waits are bounded; no bare sleeps are used as synchronisation.
    """
    stage_calls: list[str] = []
    first_call_started = threading.Event()
    first_call_release = threading.Event()
    fake_spec = _make_blocking_spec(stage_calls, first_call_started, first_call_release)

    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )

    import urllib.parse  # noqa: PLC0415

    from src.common.resolver import resolve as _resolve  # noqa: PLC0415

    # Use a real resolved math payload so that route-level validation passes.
    # The stream wrapper below switches the subject to "fake" before it hits service.py.
    partial: dict[str, Any] = {
        "subject": "math",
        "seed": 1,
        "skip_verify": True,
    }
    resolved = _resolve(partial).payload
    wire: dict[str, Any] = {k: v for k, v in resolved.items() if v is not None}
    qs_bytes = urllib.parse.urlencode(wire, doseq=True).encode()

    original_stream = _gen_routes.generate_question_stream
    original_persist = _gen_routes.persist_aborted_generation_record

    async def _run() -> None:
        # ── DB — single in-memory engine for the lifetime of this event loop ──
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
        test_user = User(id=uuid.uuid4(), email="disconnect-renderer@example.com")
        async with _SessionLocal() as session:
            session.add(test_user)
            await session.commit()

        async def _override_session() -> Any:
            async with _SessionLocal() as sess:
                yield sess

        # ── Proxy: routes.generate_question_stream → fake spec ─────────────
        # The route calls stream.aclose() on disconnect, which throws GeneratorExit
        # into this proxy.  The proxy MUST explicitly call inner.aclose() in its
        # finally block so that generate_question_stream's own finally block runs
        # (setting cancel_event and returning the renderer).
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
                # (cancel_event.set() + await signal_task + renderer_pool.put)
                # runs when GeneratorExit is thrown into this proxy by the route.
                await inner.aclose()

        # ── Timing diagnostic: record when persist_aborted is called ────────
        persist_times: list[float] = []

        async def _timed_persist(**kwargs: Any) -> None:  # noqa: ARG001
            persist_times.append(time.time())
            # No-op: avoids real DB writes; the DB write is not under test here.

        _gen_routes.generate_question_stream = _stream_with_fake  # type: ignore[assignment]
        _gen_routes.persist_aborted_generation_record = _timed_persist  # type: ignore[assignment]
        limiter.reset()

        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: test_user
        app.dependency_overrides[get_async_session] = _override_session
        app.dependency_overrides[get_config] = lambda: config

        # Create the renderer pool with exactly one sentinel, on THIS event loop.
        # app.state.renderer_pool is what generate_question_stream reads via
        # getattr(app_state, "renderer_pool", None).
        pool: asyncio.Queue = asyncio.Queue()
        sentinel = object()
        await pool.put(sentinel)
        app.state.renderer_pool = pool

        try:
            # ── ASGI primitives ────────────────────────────────────────────────
            disconnect_event = asyncio.Event()
            response_complete = asyncio.Event()
            pipeline_start_seen = asyncio.Event()
            accumulated_body = bytearray()

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
                    return {"type": "http.request", "body": b"", "more_body": False}
                # Race disconnect vs. response complete — whichever fires first.
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

            async def send_fn(message: dict[str, Any]) -> None:
                if message["type"] == "http.response.body":
                    body = message.get("body", b"")
                    accumulated_body.extend(body)
                    if b"pipeline_start" in accumulated_body:
                        pipeline_start_seen.set()
                    if not message.get("more_body", False):
                        response_complete.set()

            # Run the ASGI app in a background task.
            route_task = asyncio.create_task(app(scope, receive, send_fn))

            # Wait for pipeline_start to appear in the SSE body — confirms the
            # generator has passed its ``started`` event and acquired the renderer.
            try:
                await asyncio.wait_for(pipeline_start_seen.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                pytest.fail("Timed out (15 s) waiting for pipeline_start in SSE body")

            # Wait for stage 1 to actually start inside the worker thread.
            started = await anyio.to_thread.run_sync(
                lambda: first_call_started.wait(15.0)
            )
            assert started, "Timed out waiting for stage 1 to start in worker"

            disconnect_time = time.time()

            # Signal HTTP disconnect while the route is still streaming.
            disconnect_event.set()

            # Release the blocking worker so signal_task can eventually resolve
            # and generate_question_stream's finally can reach renderer_pool.put.
            first_call_release.set()

            # Poll up to 10 s for the sentinel to return to the pool.
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if pool.qsize() == 1:
                    break
                await asyncio.sleep(0.05)

            # ── Diagnostic: timing of persist_aborted relative to disconnect ──
            if persist_times:
                delta = persist_times[0] - disconnect_time
                print(
                    f"\n[#689 diagnostic] persist_aborted_generation_record called "
                    f"{delta:.3f} s after disconnect "
                    f"(worker released simultaneously with disconnect)"
                )
            else:
                print(
                    "\n[#689 diagnostic] persist_aborted_generation_record was NOT "
                    "called during this run (aborted path may not have triggered)"
                )

            # ── Hard assertion: renderer must be back in the pool ────────────
            assert pool.qsize() == 1, (
                "Expected renderer (sentinel) to be returned to the pool after the "
                "worker exits and generate_question_stream's finally completes. "
                "A leaked renderer is what makes #689's stream stall forever after "
                "'started': with only 2 pooled renderers, two aborted runs empty "
                "the pool, and every subsequent `await renderer_pool.get()` blocks "
                "indefinitely. pool.qsize() == 0 means the in-process ASGI seam "
                "reproduces the leak."
            )
            returned_item = pool.get_nowait()
            assert returned_item is sentinel, (
                f"Item returned to pool is not the original sentinel: {returned_item!r}"
            )

            # Let the route task finish gracefully.
            try:
                await asyncio.wait_for(route_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                route_task.cancel()
                try:
                    await route_task
                except (asyncio.CancelledError, Exception):
                    pass

        finally:
            _gen_routes.generate_question_stream = original_stream  # type: ignore[assignment]
            _gen_routes.persist_aborted_generation_record = original_persist  # type: ignore[assignment]
            limiter.reset()
            await engine.dispose()

    anyio.run(_run)
