"""Issue #909 – live SSE events route.

Tests the ``GET /api/runs/{id}/events`` endpoint at the ASGI level, confirming:
- 404 when run is not in-process (slot absent from ``_live_observers``)
- 404 for a different user even when the slot exists (ownership check)
- 200 + SSE stream that delivers queued events and terminates on ``done``
- ``GET /api/runs/{id}`` reports ``live_events_available`` correctly
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.run import _live_observers, _publish_live
from server.models import Base, User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params


def _body(**overrides: Any) -> dict[str, Any]:
    payload = complete_math_query_params(
        seed=41,
        grade=8,
        context=["個人"],
        set_type="單一題",
        q_type=["選擇題"],
        style=["text_only"],
        math_thinking=["形成"],
        learning_content=["A-7-7"],
        learning_performance=["s-IV-12"],
        core_competency=["數-J-A2"],
        content_type="純文字",
        skip_verify=True,
        count=1,
    )
    payload.pop("stream_version", None)
    payload["stream_version"] = 3
    payload.update(overrides)
    return payload


class _Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.db_url = f"sqlite+aiosqlite:///{tmp_path / 'live_route.db'}"
        self.config = ServerConfig(
            api_key="x",
            jwt_secret="test-secret",
            gemini_api_key="x",
            output_dir=tmp_path / "out",
            data_dir=Path("data"),
        )
        self.owner = uuid.uuid4()
        self.other = uuid.uuid4()

        async def _init() -> None:
            engine = create_async_engine(self.db_url)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with sessions() as session:
                session.add_all([
                    User(id=self.owner, email="owner@example.com"),
                    User(id=self.other, email="other@example.com"),
                ])
                await session.commit()
            await engine.dispose()

        asyncio.run(_init())

    def app(self) -> Any:
        engine = create_async_engine(self.db_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async def override_session() -> AsyncGenerator[AsyncSession, None]:
            async with sessions() as session:
                yield session

        app = create_app()
        app.dependency_overrides[get_async_session] = override_session
        app.dependency_overrides[get_config] = lambda: self.config
        limiter.reset()
        return app

    def headers(self, user_id: uuid.UUID) -> dict[str, str]:
        email = "owner@example.com" if user_id == self.owner else "other@example.com"
        return {"Authorization": f"Bearer {create_jwt(user_id, email, config=self.config)}"}


@pytest.fixture(autouse=True)
def _quiet_outcome_metric():
    from unittest.mock import patch
    with patch("server.observability.record_generation_outcome"):
        yield


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure the global observer registry is clean before and after each test."""
    _live_observers.clear()
    yield
    _live_observers.clear()


@pytest.fixture()
def harness(tmp_path: Path) -> _Harness:
    return _Harness(tmp_path)


def test_live_events_not_advertised_for_queued_run(harness: _Harness) -> None:
    """GET /api/runs/{id} on a queued (not in-process) run shows live_events_available: false."""
    with TestClient(harness.app()) as client:
        accepted = client.post(
            "/api/generate", json=_body(), headers=harness.headers(harness.owner)
        )
        assert accepted.status_code == 202
        run_id = accepted.json()["run_id"]

        # No host loop running — slot not in _live_observers.
        read = client.get(f"/api/runs/{run_id}", headers=harness.headers(harness.owner))
        assert read.status_code == 200
        data = read.json()
        # live_events_available is false when run is not in-process.
        assert data.get("live_events_available") is False


def test_events_route_404_when_not_in_process(harness: _Harness) -> None:
    """GET /api/runs/{id}/events returns 404 when run slot is absent."""
    with TestClient(harness.app()) as client:
        accepted = client.post(
            "/api/generate", json=_body(), headers=harness.headers(harness.owner)
        )
        run_id = accepted.json()["run_id"]

        # No host loop → slot not in registry → 404.
        response = client.get(
            f"/api/runs/{run_id}/events", headers=harness.headers(harness.owner)
        )
        assert response.status_code == 404


