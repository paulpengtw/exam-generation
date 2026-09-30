"""Issue #909 – live SSE events route.

Tests the ``GET /api/runs/{id}/events`` endpoint at the ASGI level, confirming:
- 404 when run is not in-process (slot absent from ``_live_observers``)
- 404 for a different user even when the slot exists (ownership check)
- 200 + SSE stream that delivers queued events and terminates on ``done``
- ``GET /api/runs/{id}`` reports ``live_events_available`` correctly
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.run import _live_observers
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


def test_events_route_opens_sse_stream_for_in_process_run(harness: _Harness) -> None:
    """With the run slot registered, GET /api/runs/{id}/events returns 200 + SSE content-type.

    We register the run's slot and then send the done sentinel via a background
    thread so the response body terminates quickly.
    """
    import threading
    import time

    with TestClient(harness.app()) as client:
        accepted = client.post(
            "/api/generate", json=_body(), headers=harness.headers(harness.owner)
        )
        run_id = accepted.json()["run_id"]

        # Register the slot directly so is_live_available returns True.
        # The route will call subscribe_live which adds its own queue to the list.
        _live_observers[run_id] = []

        # Background thread: wait briefly then publish the done sentinel to any
        # observer queues that appear after subscribe_live is called by the route.
        sent = threading.Event()

        def _publisher():
            # Wait until the route has had a chance to call subscribe_live and
            # register its queue.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                observers = _live_observers.get(run_id, [])
                if observers:
                    for q in list(observers):
                        try:
                            q.put_nowait({"event": "done", "payload": None})
                        except Exception:
                            pass
                    sent.set()
                    return
                time.sleep(0.01)
            # If no observer appeared, put done into registry directly.
            _live_observers.setdefault(run_id, [])
            sent.set()

        t = threading.Thread(target=_publisher, daemon=True)
        t.start()
        try:
            # TestClient will buffer the full response; the done event triggers break.
            response = client.get(
                f"/api/runs/{run_id}/events",
                headers=harness.headers(harness.owner),
            )
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            # The response body must include a done event line.
            assert "event: done" in response.text
        finally:
            sent.wait(timeout=5.0)
            t.join(timeout=5.0)
            _live_observers.pop(run_id, None)
