"""ASGI reverse-proxy gateway with admission control."""

from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from gateway.admission import PAUSED_CODE, PAUSED_DETAIL, is_generation_entry
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


def create_app(
    *,
    backend_url: str,
    state_dir: Path,
    control_token: str | None = None,
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
        return JSONResponse({"status": "ok", "admission": state.state, "reason": state.reason})

    async def gateway_admission(request: Request) -> JSONResponse:
        if control_token is None:
            return JSONResponse({"detail": "Control endpoint is disabled."}, status_code=404)
        token = request.headers.get("X-Gateway-Control-Token", "")
        if token != control_token:
            return JSONResponse({"detail": "Invalid or missing control token."}, status_code=403)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"detail": "Invalid JSON body."}, status_code=400)
        desired = body.get("state")
        reason = body.get("reason") if isinstance(body.get("reason"), str) else None
        if desired == "paused":
            new_state = pause(state_dir, reason=reason)
        elif desired == "open":
            new_state = open_gate(state_dir)
        else:
            return JSONResponse(
                {"detail": "state must be 'paused' or 'open'."}, status_code=400
            )
        return JSONResponse(asdict(new_state))

    # -----------------------------------------------------------------------
    # Reverse-proxy catch-all
    # -----------------------------------------------------------------------

    async def proxy(request: Request) -> StreamingResponse | JSONResponse:
        method = request.method
        path = request.url.path

        # Re-read state on every request — no caching
        state = read_state(state_dir)

        if state.state == "paused" and is_generation_entry(method, path):
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
            return JSONResponse(
                {"detail": f"Backend connection failed: {exc}"},
                status_code=502,
            )
        except httpx.HTTPError as exc:
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
                await backend_resp.aclose()

        return StreamingResponse(
            iter_raw(),
            status_code=backend_resp.status_code,
            headers=resp_headers,
            media_type=None,
        )

    routes = [
        Route("/gateway/health", gateway_health, methods=["GET"]),
        Route("/gateway/admission", gateway_admission, methods=["POST"]),
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
