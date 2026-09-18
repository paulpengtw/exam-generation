"""ASGI reverse-proxy gateway with admission control."""

from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from gateway.admission import PAUSED_CODE, PAUSED_DETAIL, is_generation_entry, is_private_path
from gateway.release_controller import (
    ReleaseController,
    ReleasePolicyError,
)
from gateway.state import open_gate, pause, read_state

# Headers that must not be forwarded between hops
_HOP_BY_HOP = frozenset(
    [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    ]
)


def _filter_request_headers(headers: "httpx.Headers | dict") -> dict:
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "host"
    }


def _filter_response_headers(headers: "httpx.Headers") -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}


class PendingAdmissionTracker:
    """Thread-safe count of requests that passed the gateway admission seam."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._count = 0

    def enter(self) -> None:
        with self._lock:
            self._count += 1

    def leave(self) -> None:
        with self._lock:
            self._count = max(0, self._count - 1)

    @property
    def count(self) -> int:
        with self._lock:
            return self._count


def create_app(
    *,
    backend_url: str,
    state_dir: Path,
    control_token: str | None = None,
    release_controller: ReleaseController | None = None,
    pending_tracker: PendingAdmissionTracker | None = None,
) -> Starlette:
    """Create the gateway ASGI app.

    Parameters
    ----------
    backend_url:
        Base URL of the backend, e.g. ``http://localhost:8000``.
    state_dir:
        Directory where ``admission.json`` is stored.
    control_token:
        Secret token required in ``X-Gateway-Control-Token`` for the control
        endpoint.  Pass ``None`` to disable the control endpoint (returns 404).
    """
    # Shared httpx client — created on startup, closed on shutdown
    client_holder: list[httpx.AsyncClient] = []
    pending_admissions = pending_tracker or PendingAdmissionTracker()

    def _authority_unavailable() -> JSONResponse:
        return JSONResponse(
            {
                "detail": "Release authority unavailable; please retry.",
                "code": "AUTHORITY_UNAVAILABLE",
            },
            status_code=503,
            headers={"Retry-After": "30", "Cache-Control": "no-store"},
        )

    def _service_paused(reason: str | None = None) -> JSONResponse:
        return JSONResponse(
            {
                "detail": PAUSED_DETAIL,
                "code": "SERVICE_PAUSED",
                "reason": reason,
            },
            status_code=503,
            headers={"Retry-After": "60"},
        )

    def _controller_policy() -> dict[str, Any] | None:
        if release_controller is None:
            return None
        return release_controller.read_policy()

    @asynccontextmanager
    async def lifespan(app):  # noqa: ANN001
        client_holder.append(
            httpx.AsyncClient(
                base_url=backend_url,
                timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None),
                follow_redirects=False,
            )
        )
        yield
        if client_holder:
            await client_holder[0].aclose()

    # -----------------------------------------------------------------------
    # Local-only gateway endpoints
    # -----------------------------------------------------------------------

    async def gateway_health(request: Request) -> JSONResponse:
        state = read_state(state_dir)
        policy = _controller_policy()
        return JSONResponse(
            {
                "status": "ok",
                "admission": state.state,
                "reason": state.reason,
                "release_revision": policy.get("release_revision") if policy else None,
                "released_build_id": policy.get("released_build_id") if policy else None,
                "pending_admissions": pending_admissions.count,
            }
        )

    async def release_policy(request: Request) -> JSONResponse:
        policy = _controller_policy()
        if policy is None:
            return _authority_unavailable()
        return JSONResponse(policy, headers={"Cache-Control": "no-store"})

    async def build_meta(request: Request) -> JSONResponse:
        policy = _controller_policy()
        if policy is None:
            return _authority_unavailable()
        artifact = (policy.get("artifacts") or {}).get("current")
        if not isinstance(artifact, dict):
            artifact = {
                "build_id": policy["released_build_id"],
                "release_revision": policy["release_revision"],
                "reader_version": policy.get("reader_version"),
            }
        return JSONResponse(
            {
                "schema": "exam-generation.build-meta/1",
                "environment": policy["environment"],
                "build_id": artifact.get("build_id"),
                "release_revision": artifact.get("release_revision"),
                "reader_version": artifact.get("reader_version"),
            },
            headers={"Cache-Control": "no-store"},
        )

    def _require_control_token(request: Request) -> JSONResponse | None:
        if control_token is None:
            return JSONResponse({"detail": "Control endpoint is disabled."}, status_code=404)
        token = request.headers.get("X-Gateway-Control-Token", "")
        if token != control_token:
            return JSONResponse(
                {"detail": "Invalid or missing control token."}, status_code=403
            )
        return None

    async def gateway_admission(request: Request) -> JSONResponse:
        if response := _require_control_token(request):
            return response
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"detail": "Invalid JSON body."}, status_code=400)
        desired = body.get("state")
        reason = body.get("reason") if isinstance(body.get("reason"), str) else None
        if desired == "paused":
            new_state = pause(state_dir, reason=reason)
        elif desired == "open":
            if release_controller is not None:
                policy = _controller_policy()
                if policy is None:
                    return _authority_unavailable()
                if policy["admission"] == "preparing":
                    return JSONResponse(
                        {"detail": "Release preparation is still in progress."},
                        status_code=409,
                    )
            new_state = open_gate(state_dir)
        else:
            return JSONResponse(
                {"detail": "state must be 'paused' or 'open'."}, status_code=400
            )
        return JSONResponse(asdict(new_state))

    async def gateway_prepare(request: Request) -> JSONResponse:
        if response := _require_control_token(request):
            return response
        if release_controller is None:
            return _authority_unavailable()
        try:
            body = await request.json()
            target = body.get("target")
            assets = body.get("transition_assets", [])
            result = release_controller.prepare_target(target, transition_assets=assets)
        except ReleasePolicyError as exc:
            return JSONResponse(
                {"detail": str(exc), "code": "RELEASE_TRANSITION_REJECTED"}, status_code=409
            )
        except Exception:
            return JSONResponse({"detail": "Invalid release preparation request."}, status_code=400)
        return JSONResponse(result)

    async def gateway_publish(request: Request) -> JSONResponse:
        if response := _require_control_token(request):
            return response
        if release_controller is None:
            return _authority_unavailable()
        try:
            evidence = await request.json()
            if not isinstance(evidence, dict):
                raise ReleasePolicyError("release evidence must be an object")
            evidence = dict(evidence)
            # The controller receives the gateway's live count, not a caller's
            # assertion. This covers admissions already between gate and backend.
            evidence["pending_admissions"] = pending_admissions.count
            result = release_controller.publish_target(evidence)
        except ReleasePolicyError as exc:
            return JSONResponse(
                {"detail": str(exc), "code": "RELEASE_TRANSITION_REJECTED"}, status_code=409
            )
        except Exception:
            return JSONResponse({"detail": "Invalid release publication request."}, status_code=400)
        return JSONResponse(result)

    async def gateway_retire(request: Request) -> JSONResponse:
        if response := _require_control_token(request):
            return response
        if release_controller is None:
            return _authority_unavailable()
        try:
            body = await request.json()
            result = release_controller.retire_artifact(body["artifact"], body["evidence"])
        except (KeyError, TypeError, ReleasePolicyError) as exc:
            return JSONResponse(
                {"detail": str(exc), "code": "RELEASE_TRANSITION_REJECTED"}, status_code=409
            )
        return JSONResponse(result)

    # -----------------------------------------------------------------------
    # Reverse-proxy catch-all
    # -----------------------------------------------------------------------

    async def proxy(request: Request) -> StreamingResponse | JSONResponse:
        method = request.method
        path = request.url.path

        # /internal/* paths are NEVER proxied to the backend (privacy guard)
        if is_private_path(path):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        admission_held = False

        def _release_admission() -> None:
            nonlocal admission_held
            if admission_held:
                admission_held = False
                pending_admissions.leave()

        try:
            if is_generation_entry(method, path) and release_controller is not None:
                pending_admissions.enter()
                admission_held = True
                policy = _controller_policy()
                if policy is None:
                    _release_admission()
                    return _authority_unavailable()
                if policy["admission"] in {"paused", "preparing"}:
                    _release_admission()
                    return _service_paused()
                required_build_id = policy["released_build_id"]
                supplied_build_id = (request.headers.get("X-Frontend-Build-ID") or "").strip()
                if supplied_build_id != required_build_id:
                    _release_admission()
                    return JSONResponse(
                        {
                            "detail": "Client build is outdated; please reload the page.",
                            "code": "CLIENT_UPDATE_REQUIRED",
                            "required_build_id": required_build_id,
                        },
                        status_code=426,
                    )
            elif is_generation_entry(method, path):
                # Re-read state on every legacy gateway request — no caching.
                state = read_state(state_dir)
                if state.state == "paused":
                    return JSONResponse(
                        {
                            "detail": PAUSED_DETAIL,
                            "code": PAUSED_CODE,
                            "reason": state.reason,
                        },
                        status_code=503,
                        headers={"Retry-After": "30"},
                    )

            client = client_holder[0]
            # Build forwarded URL preserving raw query string
            raw_query = request.url.query
            target_path = f"{path}?{raw_query}" if raw_query else path

            # Forward request headers (minus hop-by-hop and host)
            fwd_headers = _filter_request_headers(dict(request.headers))

            # Add forwarding headers
            client_host = request.client.host if request.client else "unknown"
            existing_xff = fwd_headers.get("x-forwarded-for", "")
            fwd_headers["x-forwarded-for"] = (
                f"{existing_xff}, {client_host}" if existing_xff else client_host
            )
            fwd_headers["x-forwarded-proto"] = request.url.scheme
            fwd_headers["x-forwarded-host"] = request.headers.get("host", "")

            # Stream request body
            body = await request.body()

            # We need to keep the httpx response stream open while Starlette iterates it.
            # Build the request, send it, and pipe chunks through an async generator that
            # owns the open connection for the duration of the response body.
            req = client.build_request(method, target_path, headers=fwd_headers, content=body)
            try:
                backend_resp = await client.send(req, stream=True)
            except httpx.ConnectError as exc:
                _release_admission()
                return JSONResponse(
                    {"detail": f"Backend connection failed: {exc}"},
                    status_code=502,
                )
            except httpx.HTTPError as exc:
                _release_admission()
                return JSONResponse(
                    {"detail": f"Backend error: {exc}"},
                    status_code=502,
                )

            resp_headers = _filter_response_headers(backend_resp.headers)

            async def iter_raw():
                try:
                    async for chunk in backend_resp.aiter_raw():
                        yield chunk
                finally:
                    try:
                        await backend_resp.aclose()
                    finally:
                        _release_admission()

            return StreamingResponse(
                iter_raw(),
                status_code=backend_resp.status_code,
                headers=resp_headers,
                media_type=None,
            )
        except BaseException:
            _release_admission()
            raise

    routes = [
        Route("/gateway/health", gateway_health, methods=["GET"]),
        Route("/gateway/admission", gateway_admission, methods=["POST"]),
        Route("/gateway/release/prepare", gateway_prepare, methods=["POST"]),
        Route("/gateway/release/publish", gateway_publish, methods=["POST"]),
        Route("/gateway/release/retire", gateway_retire, methods=["POST"]),
        Route("/release/policy.json", release_policy, methods=["GET"]),
        Route("/build-meta.json", build_meta, methods=["GET"]),
        Route(
            "/{path:path}",
            proxy,
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        ),
        Route(
            "/",
            proxy,
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        ),
    ]

    return Starlette(
        routes=routes,
        lifespan=lifespan,
    )
