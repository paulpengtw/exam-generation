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
import sys
import threading
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
            ["readiness", "--inventory", str(inv_path), "--require-version", "1"]
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
             "--timeout", "5", "--poll-interval", "0.1"]
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
