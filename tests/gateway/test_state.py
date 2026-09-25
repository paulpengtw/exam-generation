"""Persistent state is fail closed, including damaged or inaccessible storage."""

import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import pytest


@pytest.mark.parametrize("directory_exists", [False, True])
def test_missing_state_is_paused(tmp_path, directory_exists):
    from gateway.state import read_state

    state_dir = tmp_path / "gate"
    if directory_exists:
        state_dir.mkdir()
    state = read_state(state_dir)
    assert state.state == "paused"
    assert state.reason == "no admission state recorded"
    assert state.changed_at is None
    assert state.changed_by is None
    assert not (state_dir / "admission.json").exists()


@pytest.mark.parametrize("contents", [b"{broken", b"\xff", b"null", b"[]", b'"open"'])
def test_malformed_state_is_paused(tmp_path, contents):
    from gateway.state import read_state

    (tmp_path / "admission.json").write_bytes(contents)
    state = read_state(tmp_path)
    assert state.state == "paused"
    assert state.reason == "admission state unreadable"


@pytest.mark.parametrize("value", ["unknown", "OPEN", None, 1, [], {}])
def test_unknown_state_is_paused(tmp_path, value):
    from gateway.state import read_state

    (tmp_path / "admission.json").write_text(json.dumps({"state": value}))
    state = read_state(tmp_path)
    assert state.state == "paused"
    assert state.reason == "unknown admission state"


def test_unreadable_state_is_paused(tmp_path, monkeypatch):
    from gateway.state import read_state

    def unreadable(*args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "read_text", unreadable)
    state = read_state(tmp_path)
    assert state.state == "paused"
    assert state.reason == "admission state unreadable"


def test_directory_instead_of_file_is_paused(tmp_path):
    from gateway.state import read_state

    (tmp_path / "admission.json").mkdir()
    assert read_state(tmp_path).state == "paused"
    assert read_state(tmp_path).reason == "admission state unreadable"


def test_invalid_metadata_is_paused(tmp_path):
    from gateway.state import read_state

    (tmp_path / "admission.json").write_text('{"state": "open", "reason": []}')
    assert read_state(tmp_path).state == "paused"


def test_pause_open_round_trip(tmp_path):
    from gateway.state import open_gate, pause, read_state

    state_dir = tmp_path / "new" / "gate"
    paused = pause(state_dir, reason="release preparation", changed_by="operator")
    assert read_state(state_dir) == paused
    assert paused.state == "paused"
    assert paused.reason == "release preparation"
    assert paused.changed_by == "operator"
    assert datetime.fromisoformat(paused.changed_at).utcoffset() == timedelta(0)
    assert json.loads((state_dir / "admission.json").read_text()) == asdict(paused)

    opened = open_gate(state_dir, changed_by="supervisor")
    assert read_state(state_dir) == opened
    assert opened.state == "open"
    assert opened.reason is None
    assert opened.changed_by == "supervisor"
    assert datetime.fromisoformat(opened.changed_at) >= datetime.fromisoformat(paused.changed_at)
    assert pause(state_dir).reason is None
    assert read_state(state_dir).changed_by is None


def test_write_replaces_complete_file_atomically(tmp_path, monkeypatch):
    from gateway.state import open_gate, pause, read_state

    original = pause(tmp_path, reason="before")
    replace = os.replace
    replacements = []

    def observe_replace(source, destination):
        assert Path(source).parent == tmp_path
        assert read_state(tmp_path) == original
        assert json.loads(Path(source).read_text())["state"] == "open"
        replacements.append(destination)
        replace(source, destination)

    monkeypatch.setattr(os, "replace", observe_replace)
    opened = open_gate(tmp_path)
    assert replacements == [tmp_path / "admission.json"]
    assert read_state(tmp_path) == opened
    assert list(tmp_path.iterdir()) == [tmp_path / "admission.json"]


def test_failed_replace_preserves_previous_state(tmp_path, monkeypatch):
    from gateway.state import open_gate, pause, read_state

    original = pause(tmp_path)

    def fail_replace(*args):
        raise OSError("storage unavailable")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="storage unavailable"):
        open_gate(tmp_path)
    assert read_state(tmp_path) == original
    assert list(tmp_path.iterdir()) == [tmp_path / "admission.json"]
