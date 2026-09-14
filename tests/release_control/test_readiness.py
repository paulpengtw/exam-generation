"""Tests for the readiness subcommand in scripts/release_control.py (slice 4, task 8.4).

readiness = preflight + compat-check + drain-check combined, returns a
machine-readable summary dict with per-instance status.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import release_control  # noqa: E402

_QUIESCENT_SNAP = {
    "instance_id": "abc",
    "hostname": "host1",
    "pid": 1,
    "started_at": "2026-09-15T00:00:00+00:00",
    "app_version": "v1.0",
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

_BUSY_SNAP = {**_QUIESCENT_SNAP, "active_runs": 2, "quiescent": False}

_INVENTORY_2 = {
    "instances": [
        {"name": "backend-1", "url": "http://backend1", "token_env": "DRAIN_TOKEN_1"},
        {"name": "backend-2", "url": "http://backend2", "token_env": "DRAIN_TOKEN_2"},
    ],
    "gateway": {"url": "http://gateway", "token_env": "GATEWAY_CONTROL_TOKEN"},
}


def _write_inventory(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "inventory.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# (a) readiness: all instances healthy → exit 0, all fields present
# ---------------------------------------------------------------------------


def test_readiness_all_healthy(tmp_path, monkeypatch):
    """readiness exits 0 and prints JSON with per-instance status when all healthy."""
    inv_path = _write_inventory(tmp_path, _INVENTORY_2)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("DRAIN_TOKEN_2", "tok2")

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _QUIESCENT_SNAP

    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(
            ["readiness", "--inventory", str(inv_path), "--require-version", "1"]
        )
    assert rc == 0


def test_readiness_one_unhealthy(tmp_path, monkeypatch):
    """readiness exits non-zero when one instance is unreachable."""
    inv_path = _write_inventory(tmp_path, _INVENTORY_2)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("DRAIN_TOKEN_2", "tok2")

    import httpx

    call_count = [0]

    def fake_get(url, **kwargs):
        call_count[0] += 1
        if "backend1" in url:
            raise httpx.ConnectError("refused")
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = _QUIESCENT_SNAP
        return m

    with patch("release_control.httpx.get", fake_get):
        rc = release_control.main(
            ["readiness", "--inventory", str(inv_path), "--require-version", "1"]
        )
    assert rc != 0


def test_readiness_version_mismatch(tmp_path, monkeypatch):
    """readiness exits non-zero when required version is absent from any instance."""
    inv_path = _write_inventory(tmp_path, _INVENTORY_2)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("DRAIN_TOKEN_2", "tok2")

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _QUIESCENT_SNAP  # has [1]

    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(
            ["readiness", "--inventory", str(inv_path), "--require-version", "2"]
        )
    assert rc != 0
