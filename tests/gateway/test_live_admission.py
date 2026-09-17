"""Controlled live-controller gateway checks for issue #778."""
from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from gateway.app import create_app
from gateway.release_controller import POLICY_SCHEMA, ReleaseController
from tests.gateway.test_proxy import _TestServer


def _policy(build_id: str = "build-a", revision: int = 1) -> dict:
    return {
        "schema": POLICY_SCHEMA,
        "environment": "test",
        "release_revision": revision,
        "released_build_id": build_id,
        "admission": "open",
        "supported_recovery_formats": ["json-v1"],
        "reader_version": "reader-1",
        "artifacts": {
            "current": {
                "build_id": build_id,
                "release_revision": revision,
                "reader_version": "reader-1",
            },
            "prepared_rollback": None,
            "transition": [],
        },
    }


def _drain(instance_id: str) -> dict:
    return {
        "instance_id": instance_id,
        "captured_at": datetime.now(UTC).isoformat(),
        "active_runs": 0,
        "active_workers": 0,
        "open_streams": 0,
        "pending_deliveries": 0,
        "pending_persistence": 0,
        "renderer_leases_held": 0,
        "integrity_errors": 0,
        "quiescent": True,
    }


def _make_backend() -> tuple[Starlette, list[int], threading.Event, threading.Event]:
    dispatches = [0]
    started = threading.Event()
    release = threading.Event()

    async def generate(_request: Request) -> StreamingResponse:
        dispatches[0] += 1
        started.set()

        async def body():
            yield b"event: started\ndata: {}\n\n"
            while not release.is_set():
                await asyncio.sleep(0.01)
            yield b"event: done\ndata: {}\n\n"

        return StreamingResponse(body(), media_type="text/event-stream")

    async def read_only(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    return (
        Starlette(
            routes=[
                Route("/api/generate", generate, methods=["GET", "POST"]),
                Route("/api/generate/", generate, methods=["GET", "POST"]),
                Route("/health", read_only, methods=["GET"]),
                Route("/api/history", read_only, methods=["GET"]),
            ]
        ),
        dispatches,
        started,
        release,
    )


def _publish_evidence(build_id: str = "build-b", revision: int = 2) -> dict:
    route = {
        "build_id": build_id,
        "release_revision": revision,
        "reader_version": "reader-1",
    }
    return {
        "instances": ["backend-1", "backend-2"],
        "expected_routes": ["frontend", "gateway"],
        "drain_snapshots": [_drain("backend-1"), _drain("backend-2")],
        "routes": [{"name": "frontend", **route}, {"name": "gateway", **route}],
    }


def test_controller_gateway_uses_one_live_policy_and_zero_work_on_rejection(tmp_path) -> None:
    backend, dispatches, _started, release = _make_backend()
    backend_server = _TestServer(backend)
    backend_server.start()
    state_dir = tmp_path / "gate"
    controller = ReleaseController(state_dir, environment="test")
    controller.initialize(_policy())
    gateway_server = _TestServer(
        create_app(
            backend_url=backend_server.base_url,
            state_dir=state_dir,
            control_token="secret",
            release_controller=controller,
        )
    )
    gateway_server.start()
    try:
        policy_response = httpx.get(f"{gateway_server.base_url}/release/policy.json")
        assert policy_response.status_code == 200
        assert policy_response.json()["released_build_id"] == "build-a"
        assert policy_response.headers["cache-control"] == "no-store"

        release.set()
        accepted = httpx.get(
            f"{gateway_server.base_url}/api/generate",
            headers={"X-Frontend-Build-ID": "build-a"},
            timeout=5,
        )
        assert accepted.status_code == 200
        assert dispatches[0] == 1

        stale = httpx.post(
            f"{gateway_server.base_url}/api/generate",
            headers={"X-Frontend-Build-ID": "old-build"},
            json={},
        )
        missing = httpx.get(f"{gateway_server.base_url}/api/generate")
        assert stale.status_code == 426
        assert missing.status_code == 426
        assert dispatches[0] == 1

        controller.prepare_target(
            {"build_id": "build-b", "release_revision": 2, "reader_version": "reader-1"}
        )
        paused = httpx.get(
            f"{gateway_server.base_url}/api/generate",
            headers={"X-Frontend-Build-ID": "build-a"},
        )
        assert paused.status_code == 503
        assert dispatches[0] == 1

        (state_dir / "admission.json").unlink()
        unavailable = httpx.get(
            f"{gateway_server.base_url}/api/generate",
            headers={"X-Frontend-Build-ID": "build-a"},
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["code"] == "AUTHORITY_UNAVAILABLE"
        assert dispatches[0] == 1
    finally:
        release.set()
        gateway_server.stop()
        backend_server.stop()


def test_policy_transition_waits_for_pending_admission_and_existing_stream_survives(
    tmp_path,
) -> None:
    backend, dispatches, started, release = _make_backend()
    backend_server = _TestServer(backend)
    backend_server.start()
    state_dir = tmp_path / "gate"
    controller = ReleaseController(state_dir, environment="test")
    controller.initialize(_policy())
    gateway_server = _TestServer(
        create_app(
            backend_url=backend_server.base_url,
            state_dir=state_dir,
            control_token="secret",
            release_controller=controller,
        )
    )
    gateway_server.start()
    stream_lines: list[str] = []
    errors: list[Exception] = []

    def consume() -> None:
        try:
            with httpx.stream(
                "GET",
                f"{gateway_server.base_url}/api/generate",
                headers={"X-Frontend-Build-ID": "build-a"},
            ) as response:
                stream_lines.extend(response.iter_lines())
        except Exception as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    try:
        assert started.wait(5)
        controller.prepare_target(
            {"build_id": "build-b", "release_revision": 2, "reader_version": "reader-1"}
        )
        pending = httpx.post(
            f"{gateway_server.base_url}/gateway/release/publish",
            headers={"X-Gateway-Control-Token": "secret"},
            json=_publish_evidence(),
        )
        assert pending.status_code == 409
        assert "pending" in pending.json()["detail"]
        assert thread.is_alive()

        release.set()
        thread.join(5)
        assert not errors
        assert any("done" in line for line in stream_lines)

        published = httpx.post(
            f"{gateway_server.base_url}/gateway/release/publish",
            headers={"X-Gateway-Control-Token": "secret"},
            json=_publish_evidence(),
        )
        assert published.status_code == 200
        assert published.json()["released_build_id"] == "build-b"
        assert published.json()["admission"] == "paused"
        assert dispatches[0] == 1
    finally:
        release.set()
        thread.join(5)
        gateway_server.stop()
        backend_server.stop()
