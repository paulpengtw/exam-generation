"""Slice 3 proxy app tests — real in-process uvicorn servers."""

import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

# ---------------------------------------------------------------------------
# Fake backend helpers
# ---------------------------------------------------------------------------


def _make_fake_backend() -> Starlette:
    """Create a fake backend app that records requests and serves SSE for /api/generate.

    Uses a threading.Event so the test thread can control release without needing
    access to the uvicorn event loop.
    """
    generation_counter = [0]
    requests_log: list[tuple[str, str]] = []

    async def generate_dynamic(request: Request) -> StreamingResponse:
        generation_counter[0] += 1
        requests_log.append((request.method, request.url.path))
        ev = app.state.release_event  # type: ignore[attr-defined]

        async def sse_body():
            yield b"event: started\ndata: {}\n\n"
            if ev is not None:
                # Poll the threading.Event without blocking the event loop
                deadline = time.monotonic() + 10.0
                while not ev.is_set() and time.monotonic() < deadline:
                    await asyncio.sleep(0.05)
            yield b"event: result\ndata: {}\n\n"
            yield b"event: done\ndata: {}\n\n"

        return StreamingResponse(sse_body(), media_type="text/event-stream")

    async def history(request: Request) -> JSONResponse:
        requests_log.append((request.method, request.url.path))
        return JSONResponse({"records": []})

    async def health(request: Request) -> JSONResponse:
        requests_log.append((request.method, request.url.path))
        return JSONResponse({"status": "ok"})

    async def modifications(request: Request) -> JSONResponse:
        requests_log.append((request.method, request.url.path))
        return JSONResponse({"ok": True})

    async def preview(request: Request) -> JSONResponse:
        requests_log.append((request.method, request.url.path))
        return JSONResponse({"ok": True})

    async def resolve(request: Request) -> JSONResponse:
        requests_log.append((request.method, request.url.path))
        return JSONResponse({"ok": True})

    async def plan_core(request: Request) -> JSONResponse:
        requests_log.append((request.method, request.url.path))
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/api/generate", generate_dynamic, methods=["GET", "POST"]),
            Route("/api/generate/", generate_dynamic, methods=["GET", "POST"]),
            Route("/api/history", history, methods=["GET"]),
            Route("/api/history/{rest:path}", history, methods=["GET"]),
            Route("/health", health, methods=["GET"]),
            Route(
                "/api/generation-records/{id}/modifications",
                modifications,
                methods=["POST"],
            ),
            Route("/api/generate/preview", preview, methods=["POST"]),
            Route("/api/generate/resolve", resolve, methods=["POST"]),
            Route("/api/plan-core-questions", plan_core, methods=["POST"]),
            Route("/api/schemas", lambda r: JSONResponse({}), methods=["GET"]),
            Route(
                "/api/generation-logs/{id}/exchanges",
                lambda r: JSONResponse({}),
                methods=["GET"],
            ),
        ]
    )
    # Attach mutable state to the app for test access
    app.state.release_event = None  # type: ignore[attr-defined]  # threading.Event | None
    app.state.generation_counter = generation_counter  # type: ignore[attr-defined]
    app.state.requests_log = requests_log  # type: ignore[attr-defined]

    return app


# ---------------------------------------------------------------------------
# Server fixture helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _TestServer:
    """Runs a Starlette ASGI app under uvicorn in a daemon thread."""

    def __init__(self, app, *, port: int | None = None):
        self.app = app  # expose the app for test access
        self.port = port or _free_port()
        self.config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="warning"
        )
        self.server = uvicorn.Server(self.config)
        self._thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Server did not start in time")
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_backend_app():
    return _make_fake_backend()


@pytest.fixture
def backend_server(fake_backend_app):
    srv = _TestServer(fake_backend_app)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def gateway_server(backend_server, tmp_path):
    from gateway.app import create_app

    app = create_app(
        backend_url=backend_server.base_url,
        state_dir=tmp_path / "gate",
        control_token="secret",
    )
    srv = _TestServer(app)
    srv.start()
    yield srv, tmp_path / "gate"
    srv.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_a_fresh_state_dir_returns_503(gateway_server):
    """(a) fresh state dir -> GET /api/generate via gateway is 503, exact strings."""
    srv, state_dir = gateway_server
    # State dir is NOT pre-initialised — fail closed by default
    r = httpx.get(f"{srv.base_url}/api/generate", headers={"Accept": "text/event-stream"})
    assert r.status_code == 503
    body = r.json()
    assert isinstance(body["detail"], str), "detail must be a plain string"
    assert body["detail"] == "目前暫停受理新的出題請求，請稍後再試。"
    assert body["code"] == "GENERATION_ADMISSION_PAUSED"
    assert "Retry-After" in r.headers


