"""Multi-process rehearsal test for drain + release_control (slice 4, task 8.4).

Spins up two real FastAPI server processes in-process using httpx's AsyncClient
and ASGITransport, simulating a two-backend release rehearsal.  This tests the
end-to-end drain snapshot → release_control.readiness flow without any real
network sockets.

The test is synchronous-friendly because all DrainTelemetry operations are
thread-safe and snapshot() is synchronous.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import release_control  # noqa: E402

from server.generate.drain import DrainTelemetry

# ---------------------------------------------------------------------------
# Helpers: in-process fake drain servers
# ---------------------------------------------------------------------------


def _make_drain_snapshot(drain: DrainTelemetry) -> dict:
    """Return snapshot from a DrainTelemetry object."""
    return drain.snapshot()


class _FakeInstance:
    """Simulates one backend instance with a DrainTelemetry."""

    def __init__(self, name: str, token: str) -> None:
        self.name = name
        self.token = token
        self.drain = DrainTelemetry()
        self._url = f"http://{name}"  # fake URL

    @property
    def inventory_entry(self) -> dict:
        return {
            "name": self.name,
            "url": self._url,
            "token_env": f"TOKEN_{self.name.upper().replace('-', '_')}",
        }

    def mock_get(self, url: str, **kwargs) -> MagicMock:
        """Return a fake httpx response for GET /internal/drain."""
        resp = MagicMock()
        if f"{self._url}/internal/drain" == url:
            provided = kwargs.get("headers", {}).get("X-Drain-Token", "")
            if provided != self.token:
                resp.status_code = 403
                resp.json.return_value = {"detail": "Forbidden"}
            else:
                resp.status_code = 200
                resp.json.return_value = _make_drain_snapshot(self.drain)
        else:
            resp.status_code = 404
            resp.json.return_value = {"detail": "Not Found"}
        return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_two_backends_both_idle(tmp_path, monkeypatch):
    """readiness exits 0 when two backends are both idle and quiescent."""
    inst1 = _FakeInstance("backend-1", "tok1")
    inst2 = _FakeInstance("backend-2", "tok2")
    monkeypatch.setenv("TOKEN_BACKEND_1", "tok1")
    monkeypatch.setenv("TOKEN_BACKEND_2", "tok2")

    inventory = {
        "instances": [inst1.inventory_entry, inst2.inventory_entry],
        "gateway": {"url": "http://gateway", "token_env": "GATEWAY_CONTROL_TOKEN"},
    }
    inv_path = tmp_path / "inventory.json"
    inv_path.write_text(json.dumps(inventory))

    def fake_get(url, **kwargs):
        if "backend-1" in url:
            return inst1.mock_get(url, **kwargs)
        return inst2.mock_get(url, **kwargs)

    with patch("release_control.httpx.get", fake_get):
        rc = release_control.main(
            ["readiness", "--inventory", str(inv_path), "--require-version", "1",
             "--max-age-seconds", "3600"]
        )
    assert rc == 0


def test_two_backends_one_busy_then_drained(tmp_path, monkeypatch):
    """drain-check exits 0 only after the active run counter drains to zero."""
    inst1 = _FakeInstance("backend-1", "tok1")
    inst2 = _FakeInstance("backend-2", "tok2")
    monkeypatch.setenv("TOKEN_BACKEND_1", "tok1")
    monkeypatch.setenv("TOKEN_BACKEND_2", "tok2")

    # Start inst1 with an active run
    inst1.drain._inc("_active_runs")
    assert not inst1.drain.snapshot()["quiescent"]

    inventory = {
        "instances": [inst1.inventory_entry, inst2.inventory_entry],
        "gateway": {"url": "http://gateway", "token_env": "GATEWAY_CONTROL_TOKEN"},
    }
    inv_path = tmp_path / "inventory.json"
    inv_path.write_text(json.dumps(inventory))

    # Schedule decrement after 0.3 seconds
    def drain_after_delay():
        import time
        time.sleep(0.3)
        inst1.drain._dec("_active_runs")

    t = threading.Thread(target=drain_after_delay, daemon=True)
    t.start()

    call_count = [0]

    def fake_get(url, **kwargs):
        call_count[0] += 1
        if "backend-1" in url:
            return inst1.mock_get(url, **kwargs)
        return inst2.mock_get(url, **kwargs)

    with patch("release_control.httpx.get", fake_get), \
         patch("release_control.time.sleep", lambda s: None):  # fast poll
        rc = release_control.main(
            ["drain-check", "--inventory", str(inv_path),
             "--timeout", "5", "--poll-interval", "0.1",
             "--max-age-seconds", "3600"]
        )
    t.join(timeout=2)
    assert rc == 0
    # Should have polled more than once (inst1 was busy on first call)
    assert call_count[0] >= 2


def test_two_backends_counter_never_goes_negative(tmp_path, monkeypatch):
    """Drain counters must not go negative after a dec-without-inc."""
    drain = DrainTelemetry()
    # Over-decrement should not make counters negative
    drain._inc("_active_runs")
    drain._dec("_active_runs")
    drain._dec("_active_runs")  # extra dec — must clamp or ignore
    snap = drain.snapshot()
    # active_runs must be >= 0
    assert snap["active_runs"] >= 0


# ===========================================================================
# Fix 4 — real multi-process rehearsal (task 8.4)
# ===========================================================================


def _free_port() -> int:
    """Return an available TCP port by binding and releasing."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    """Poll until TCP port is accepting connections or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def test_one_subprocess_one_in_process_drain_check(tmp_path, monkeypatch):
    """One backend in a separate OS process; one in-process.

    Checks:
    - The two instance_ids and pids differ (real separate processes).
    - drain-check while the in-process instance is busy → fails naming it.
    - Release the in-process instance → drain-check passes.
    - subprocess is always terminated in a finally block.
    """
    token = "test-multiprocess-token"
    port = _free_port()
    monkeypatch.setenv("TOKEN_SUBPROCESS", token)
    monkeypatch.setenv("TOKEN_INPROCESS", token)
    monkeypatch.setenv("DRAIN_TELEMETRY_TOKEN", token)

    # ── Start the subprocess backend ────────────────────────────────────────
    env = os.environ.copy()
    env["DRAIN_TELEMETRY_TOKEN"] = token
    proc = subprocess.Popen(
        [
            sys.executable, "-m",
            "tests.release_control._instance_runner",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parents[2]),
    )

    try:
        # Wait for the subprocess to accept connections
        assert _wait_for_port("127.0.0.1", port, timeout=15), (
            f"subprocess backend did not start on port {port} within 15 s; "
            f"stderr: {proc.stderr.read(200) if proc.poll() is not None else '(still running)'}"
        )

        # ── In-process backend ─────────────────────────────────────────────
        in_proc_drain = DrainTelemetry()

        # ── Inventory ──────────────────────────────────────────────────────
        inventory = {
            "instances": [
                {
                    "name": "subprocess-backend",
                    "url": f"http://127.0.0.1:{port}",
                    "token_env": "TOKEN_SUBPROCESS",
                },
                {
                    "name": "inprocess-backend",
                    "url": "http://inprocess-stub",  # served via fake httpx.get
                    "token_env": "TOKEN_INPROCESS",
                },
            ],
            "gateway": {"url": "http://gateway-stub", "token_env": "GATEWAY_CONTROL_TOKEN"},
        }
        inv_path = tmp_path / "inventory.json"
        inv_path.write_text(json.dumps(inventory))

        import httpx as _httpx

        # Save a reference to the REAL httpx.get before any patching so that
        # fake_get can call it without recursion.
        _real_httpx_get = (
            _httpx.get.__wrapped__ if hasattr(_httpx.get, "__wrapped__") else _httpx.get
        )

        def fake_get(url, **kwargs):
            # Real HTTP to the subprocess backend (127.0.0.1)
            if "127.0.0.1" in url:
                return _real_httpx_get(url, **kwargs)
            # In-process stub for the second instance
            resp = MagicMock()
            snap = in_proc_drain.snapshot()
            resp.status_code = 200
            resp.json.return_value = snap
            return resp

        # ── Preflight: both instances must be reachable ────────────────────
        with patch("release_control.httpx.get", fake_get):
            rc_pf = release_control.main(
                ["preflight", "--inventory", str(inv_path), "--max-age-seconds", "30"]
            )
        assert rc_pf == 0, "preflight must pass for subprocess + in-process pair"

        # Verify distinct identity
        import httpx as _hx2
        resp_sub = _hx2.get(
            f"http://127.0.0.1:{port}/internal/drain",
            headers={"X-Drain-Token": token},
            timeout=5,
        )
        assert resp_sub.status_code == 200
        sub_snap = resp_sub.json()
        in_snap = in_proc_drain.snapshot()

        assert sub_snap["instance_id"] != in_snap["instance_id"], (
            "subprocess and in-process instances must have distinct instance_ids"
        )
        assert sub_snap["pid"] != in_snap["pid"], (
            "subprocess and in-process instances must have distinct pids"
        )

        # ── drain-check while in-process is busy → must fail ──────────────
        in_proc_drain._inc("_active_runs")
        assert not in_proc_drain.snapshot()["quiescent"]

        with patch("release_control.httpx.get", fake_get), \
             patch("release_control.time.sleep"):
            rc_dc = release_control.main(
                ["drain-check", "--inventory", str(inv_path),
                 "--timeout", "1", "--max-age-seconds", "30"]
            )
        assert rc_dc != 0, (
            "drain-check must fail while the in-process instance has active_runs > 0"
        )

        # ── Release → drain-check passes ──────────────────────────────────
        in_proc_drain._dec("_active_runs")
        assert in_proc_drain.snapshot()["quiescent"]

        with patch("release_control.httpx.get", fake_get), \
             patch("release_control.time.sleep"):
            rc_dc2 = release_control.main(
                ["drain-check", "--inventory", str(inv_path),
                 "--timeout", "5", "--max-age-seconds", "30"]
            )
        assert rc_dc2 == 0, (
            "drain-check must pass once both instances are quiescent"
        )

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
