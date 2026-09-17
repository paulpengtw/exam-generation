"""Repeatable local release-admission evidence rehearsal for issue #778.

The rehearsal uses two real local backend HTTP servers and two gateway HTTP
servers sharing one file-backed controller record.  It never contacts a
deployment environment.  The output records observed HTTP responses and the
backend dispatch counters that produced them.

Run from the repository root with::

    uv run python scripts/release_admission_rehearsal.py \
      --output docs/research/2026-09-17-778-release-admission/evidence.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import threading
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

# When invoked as ``python scripts/...py``, Python puts ``scripts/`` rather
# than the repository root on sys.path. Keep the documented command working.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from gateway.app import PendingAdmissionTracker, create_app  # noqa: E402
from gateway.release_controller import POLICY_SCHEMA, ReleaseController  # noqa: E402
from gateway.state import open_gate, pause  # noqa: E402

CURRENT_BUILD = "build-current"
NEXT_BUILD = "build-next"
ENVIRONMENT = "test"
READER_VERSION = "reader-1"
ROUTE_INVENTORY = (
    ("GET", "/release/policy.json", "metadata"),
    ("GET", "/build-meta.json", "metadata"),
    ("GET", "/api/generate", "generation"),
    ("POST", "/api/generate", "generation"),
    ("GET", "/api/generate/", "generation"),
    ("POST", "/api/generate/", "generation"),
    ("POST", "/api/generate/preview", "passthrough"),
    ("POST", "/api/generate/resolve", "passthrough"),
    ("POST", "/api/plan-core-questions", "passthrough"),
    ("POST", "/api/generation-records/example/modifications", "passthrough"),
    ("GET", "/api/generation-logs/example/exchanges", "passthrough"),
    ("GET", "/api/history", "passthrough"),
    ("GET", "/api/history/1", "passthrough"),
    ("GET", "/api/schemas", "passthrough"),
    ("GET", "/auth/magic-link", "passthrough"),
    ("POST", "/auth/session", "passthrough"),
    ("GET", "/health", "passthrough"),
    ("GET", "/internal/drain", "private"),
)


def _policy(build_id: str = CURRENT_BUILD, revision: int = 1) -> dict[str, Any]:
    return {
        "schema": POLICY_SCHEMA,
        "environment": ENVIRONMENT,
        "release_revision": revision,
        "released_build_id": build_id,
        "admission": "open",
        "supported_recovery_formats": ["json-v1"],
        "reader_version": READER_VERSION,
        "artifacts": {
            "current": {
                "build_id": build_id,
                "release_revision": revision,
                "reader_version": READER_VERSION,
            },
            "prepared_rollback": None,
            "transition": [],
        },
    }


class _Backend:
    def __init__(self, name: str) -> None:
        self.name = name
        self.generation_dispatches = 0
        self.provider_dispatches = 0
        self.read_only_dispatches = 0
        self.requests: list[tuple[str, str]] = []
        self.generation_started = threading.Event()
        self.stream_release = threading.Event()
        self.stream_release.set()

    def app(self) -> Starlette:
        async def generate(request: Request) -> StreamingResponse:
            self.generation_dispatches += 1
            self.provider_dispatches += 1
            self.requests.append((request.method, request.url.path))
            self.generation_started.set()

            async def body():
                yield b"event: started\ndata: {}\n\n"
                while not self.stream_release.is_set():
                    await asyncio.sleep(0.01)
                yield b"event: done\ndata: {}\n\n"

            return StreamingResponse(body(), media_type="text/event-stream")

        async def read_only(request: Request) -> JSONResponse:
            self.read_only_dispatches += 1
            self.requests.append((request.method, request.url.path))
            return JSONResponse({"ok": True, "backend": self.name})

        return Starlette(
            routes=[
                Route("/api/generate", generate, methods=["GET", "POST"]),
                Route("/api/generate/", generate, methods=["GET", "POST"]),
                Route("/api/generate/preview", read_only, methods=["POST"]),
                Route("/api/generate/resolve", read_only, methods=["POST"]),
                Route("/api/plan-core-questions", read_only, methods=["POST"]),
                Route(
                    "/api/generation-records/{rest:path}",
                    read_only,
                    methods=["POST"],
                ),
                Route(
                    "/api/generation-logs/{rest:path}",
                    read_only,
                    methods=["GET"],
                ),
                Route("/api/history", read_only, methods=["GET"]),
                Route("/api/history/{rest:path}", read_only, methods=["GET"]),
                Route("/api/schemas", read_only, methods=["GET"]),
                Route("/auth/{rest:path}", read_only, methods=["GET", "POST"]),
                Route("/health", read_only, methods=["GET"]),
            ]
        )


class _Server:
    def __init__(self, app: Starlette) -> None:
        self.config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            log_level="error",
        )
        # uvicorn does not reliably expose the chosen port when port=0 until
        # after bind, so reserve a local socket through the test helper path.
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = int(sock.getsockname()[1])
        self.config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.port,
            log_level="error",
        )
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() >= deadline:
                raise RuntimeError("local rehearsal server did not start")
            time.sleep(0.02)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _request(base_url: str, method: str, path: str, *, headers: dict[str, str] | None = None):
    kwargs: dict[str, Any] = {"headers": headers or {}, "timeout": 10}
    if method == "POST":
        kwargs["json"] = {}
    return httpx.request(method, f"{base_url}{path}", **kwargs)


def _drain(instance_id: str) -> dict[str, Any]:
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


def _publish_evidence() -> dict[str, Any]:
    route = {
        "build_id": NEXT_BUILD,
        "release_revision": 2,
        "reader_version": READER_VERSION,
    }
    return {
        "instances": ["backend-1", "backend-2"],
        "drain_snapshots": [_drain("backend-1"), _drain("backend-2")],
        "routes": [{"name": "frontend", **route}, {"name": "gateway", **route}],
    }


def _nginx_headers() -> dict[str, bool]:
    result: dict[str, bool] = {}
    root = Path(__file__).resolve().parents[1] / "web"
    for name in ("nginx.conf", "nginx.conf.template"):
        content = (root / name).read_text(encoding="utf-8")
        policy = re.search(r"location\s*=\s*/release/policy\.json\s*\{(?P<body>[^}]*)}", content)
        meta = re.search(r"location\s*=\s*/build-meta\.json\s*\{(?P<body>[^}]*)}", content)
        result[name] = bool(
            policy
            and meta
            and "proxy_pass" in policy.group("body")
            and "proxy_pass" in meta.group("body")
            and content.count("Cache-Control 'no-store'") >= 2
            and "Cache-Control 'no-cache'" in content
        )
    return result


def run_rehearsal(output_path: Path | str) -> dict[str, Any]:
    """Run the local rehearsal and write/return its JSON evidence document."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    state_dir = output.parent / f".release-state-{uuid.uuid4().hex}"
    controller = ReleaseController(state_dir, environment=ENVIRONMENT, max_drain_age_seconds=30)
    controller.initialize(_policy())

    backends = [_Backend("backend-1"), _Backend("backend-2")]
    backend_servers = [_Server(backend.app()) for backend in backends]
    tracker = PendingAdmissionTracker()
    gateway_servers: list[_Server] = []
    route_inventory: list[dict[str, Any]] = []
    try:
        for server in backend_servers:
            server.start()
        for backend_server in backend_servers:
            gateway_servers.append(
                _Server(
                    create_app(
                        backend_url=backend_server.base_url,
                        state_dir=state_dir,
                        control_token="evidence-token",
                        release_controller=ReleaseController(
                            state_dir,
                            environment=ENVIRONMENT,
                            max_drain_age_seconds=30,
                        ),
                        pending_tracker=tracker,
                    )
                )
            )
        for server in gateway_servers:
            server.start()

        route_headers = {"X-Frontend-Build-ID": CURRENT_BUILD}
        for gateway_index, gateway in enumerate(gateway_servers, start=1):
            for method, path, kind in ROUTE_INVENTORY:
                headers = route_headers if kind == "metadata" else {}
                if kind == "generation":
                    # Inventory coverage uses the missing-build path so it
                    # proves the alternate route is gated without adding work.
                    headers = {}
                response = _request(gateway.base_url, method, path, headers=headers)
                route_inventory.append(
                    {
                        "surface": f"gateway-{gateway_index}",
                        "method": method,
                        "path": path,
                        "kind": kind,
                        "status": response.status_code,
                        "code": response.json().get("code")
                        if response.headers.get("content-type", "").startswith("application/json")
                        else None,
                        "backend": backends[gateway_index - 1].name,
                    }
                )

        # One accepted current generation, with the exact backend dispatch
        # seam recorded before/after the request.
        before_current = sum(item.generation_dispatches for item in backends)
        accepted = _request(
            gateway_servers[0].base_url,
            "GET",
            "/api/generate",
            headers=route_headers,
        )
        after_current = sum(item.generation_dispatches for item in backends)
        current_check = {
            "status": accepted.status_code,
            "generation_dispatches": after_current - before_current,
            "provider_dispatches": sum(item.provider_dispatches for item in backends),
        }

        # Stale and missing IDs are rejected at both alternate generation
        # spellings without contacting either backend dispatch seam.
        before_rejected = sum(item.generation_dispatches for item in backends)
        rejected_responses = [
            _request(
                gateway_servers[0].base_url,
                "GET",
                "/api/generate",
                headers={"X-Frontend-Build-ID": "old-build"},
            ),
            _request(gateway_servers[1].base_url, "POST", "/api/generate/", headers={}),
        ]
        stale_missing_check = {
            "rejected_statuses": [response.status_code for response in rejected_responses],
            "generation_dispatches_delta": sum(item.generation_dispatches for item in backends)
            - before_rejected,
        }

        # Pause is controlled only by the persistent controller record. Both
        # alternate gateways observe it, and neither dispatches work.
        open_gate(state_dir)
        before_paused = sum(item.generation_dispatches for item in backends)
        pause(state_dir, reason="controlled evidence")
        paused_responses = [
            _request(gateway.base_url, "GET", "/api/generate", headers=route_headers)
            for gateway in gateway_servers
        ]
        paused_delta = sum(item.generation_dispatches for item in backends) - before_paused

        # A missing authority is distinct from a deliberate pause but remains
        # fail-closed and has the same zero-work guarantee.
        (state_dir / "admission.json").unlink()
        before_unavailable = sum(item.generation_dispatches for item in backends)
        unavailable_responses = [
            _request(gateway.base_url, "POST", "/api/generate/", headers=route_headers)
            for gateway in gateway_servers
        ]
        unavailable_delta = (
            sum(item.generation_dispatches for item in backends) - before_unavailable
        )
        controller.initialize(_policy())

        # An established stream remains usable while read-only routes continue
        # to be served after the gate is paused.
        open_gate(state_dir)
        backends[1].generation_started.clear()
        backends[1].stream_release.clear()
        stream_lines: list[str] = []
        stream_errors: list[str] = []

        def consume_stream() -> None:
            try:
                with httpx.stream(
                    "GET",
                    f"{gateway_servers[1].base_url}/api/generate/",
                    headers=route_headers,
                    timeout=10,
                ) as response:
                    stream_lines.extend(response.iter_lines())
            except Exception as exc:  # pragma: no cover - surfaced in evidence
                stream_errors.append(str(exc))

        stream_thread = threading.Thread(target=consume_stream, daemon=True)
        stream_thread.start()
        if not backends[1].generation_started.wait(5):
            raise RuntimeError("stream did not reach backend dispatch seam")
        pause(state_dir, reason="stream continuity check")
        read_responses = [
            _request(gateway.base_url, "GET", path)
            for gateway in gateway_servers
            for path in ("/health", "/api/history")
        ]
        backends[1].stream_release.set()
        stream_thread.join(timeout=10)
        open_gate(state_dir)

        # Prepare a target while a second stream is in flight. Publication is
        # rejected from the gateway because it injects its live shared pending
        # admission count into the controller evidence.
        backends[0].generation_started.clear()
        backends[0].stream_release.clear()
        pending_lines: list[str] = []

        def consume_pending() -> None:
            with suppress(Exception):
                with httpx.stream(
                    "GET",
                    f"{gateway_servers[0].base_url}/api/generate",
                    headers=route_headers,
                    timeout=10,
                ) as response:
                    pending_lines.extend(response.iter_lines())

        pending_thread = threading.Thread(target=consume_pending, daemon=True)
        pending_thread.start()
        if not backends[0].generation_started.wait(5):
            raise RuntimeError("pending stream did not reach backend dispatch seam")
        controller.prepare_target(
            {"build_id": NEXT_BUILD, "release_revision": 2, "reader_version": READER_VERSION}
        )
        pending_publish = httpx.post(
            f"{gateway_servers[0].base_url}/gateway/release/publish",
            headers={"X-Gateway-Control-Token": "evidence-token"},
            json=_publish_evidence(),
            timeout=10,
        )
        backends[0].stream_release.set()
        pending_thread.join(timeout=10)
        published = httpx.post(
            f"{gateway_servers[0].base_url}/gateway/release/publish",
            headers={"X-Gateway-Control-Token": "evidence-token"},
            json=_publish_evidence(),
            timeout=10,
        )

        evidence = {
            "schema": "exam-generation.release-admission-evidence/1",
            "issue": 778,
            "generated_at": datetime.now(UTC).isoformat(),
            "authority": {
                "schema": POLICY_SCHEMA,
                "environment": ENVIRONMENT,
                "initial_build_id": CURRENT_BUILD,
                "published_build_id": NEXT_BUILD,
                "published_revision": 2,
            },
            "backend_instances": [
                {"name": backend.name, "url": server.base_url}
                for backend, server in zip(backends, backend_servers, strict=True)
            ],
            "route_inventory": route_inventory,
            "checks": {
                "current_build_accepted": current_check,
                "stale_or_missing_build": stale_missing_check,
                "paused_or_unavailable_authority": {
                    "statuses": [response.status_code for response in paused_responses],
                    "unavailable_statuses": [
                        response.status_code for response in unavailable_responses
                    ],
                    "generation_dispatches_delta": paused_delta + unavailable_delta,
                    "paused_codes": [
                        response.json().get("code") for response in paused_responses
                    ],
                    "unavailable_codes": [
                        response.json().get("code") for response in unavailable_responses
                    ],
                },
                "existing_stream_and_read_only": {
                    "stream_completed": not stream_thread.is_alive()
                    and not stream_errors
                    and any("done" in line for line in stream_lines),
                    "read_only_statuses": [response.status_code for response in read_responses],
                },
                "pending_transition": {
                    "pending_publish_status": pending_publish.status_code,
                    "published_status": published.status_code,
                    "pending_publish_code": pending_publish.json().get("code"),
                    "published_build_id": published.json().get("released_build_id"),
                    "pending_stream_completed": not pending_thread.is_alive()
                    and any("done" in line for line in pending_lines),
                },
                "nginx_headers": _nginx_headers(),
            },
            "dispatch_evidence": [
                {
                    "name": backend.name,
                    "generation_dispatches": backend.generation_dispatches,
                    "provider_dispatches": backend.provider_dispatches,
                    "read_only_dispatches": backend.read_only_dispatches,
                    "request_count": len(backend.requests),
                }
                for backend in backends
            ],
        }
        output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return evidence
    finally:
        for server in reversed(gateway_servers):
            server.stop()
        for server in reversed(backend_servers):
            server.stop()
        with suppress(OSError):
            (state_dir / "admission.json").unlink()
        with suppress(OSError):
            state_dir.rmdir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/research/2026-09-17-778-release-admission/evidence.json"),
    )
    args = parser.parse_args(argv)
    evidence = run_rehearsal(args.output)
    print(
        json.dumps(
            {"output": str(args.output), "checks": evidence["checks"]}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