def test_events_route_404_for_non_owner(harness: _Harness) -> None:
    """GET /api/runs/{id}/events returns 404 for a different user even when slot exists."""
    with TestClient(harness.app()) as client:
        accepted = client.post(
            "/api/generate", json=_body(), headers=harness.headers(harness.owner)
        )
        run_id = accepted.json()["run_id"]

        # Register the slot as if a host loop started it.
        _live_observers[run_id] = []
        try:
            response = client.get(
                f"/api/runs/{run_id}/events", headers=harness.headers(harness.other)
            )
            assert response.status_code == 404
        finally:
            _live_observers.pop(run_id, None)


def test_live_events_advertised_for_in_process_run(harness: _Harness) -> None:
    """GET /api/runs/{id} reports live_events_available: true while the slot is registered."""
    with TestClient(harness.app()) as client:
        accepted = client.post(
            "/api/generate", json=_body(), headers=harness.headers(harness.owner)
        )
        assert accepted.status_code == 202
        run_id = accepted.json()["run_id"]

        _live_observers[run_id] = []
        try:
            read = client.get(f"/api/runs/{run_id}", headers=harness.headers(harness.owner))
            assert read.status_code == 200
            assert read.json().get("live_events_available") is True
        finally:
            _live_observers.pop(run_id, None)


