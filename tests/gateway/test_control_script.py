"""Slice 4 tests for scripts/admission_gate.py CLI."""

import json
from pathlib import Path


def _run(args: list[str], state_dir: Path | None = None) -> tuple[str, int]:
    """Call the CLI main() and return (stdout_text, exit_code)."""
    import io
    from unittest.mock import patch

    from scripts.admission_gate import main

    buf = io.StringIO()
    actual_args = list(args)
    if state_dir is not None:
        actual_args = ["--state-dir", str(state_dir)] + actual_args

    exit_code = 0
    with patch("sys.stdout", buf):
        try:
            main(actual_args)
        except SystemExit as exc:
            exit_code = int(exc.code) if exc.code is not None else 0

    return buf.getvalue(), exit_code


def test_pause_writes_state_and_prints_json(tmp_path):
    out, code = _run(["pause", "--reason", "maintenance", "--by", "admin"], state_dir=tmp_path)
    assert code == 0
    data = json.loads(out)
    assert data["state"] == "paused"
    assert data["reason"] == "maintenance"
    assert data["changed_by"] == "admin"


def test_open_writes_state_and_prints_json(tmp_path):
    _run(["pause"], state_dir=tmp_path)
    out, code = _run(["open", "--by", "operator"], state_dir=tmp_path)
    assert code == 0
    data = json.loads(out)
    assert data["state"] == "open"
    assert data["changed_by"] == "operator"


def test_status_prints_json(tmp_path):
    _run(["pause", "--reason", "prep"], state_dir=tmp_path)
    out, code = _run(["status"], state_dir=tmp_path)
    assert code == 0
    data = json.loads(out)
    assert data["state"] == "paused"
    assert data["reason"] == "prep"


def test_status_require_paused_exits_0_when_paused(tmp_path):
    _run(["pause"], state_dir=tmp_path)
    _, code = _run(["status", "--require", "PAUSED"], state_dir=tmp_path)
    assert code == 0


def test_status_require_open_exits_3_when_paused(tmp_path):
    _run(["pause"], state_dir=tmp_path)
    _, code = _run(["status", "--require", "OPEN"], state_dir=tmp_path)
    assert code == 3


def test_status_require_open_exits_0_when_open(tmp_path):
    _run(["open"], state_dir=tmp_path)
    _, code = _run(["status", "--require", "OPEN"], state_dir=tmp_path)
    assert code == 0


def test_status_require_paused_exits_3_when_open(tmp_path):
    _run(["open"], state_dir=tmp_path)
    _, code = _run(["status", "--require", "PAUSED"], state_dir=tmp_path)
    assert code == 3


def test_status_fresh_dir_is_paused(tmp_path):
    out, code = _run(["status"], state_dir=tmp_path / "gate")
    assert code == 0
    data = json.loads(out)
    assert data["state"] == "paused"


def test_pause_no_reason_or_by(tmp_path):
    out, code = _run(["pause"], state_dir=tmp_path)
    assert code == 0
    data = json.loads(out)
    assert data["state"] == "paused"
    assert data["reason"] is None
    assert data["changed_by"] is None
