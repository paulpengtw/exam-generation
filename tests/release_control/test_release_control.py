"""Tests for scripts/release_control.py (slice 3, task 8.3).

These tests exercise the CLI subcommands against a local fake inventory
(in-process HTTP stubs via httpretty / responses), so no real backend is
required.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts/ to path so we can import release_control
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import httpx  # noqa: E402  (after sys.path patch)
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

    mock_get = MagicMock(side_effect=httpx.ConnectError("refused"))
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

    mock_post = MagicMock(side_effect=httpx.ConnectError("refused"))
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
    """reopen exits 0: drain-check passes, no compat version required, gateway opens."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("GATEWAY_CONTROL_TOKEN", "gw-tok")

    import datetime as _dtt
    fresh_snap = {
        **_QUIESCENT_SNAP,
        "captured_at": _dtt.datetime.now(_dtt.timezone.utc).isoformat(),
    }

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = fresh_snap

    mock_post = MagicMock()
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"state": "open"}

    with patch("release_control.httpx.get", mock_get), \
         patch("release_control.httpx.post", mock_post):
        rc = release_control.main(
            ["reopen", "--inventory", str(inv_path), "--max-age-seconds", "60"]
        )
    assert rc == 0
    # gateway was opened
    open_calls = [
        c for c in mock_post.call_args_list
        if (c.kwargs.get("json") or {}).get("state") == "open"
    ]
    assert len(open_calls) == 1


def test_reopen_gateway_fail(tmp_path, monkeypatch):
    """reopen exits non-zero when gateway open call is unreachable."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("GATEWAY_CONTROL_TOKEN", "gw-tok")

    fresh_snap = {
        **_QUIESCENT_SNAP,
        "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = fresh_snap

    mock_post = MagicMock(side_effect=httpx.ConnectError("refused"))
    with patch("release_control.httpx.get", mock_get), \
         patch("release_control.httpx.post", mock_post):
        rc = release_control.main(
            ["reopen", "--inventory", str(inv_path), "--max-age-seconds", "60"]
        )
    assert rc != 0


# ===========================================================================
# Fix 1 evidence rules (task 8.3) — additional tests
# ===========================================================================


def _fresh_snap(**overrides) -> dict:
    """A snapshot with a very recent captured_at (always fresh)."""
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    base = {**_QUIESCENT_SNAP, "captured_at": now}
    return {**base, **overrides}


def _stale_snap(**overrides) -> dict:
    """A snapshot with a captured_at 60 seconds in the past (always stale)."""
    past = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=60)).isoformat()
    base = {**_QUIESCENT_SNAP, "captured_at": past}
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# Stale snapshot → fail
# ---------------------------------------------------------------------------


def test_preflight_stale_snapshot_fails(tmp_path, monkeypatch):
    """preflight fails when a snapshot is older than --max-age-seconds."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _stale_snap()

    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(
            ["preflight", "--inventory", str(inv_path), "--max-age-seconds", "15"]
        )
    assert rc != 0, "preflight must fail on a stale snapshot"


# ---------------------------------------------------------------------------
# Duplicate identity → fail even when both are quiescent
# ---------------------------------------------------------------------------


def test_drain_check_duplicate_identity_fails(tmp_path, monkeypatch):
    """drain-check fails when two inventory entries return the same instance_id."""
    inv = {
        "instances": [
            {"name": "backend-1", "url": "http://backend1", "token_env": "DRAIN_TOKEN_1"},
            {"name": "backend-2", "url": "http://backend2", "token_env": "DRAIN_TOKEN_2"},
        ],
        "gateway": _INVENTORY["gateway"],
    }
    inv_path = _write_inventory(tmp_path, inv)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("DRAIN_TOKEN_2", "tok2")

    shared_id_snap = _fresh_snap(instance_id="SAME-ID", quiescent=True)

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = shared_id_snap

    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(
            ["drain-check", "--inventory", str(inv_path), "--timeout", "5",
             "--max-age-seconds", "15"]
        )
    assert rc != 0, (
        "drain-check must fail when two inventory entries share the same instance_id"
    )


