"""Tests for scripts/release_control.py (slice 3, task 8.3).

These tests exercise the CLI subcommands against a local fake inventory
(in-process HTTP stubs via httpretty / responses), so no real backend is
required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts/ to path so we can import release_control
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import release_control  # noqa: E402  (after sys.path patch)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_QUIESCENT_SNAP = {
    "instance_id": "abc",
    "hostname": "host1",
    "pid": 1,
    "started_at": "2026-09-15T00:00:00+00:00",
    "app_version": None,
    "supported_stream_versions": [1],
    "active_runs": 0,
    "active_workers": 0,
    "open_streams": 0,
    "pending_deliveries": 0,
    "pending_persistence": 0,
    "renderer_leases_held": 0,
    "quiescent": True,
    "captured_at": "2026-09-15T00:00:00+00:00",
}

_BUSY_SNAP = {**_QUIESCENT_SNAP, "active_runs": 1, "quiescent": False}

_INVENTORY = {
    "instances": [
        {"name": "backend-1", "url": "http://backend1", "token_env": "DRAIN_TOKEN_1"},
    ],
    "gateway": {"url": "http://gateway", "token_env": "GATEWAY_CONTROL_TOKEN"},
}


def _write_inventory(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "inventory.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# (a) preflight: all instances reachable → exit 0
# ---------------------------------------------------------------------------


def test_preflight_all_reachable(tmp_path, monkeypatch):
    """preflight exits 0 when all instances respond 200 with a valid snapshot."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _QUIESCENT_SNAP

    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(["preflight", "--inventory", str(inv_path)])
    assert rc == 0


def test_preflight_unreachable_instance(tmp_path, monkeypatch):
    """preflight exits non-zero when an instance is unreachable."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")

    import httpx as req_mod

    mock_get = MagicMock(side_effect=req_mod.ConnectError("refused"))
    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(["preflight", "--inventory", str(inv_path)])
    assert rc != 0


# ---------------------------------------------------------------------------
# (b) drain-check: returns 0 when all quiescent
# ---------------------------------------------------------------------------


def test_drain_check_already_quiescent(tmp_path, monkeypatch):
    """drain-check exits 0 immediately when all instances are already quiescent."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _QUIESCENT_SNAP

    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(
            ["drain-check", "--inventory", str(inv_path), "--timeout", "5"]
        )
    assert rc == 0


def test_drain_check_times_out(tmp_path, monkeypatch):
    """drain-check exits non-zero when not quiescent within timeout."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _BUSY_SNAP

    with patch("release_control.httpx.get", mock_get), \
         patch("release_control.time.sleep"):
        rc = release_control.main(
            ["drain-check", "--inventory", str(inv_path), "--timeout", "1"]
        )
    assert rc != 0


# ---------------------------------------------------------------------------
# (c) pause-and-drain: pauses gateway then polls until quiescent
# ---------------------------------------------------------------------------


def test_pause_and_drain_success(tmp_path, monkeypatch):
    """pause-and-drain exits 0: gateway paused + instances quiescent."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("GATEWAY_CONTROL_TOKEN", "gw-tok")

    mock_post = MagicMock()
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"state": "paused"}

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _QUIESCENT_SNAP

    with patch("release_control.httpx.post", mock_post), \
         patch("release_control.httpx.get", mock_get):
        rc = release_control.main(
            ["pause-and-drain", "--inventory", str(inv_path), "--timeout", "10",
             "--reason", "release test"]
        )
    assert rc == 0
    # gateway pause call was made
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "admission" in str(call_kwargs)


def test_pause_and_drain_gateway_fail(tmp_path, monkeypatch):
    """pause-and-drain exits non-zero if gateway pause call fails."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("GATEWAY_CONTROL_TOKEN", "gw-tok")

    import httpx as req_mod

    mock_post = MagicMock(side_effect=req_mod.ConnectError("refused"))
    with patch("release_control.httpx.post", mock_post):
        rc = release_control.main(
            ["pause-and-drain", "--inventory", str(inv_path), "--timeout", "5"]
        )
    assert rc != 0


# ---------------------------------------------------------------------------
# (d) compat-check: version compatibility gate
# ---------------------------------------------------------------------------


def test_compat_check_pass(tmp_path, monkeypatch):
    """compat-check exits 0 when required version is in supported_stream_versions."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _QUIESCENT_SNAP  # has [1]

    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(
            ["compat-check", "--inventory", str(inv_path), "--require-version", "1"]
        )
    assert rc == 0


def test_compat_check_fail(tmp_path, monkeypatch):
    """compat-check exits non-zero when required version is absent."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")

    snap = {**_QUIESCENT_SNAP, "supported_stream_versions": [1]}
    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = snap

    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(
            ["compat-check", "--inventory", str(inv_path), "--require-version", "2"]
        )
    assert rc != 0


# ---------------------------------------------------------------------------
# (e) reopen: reopens the gateway
# ---------------------------------------------------------------------------


def test_reopen_success(tmp_path, monkeypatch):
    """reopen exits 0 when gateway POST returns open state."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("GATEWAY_CONTROL_TOKEN", "gw-tok")

    mock_post = MagicMock()
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"state": "open"}

    with patch("release_control.httpx.post", mock_post):
        rc = release_control.main(["reopen", "--inventory", str(inv_path)])
    assert rc == 0
    mock_post.assert_called_once()


def test_reopen_gateway_fail(tmp_path, monkeypatch):
    """reopen exits non-zero when gateway is unreachable."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("GATEWAY_CONTROL_TOKEN", "gw-tok")

    import httpx as req_mod

    mock_post = MagicMock(side_effect=req_mod.ConnectError("refused"))
    with patch("release_control.httpx.post", mock_post):
        rc = release_control.main(["reopen", "--inventory", str(inv_path)])
    assert rc != 0
