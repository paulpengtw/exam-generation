"""Tests for observer failure evidence (issue #258 Slice 2)."""
from __future__ import annotations

from types import SimpleNamespace

from src.config import Config
from src.llm_client import LLMClient, emit_stage


def _raising_observer(event: dict) -> None:
    raise RuntimeError("observer boom")


def _make_test_client(observer=None) -> LLMClient:
    """Build an LLMClient without a real network connection."""
    cfg = Config(api_key="test-key")
    client = LLMClient(cfg)
    client.client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: None))
    if observer is not None:
        client.set_observer(observer)
    return client


# ---------------------------------------------------------------------------
# emit_stage tests
# ---------------------------------------------------------------------------

def test_emit_stage_raising_observer_does_not_raise(capsys) -> None:
    """emit_stage must not propagate an observer exception."""
    emit_stage(_raising_observer, "generator", "generate", "started")


def test_emit_stage_first_failure_written_to_stderr(capsys) -> None:
    """The FIRST observer failure must produce a stderr message with the exception text."""
    def boom(event: dict) -> None:
        raise ValueError("sentinel-message-xyz")

    emit_stage(boom, "generator", "generate", "started")

    captured = capsys.readouterr()
    assert "sentinel-message-xyz" in captured.err, (
        f"Expected exception message in stderr, got: {captured.err!r}"
    )


def test_emit_stage_repeated_calls_produce_exactly_one_warning(capsys) -> None:
    """Repeated calls with the SAME raising observer emit only one stderr warning."""
    call_count = 0

    def counting_boom(event: dict) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError(f"boom-call-{call_count}")

    for _ in range(3):
        emit_stage(counting_boom, "generator", "generate", "started")

    captured = capsys.readouterr()
    assert "boom-call-1" in captured.err, "Expected warning for the first failure"
    assert "boom-call-2" not in captured.err, "Second failure should be suppressed"
    assert "boom-call-3" not in captured.err, "Third failure should be suppressed"


# ---------------------------------------------------------------------------
# LLMClient._emit tests
# ---------------------------------------------------------------------------

def test_llm_client_emit_raising_observer_does_not_raise(capsys) -> None:
    """LLMClient._emit must not propagate an observer exception."""
    client = _make_test_client(observer=_raising_observer)
    client._emit({"type": "stage", "agent": "generator", "stage": "x", "status": "started"})


def test_llm_client_emit_first_failure_written_to_stderr(capsys) -> None:
    """The FIRST _emit observer failure must produce a stderr message with exception text."""
    def boom(event: dict) -> None:
        raise ValueError("client-sentinel-abc")

    client = _make_test_client(observer=boom)
    client._emit({"type": "stage", "agent": "generator", "stage": "x", "status": "started"})

    captured = capsys.readouterr()
    assert "client-sentinel-abc" in captured.err, (
        f"Expected exception message in stderr, got: {captured.err!r}"
    )


def test_llm_client_emit_repeated_calls_produce_exactly_one_warning(capsys) -> None:
    """Repeated _emit calls with a raising observer emit at most one stderr warning."""
    boom_count = 0

    def counting_boom(event: dict) -> None:
        nonlocal boom_count
        boom_count += 1
        raise RuntimeError(f"client-boom-{boom_count}")

    client = _make_test_client(observer=counting_boom)

    for _ in range(3):
        client._emit({"type": "stage", "agent": "generator", "stage": "x", "status": "started"})

    captured = capsys.readouterr()
    assert "client-boom-1" in captured.err, "Expected first-failure warning"
    assert "client-boom-2" not in captured.err, "Second failure should be suppressed"
    assert "client-boom-3" not in captured.err, "Third failure should be suppressed"