def test_b_multi_entry_rejection_while_paused(gateway_server, backend_server):
    """(b) old-tab GET and direct POST /api/generate both 503 while paused, zero backend hits."""
    srv, state_dir = gateway_server
    bapp = backend_server.app  # type: ignore[attr-defined]

    # old-tab shaped request
    r1 = httpx.get(
        f"{srv.base_url}/api/generate",
        headers={"Accept": "text/event-stream", "X-Legacy": "1"},
        params={"q": "test"},
    )
    assert r1.status_code == 503

    # direct POST
    r2 = httpx.post(f"{srv.base_url}/api/generate", json={})
    assert r2.status_code == 503

    # no generation requests reached the backend
    gen_reqs = [
        (m, p) for m, p in bapp.state.requests_log
        if p in ("/api/generate", "/api/generate/")
    ]
    assert gen_reqs == []


def test_c_passthrough_while_paused(gateway_server, backend_server):
    """(c) passthrough while paused: every inventory path reaches the fake backend."""
    from tests.gateway.test_admission import PASSTHROUGH_PATHS

    srv, state_dir = gateway_server
    bapp = backend_server.app  # type: ignore[attr-defined]

    passthrough_hits_before = len(bapp.state.requests_log)

    client = httpx.Client(base_url=srv.base_url)
    for path in PASSTHROUGH_PATHS:
        if path.startswith("/api/generate/"):
            r = client.post(path, json={})
        elif path.startswith("/api/generation-records/"):
            r = client.post(path, json={})
        elif path.startswith("/api/generation-logs/"):
            r = client.get(path)
        elif path.startswith("/auth/"):
            # auth routes may not exist in fake backend — just try
            try:
                client.get(path)
            except Exception:
                pass
            continue
        else:
            r = client.get(path)
        # Should NOT be 503 (the generation block code)
        assert r.status_code != 503, f"Path {path} got 503 unexpectedly"

    # Some passthrough paths hit the backend
    new_hits = bapp.state.requests_log[passthrough_hits_before:]
    # At least health and history should have been proxied
    hit_paths = {p for _, p in new_hits}
    assert "/health" in hit_paths or "/api/history" in hit_paths or len(new_hits) > 0


def test_d_open_proxied_no_buffering(backend_server, tmp_path):
    """(d) open -> GET /api/generate proxied and first SSE event arrives before release."""
    from gateway.app import create_app
    from gateway.state import open_gate

    state_dir = tmp_path / "gate"
    open_gate(state_dir)

    bapp = backend_server.app  # type: ignore[attr-defined]
    # Use a threading.Event to block the backend after the first SSE chunk
    release = threading.Event()
    bapp.state.release_event = release

    app = create_app(
        backend_url=backend_server.base_url,
        state_dir=state_dir,
        control_token=None,
    )
    gw = _TestServer(app)
    gw.start()
    try:
        events = []
        with httpx.stream("GET", f"{gw.base_url}/api/generate") as resp:
            assert resp.status_code == 200
            for chunk in resp.iter_lines():
                if chunk.startswith("event:"):
                    events.append(chunk)
                    if "started" in chunk:
                        # First event received before release — success
                        break
        assert any("started" in e for e in events), f"expected 'started' event, got {events}"
    finally:
        # Release the backend so it can finish
        release.set()
        gw.stop()


def test_e_established_stream_survives_pause(backend_server, tmp_path):
    """(e) established stream survives pause; new request -> 503; backend gen counter == 1."""
    from gateway.app import create_app
    from gateway.state import open_gate, pause

    state_dir = tmp_path / "gate"
    open_gate(state_dir)

    bapp = backend_server.app  # type: ignore[attr-defined]

    # Use threading.Event to control backend stream release from test thread
    release = threading.Event()
    bapp.state.release_event = release

    app = create_app(
        backend_url=backend_server.base_url,
        state_dir=state_dir,
        control_token=None,
    )
    gw = _TestServer(app)
    gw.start()

    try:
        received_events = []
        error_holder = []

        def stream_in_thread():
            try:
                with httpx.stream("GET", f"{gw.base_url}/api/generate") as resp:
                    for line in resp.iter_lines():
                        received_events.append(line)
                        # Keep iterating — collect all events including result and done
            except Exception as exc:
                error_holder.append(exc)

        st = threading.Thread(target=stream_in_thread, daemon=True)
        st.start()

        # Wait until 'started' is received
        deadline = time.monotonic() + 5
        while not any("started" in e for e in received_events):
            if time.monotonic() > deadline:
                raise AssertionError("Never received started event")
            time.sleep(0.05)

        # Pause — new generation should now be 503
        pause(state_dir)
        r = httpx.get(f"{gw.base_url}/api/generate")
        assert r.status_code == 503, f"Expected 503 after pause, got {r.status_code}"

        # Release the backend — original stream should complete
        release.set()

        st.join(timeout=5)
        assert not error_holder, f"Stream thread errored: {error_holder}"
        all_events = " ".join(received_events)
        assert "result" in all_events, f"Expected result event, got: {received_events}"
        assert "done" in all_events, f"Expected done event, got: {received_events}"

        # Only one generation request hit backend
        gen_count = bapp.state.generation_counter[0]
        assert gen_count == 1, f"Expected 1 backend generation, got {gen_count}"
    finally:
        gw.stop()


