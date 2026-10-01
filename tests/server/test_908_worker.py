"""Issue #908 – ``python -m server.worker`` runs the same host loop as the backend."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.worker import run_worker


def test_worker_runs_the_shared_host_loop_and_releases_state() -> None:
    calls: list[str] = []
    seen: dict[str, Any] = {}

    def fake_load(state: Any, config: ServerConfig) -> None:
        calls.append("load")
        state.renderer_pool = None

    def fake_stop(state: Any) -> None:
        calls.append("stop")

    async def fake_loop(stop_event: asyncio.Event, **kwargs: Any) -> None:
        calls.append("loop")
        seen.update(kwargs)
        await stop_event.wait()

    async def _run() -> None:
        stop = asyncio.Event()
        config = ServerConfig(api_key="x")
        task = asyncio.create_task(run_worker(stop, config))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=5)
        assert seen["config"] is config

    with (
        patch("server.worker.load_generation_state", fake_load),
        patch("server.worker.stop_generation_state", fake_stop),
        patch("server.worker.run_host_loop", fake_loop),
    ):
        asyncio.run(_run())

    assert calls == ["load", "loop", "stop"]
    assert seen["app_state"].renderer_pool is None