def test_events_route_streams_sse_for_in_process_run(harness: _Harness) -> None:
    """SSE stream delivers events and terminates on done; all I/O in ONE event loop.

    Required coverage (issue #909 task brief item 1):
    (a) live_events_available: true covered by test_live_events_advertised_for_in_process_run.
    (b) Owner receives 200 + text/event-stream; each SSE frame has ``event:`` and
        ``data:`` lines whose JSON body contains the ``event`` key; stream ends on done.
    Uses httpx.AsyncClient + httpx.ASGITransport so the ASGI app runs in the same
    event loop as the publisher task — no cross-thread queue writes.
    httpx.ASGITransport buffers the full body, so the stream MUST terminate with done.
    asyncio.wait_for guards the whole run so a regression fails instead of hanging.
    """
    async def _run() -> None:
        app = harness.app()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Accept a run via the real API endpoint.
            post_resp = await client.post(
                "/api/generate",
                json=_body(),
                headers=harness.headers(harness.owner),
            )
            assert post_resp.status_code == 202, post_resp.text
            run_id = post_resp.json()["run_id"]

            # 2. Register the slot as if execute_run just started.
            _live_observers[run_id] = []

            # 3. Publisher coroutine: wait for the route to call subscribe_live
            #    (which appends its queue to the slot), then deliver one payload
            #    event and the done sentinel.  Runs in the SAME event loop via
            #    create_task, so put_nowait is safe.
            async def _publisher() -> None:
                deadline = asyncio.get_event_loop().time() + 8.0
                while asyncio.get_event_loop().time() < deadline:
                    observers = list(_live_observers.get(run_id, []))
                    if observers:
                        await _publish_live(
                            run_id,
                            {
                                "event": "question_update",
                                "context": {
                                    "run_id": run_id,
                                    "event_seq": 1,
                                    "question_id": "q-001",
                                },
                                "payload": {"phase": "plan", "step": "start"},
                            },
                        )
                        await _publish_live(run_id, {"event": "done", "payload": None})
                        return
                    await asyncio.sleep(0.01)
                # Fallback: no observer appeared; push done so the route unblocks.
                await _publish_live(run_id, {"event": "done", "payload": None})

            publisher_task = asyncio.create_task(_publisher())

            # 4. GET the SSE stream.  ASGITransport buffers the entire body, so
            #    this await returns only after the generator yields done + stops.
            events_resp = await asyncio.wait_for(
                client.get(
                    f"/api/runs/{run_id}/events",
                    headers=harness.headers(harness.owner),
                ),
                timeout=10.0,
            )
            await publisher_task

        # 5. Assertions on status and content-type.
        assert events_resp.status_code == 200, events_resp.text
        assert "text/event-stream" in events_resp.headers.get("content-type", "")

        body = events_resp.text
        assert "event: done" in body, f"no done event in: {body!r}"

        # 6. Verify SSE frame shape: every frame must have event: + data: lines,
        #    and the data JSON must contain an 'event' key (envelope check).
        frames: list[dict[str, Any]] = []
        for chunk in body.split("\n\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            lines = chunk.splitlines()
            ev_line = next((ln for ln in lines if ln.startswith("event: ")), None)
            data_line = next((ln for ln in lines if ln.startswith("data: ")), None)
            assert ev_line is not None, f"SSE frame missing 'event:' line: {chunk!r}"
            assert data_line is not None, f"SSE frame missing 'data:' line: {chunk!r}"
            parsed = json.loads(data_line[len("data: "):])
            assert "event" in parsed, f"SSE data JSON missing 'event' key: {parsed}"
            frames.append(parsed)

        done_frames = [f for f in frames if f["event"] == "done"]
        assert len(done_frames) == 1, f"expected exactly one done frame, got: {done_frames}"

        _live_observers.pop(run_id, None)

    asyncio.run(asyncio.wait_for(_run(), timeout=15.0))


def test_events_route_full_envelope_for_generation_event(harness: _Harness) -> None:
    """SSE data JSON carries the full {event, context, payload} envelope for a real event.

    Item 3 (issue #909 review): confirms the wire format contains all three envelope
    fields — not just ``event`` — for a published non-done generation event.
    ``context`` must carry at least ``run_id``, ``event_seq`` and ``question_id``.
    ``payload`` must be a dict (not None) for a generation event.
    """
    async def _run() -> None:
        app = harness.app()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            post_resp = await client.post(
                "/api/generate",
                json=_body(),
                headers=harness.headers(harness.owner),
            )
            assert post_resp.status_code == 202, post_resp.text
            run_id = post_resp.json()["run_id"]

            _live_observers[run_id] = []

            question_event = {
                "event": "question_update",
                "context": {
                    "run_id": run_id,
                    "event_seq": 1,
                    "question_id": "q-001",
                },
                "payload": {"phase": "draft", "index": 0, "question": {"id": "q-001"}},
            }

            async def _publisher() -> None:
                deadline = asyncio.get_event_loop().time() + 8.0
                while asyncio.get_event_loop().time() < deadline:
                    if list(_live_observers.get(run_id, [])):
                        await _publish_live(run_id, question_event)
                        await _publish_live(run_id, {"event": "done", "payload": None})
                        return
                    await asyncio.sleep(0.01)
                await _publish_live(run_id, {"event": "done", "payload": None})

            publisher_task = asyncio.create_task(_publisher())

            events_resp = await asyncio.wait_for(
                client.get(
                    f"/api/runs/{run_id}/events",
                    headers=harness.headers(harness.owner),
                ),
                timeout=10.0,
            )
            await publisher_task

        assert events_resp.status_code == 200, events_resp.text
        body = events_resp.text

        # Collect all non-done SSE frames.
        generation_frames: list[dict[str, Any]] = []
        for chunk in body.split("\n\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            lines = chunk.splitlines()
            data_line = next((ln for ln in lines if ln.startswith("data: ")), None)
            if data_line is None:
                continue
            parsed = json.loads(data_line[len("data: "):])
            if parsed.get("event") != "done":
                generation_frames.append(parsed)

        assert generation_frames, "expected at least one non-done generation frame"
        frame = generation_frames[0]

        # Full envelope: all three top-level keys must be present.
        assert "event" in frame, f"missing 'event' in frame: {frame}"
        assert "context" in frame, f"missing 'context' in frame: {frame}"
        assert "payload" in frame, f"missing 'payload' in frame: {frame}"

        # context must carry the three identity fields.
        ctx = frame["context"]
        assert ctx.get("run_id") == run_id, f"context.run_id mismatch: {ctx}"
        assert isinstance(ctx.get("event_seq"), int), f"context.event_seq not int: {ctx}"
        assert ctx.get("question_id") == "q-001", f"context.question_id mismatch: {ctx}"

        # payload must be a dict for a generation event (not None like done).
        assert isinstance(frame["payload"], dict), f"payload not a dict: {frame['payload']}"

        _live_observers.pop(run_id, None)

    asyncio.run(asyncio.wait_for(_run(), timeout=15.0))