def test_f_restart_survival(backend_server, tmp_path):
    """(f) pause, stop gateway, start new gateway on same state dir -> still 503."""
    from gateway.app import create_app
    from gateway.state import pause

    state_dir = tmp_path / "gate"
    pause(state_dir, reason="before restart")

    port = _free_port()

    app1 = create_app(
        backend_url=backend_server.base_url,
        state_dir=state_dir,
        control_token=None,
    )
    gw1 = _TestServer(app1, port=port)
    gw1.start()

    r = httpx.get(f"http://127.0.0.1:{port}/api/generate")
    assert r.status_code == 503
    gw1.stop()

    # Wait for port to be released
    time.sleep(0.2)
    port2 = _free_port()

    app2 = create_app(
        backend_url=backend_server.base_url,
        state_dir=state_dir,
        control_token=None,
    )
    gw2 = _TestServer(app2, port=port2)
    gw2.start()
    try:
        r2 = httpx.get(f"http://127.0.0.1:{port2}/api/generate")
        assert r2.status_code == 503, f"Expected 503 after restart, got {r2.status_code}"
        body = r2.json()
        assert body["reason"] == "before restart"
    finally:
        gw2.stop()


def test_g_control_endpoint(backend_server, tmp_path):
    """(g) no token -> 404; wrong token -> 403; correct token can open/pause/health."""
    from gateway.app import create_app

    state_dir = tmp_path / "gate"

    # No token configured -> 404
    app_no_token = create_app(
        backend_url=backend_server.base_url,
        state_dir=state_dir,
        control_token=None,
    )
    gw_no_token = _TestServer(app_no_token)
    gw_no_token.start()
    try:
        r = httpx.post(
            f"{gw_no_token.base_url}/gateway/admission",
            json={"state": "open"},
        )
        assert r.status_code == 404
    finally:
        gw_no_token.stop()

    # With token configured
    app = create_app(
        backend_url=backend_server.base_url,
        state_dir=state_dir,
        control_token="mytoken",
    )
    gw = _TestServer(app)
    gw.start()
    try:
        # Wrong token -> 403
        r = httpx.post(
            f"{gw.base_url}/gateway/admission",
            json={"state": "open"},
            headers={"X-Gateway-Control-Token": "wrongtoken"},
        )
        assert r.status_code == 403

        # Missing token -> 403
        r = httpx.post(f"{gw.base_url}/gateway/admission", json={"state": "open"})
        assert r.status_code == 403

        # Correct token can open
        r = httpx.post(
            f"{gw.base_url}/gateway/admission",
            json={"state": "open"},
            headers={"X-Gateway-Control-Token": "mytoken"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "open"

        # Health reflects open
        r = httpx.get(f"{gw.base_url}/gateway/health")
        assert r.status_code == 200
        health = r.json()
        assert health["admission"] == "open"

        # Correct token can pause with reason
        r = httpx.post(
            f"{gw.base_url}/gateway/admission",
            json={"state": "paused", "reason": "maintenance"},
            headers={"X-Gateway-Control-Token": "mytoken"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "paused"
        assert body["reason"] == "maintenance"

        # Health reflects paused
        r = httpx.get(f"{gw.base_url}/gateway/health")
        health = r.json()
        assert health["admission"] == "paused"
        assert health["reason"] == "maintenance"
    finally:
        gw.stop()


def test_h_backend_down_returns_502(tmp_path):
    """(h) backend down -> 502 with string detail."""
    from gateway.app import create_app
    from gateway.state import open_gate

    state_dir = tmp_path / "gate"
    open_gate(state_dir)

    # Use a port that is not listening
    app = create_app(
        backend_url="http://127.0.0.1:19999",
        state_dir=state_dir,
        control_token=None,
    )
    gw = _TestServer(app)
    gw.start()
    try:
        r = httpx.get(f"{gw.base_url}/health", timeout=5)
        assert r.status_code == 502
        body = r.json()
        assert isinstance(body["detail"], str), "detail must be a plain string"
    finally:
        gw.stop()