# ---------------------------------------------------------------------------
# 404 instance → 'uninstrumented' label
# ---------------------------------------------------------------------------


def test_preflight_404_is_uninstrumented(tmp_path, monkeypatch, capsys):
    """preflight labels a 404 response as 'uninstrumented' and fails."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")

    mock_get = MagicMock()
    mock_get.return_value.status_code = 404
    mock_get.return_value.json.return_value = {"detail": "Not found"}

    with patch("release_control.httpx.get", mock_get):
        rc = release_control.main(["preflight", "--inventory", str(inv_path)])
    assert rc != 0, "preflight must fail when an instance returns 404"
    captured = capsys.readouterr()
    assert "uninstrumented" in (captured.out + captured.err).lower(), (
        "output must contain 'uninstrumented' for a 404 response"
    )


# ---------------------------------------------------------------------------
# drain-check timeout → exit 3, gateway never asked to open
# ---------------------------------------------------------------------------


def test_drain_check_timeout_exits_3(tmp_path, monkeypatch):
    """drain-check exits 3 on timeout (not 2) so callers can distinguish."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _fresh_snap(active_runs=1, quiescent=False)

    with patch("release_control.httpx.get", mock_get), \
         patch("release_control.time.sleep"):
        rc = release_control.main(
            ["drain-check", "--inventory", str(inv_path), "--timeout", "1",
             "--max-age-seconds", "30"]
        )
    assert rc == 3, f"drain-check timeout must exit 3, got {rc}"


def test_pause_and_drain_timeout_never_opens_gateway(tmp_path, monkeypatch):
    """pause-and-drain never calls open on the gateway after a drain timeout."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("GATEWAY_CONTROL_TOKEN", "gw-tok")

    pause_resp = MagicMock()
    pause_resp.status_code = 200
    pause_resp.json.return_value = {"state": "paused"}

    mock_post = MagicMock(return_value=pause_resp)

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = _fresh_snap(active_runs=1, quiescent=False)

    with patch("release_control.httpx.post", mock_post), \
         patch("release_control.httpx.get", mock_get), \
         patch("release_control.time.sleep"):
        rc = release_control.main(
            ["pause-and-drain", "--inventory", str(inv_path), "--timeout", "1",
             "--max-age-seconds", "30"]
        )
    assert rc == 3, f"pause-and-drain on drain timeout must exit 3, got {rc}"
    # Confirm gateway was ONLY asked to pause, never to open
    open_calls = [
        c for c in mock_post.call_args_list
        if (c.kwargs.get("json") or {}).get("state") == "open"
    ]
    assert len(open_calls) == 0, (
        f"gateway was asked to open after a drain timeout: {open_calls}"
    )


# ---------------------------------------------------------------------------
# reopen after a compat mismatch leaves the gateway paused
# ---------------------------------------------------------------------------


def test_reopen_after_compat_mismatch_stays_paused(tmp_path, monkeypatch):
    """reopen fails without opening the gateway when compat-check fails."""
    inv_path = _write_inventory(tmp_path, _INVENTORY)
    monkeypatch.setenv("DRAIN_TOKEN_1", "tok1")
    monkeypatch.setenv("GATEWAY_CONTROL_TOKEN", "gw-tok")

    # drain endpoint returns quiescent but version 1 only, require version 2
    snap = _fresh_snap(supported_stream_versions=[1])

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = snap

    mock_post = MagicMock()

    with patch("release_control.httpx.get", mock_get), \
         patch("release_control.httpx.post", mock_post):
        rc = release_control.main(
            ["reopen", "--inventory", str(inv_path), "--require-version", "2",
             "--max-age-seconds", "30"]
        )
    assert rc != 0, "reopen must fail when compat-check fails"
    # Gateway must NOT have been asked to open
    open_calls_post = [
        c for c in mock_post.call_args_list
        if (c.kwargs.get("json") or {}).get("state") == "open"
    ]
    assert len(open_calls_post) == 0, (
        f"gateway was asked to open despite compat mismatch: {open_calls_post}"
    )
