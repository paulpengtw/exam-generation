"""Tests for PlaywrightRenderer startup-failure cleanup (issue #657).

All tests drive the public interface only: start(), stop(), render(), and the
context manager.  No private attributes are asserted; OS-level process and
thread state are the observable side-effects.
"""

from __future__ import annotations

import glob
import os
import signal
import threading
import time
from pathlib import Path

import pytest

from src.html_renderer import PlaywrightRenderer

# ─── /proc helpers (no psutil) ──────────────────────────────────────────────

def _has_ancestor(pid: int, target: int) -> bool:
    """Return True if *target* is somewhere in *pid*'s parent chain."""
    current = pid
    visited: set[int] = set()
    while current > 1:
        if current in visited:
            break
        visited.add(current)
        try:
            with open(f"/proc/{current}/status") as fh:
                ppid = 0
                for line in fh:
                    if line.startswith("PPid:"):
                        ppid = int(line.split()[1])
                        break
        except (FileNotFoundError, ProcessLookupError, OSError):
            break
        if ppid == target:
            return True
        current = ppid
    return False


def _my_run_driver_pids() -> list[int]:
    """PIDs of playwright run-driver processes descended from this test process."""
    my_pid = os.getpid()
    result: list[int] = []
    for cmdline_path in glob.glob("/proc/*/cmdline"):
        try:
            pid = int(cmdline_path.split("/")[2])
            with open(cmdline_path, "rb") as fh:
                cmdline = fh.read().replace(b"\x00", b" ").decode(errors="replace")
            if "playwright/driver" in cmdline and "run-driver" in cmdline:
                if _has_ancestor(pid, my_pid):
                    result.append(pid)
        except (ValueError, FileNotFoundError, PermissionError, OSError):
            pass
    return result


def _wait_for_driver_count(expected: int, timeout: float = 5.0) -> list[int]:
    """Poll until count equals *expected* or timeout; return final list."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = _my_run_driver_pids()
        if len(pids) == expected:
            return pids
        time.sleep(0.1)
    return _my_run_driver_pids()


@pytest.fixture(autouse=True)
def _kill_leaked_drivers():
    """Ensure run-driver processes spawned in the test are cleaned up on failure."""
    before = set(_my_run_driver_pids())
    yield
    after = set(_my_run_driver_pids())
    for pid in after - before:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


# ─── Slice 1: regression – failed launch leaves no driver process ─────────


def test_failed_launch_leaves_no_driver_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force chromium.launch to fail; assert start() re-raises and zero drivers survive."""
    from playwright.sync_api._generated import BrowserType

    launch_error = RuntimeError("launch failed")

    def _fail_launch(self, **kwargs):  # noqa: ANN001
        raise launch_error

    monkeypatch.setattr(BrowserType, "launch", _fail_launch)

    baseline_count = len(_my_run_driver_pids())

    r = PlaywrightRenderer()
    with pytest.raises(RuntimeError) as exc_info:
        r.start()

    assert exc_info.value is launch_error, "start() must re-raise the exact exception"

    remaining = _wait_for_driver_count(baseline_count)
    assert len(remaining) == baseline_count, (
        f"Expected {baseline_count} run-driver proc(s), got {len(remaining)}: {remaining}"
    )


def test_context_manager_failed_launch_leaves_no_driver_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Context manager: failed launch re-raises and leaves no driver processes."""
    from playwright.sync_api._generated import BrowserType

    launch_error = RuntimeError("launch failed ctx")

    def _fail_launch(self, **kwargs):  # noqa: ANN001
        raise launch_error

    monkeypatch.setattr(BrowserType, "launch", _fail_launch)

    baseline_count = len(_my_run_driver_pids())

    with pytest.raises(RuntimeError) as exc_info:
        with PlaywrightRenderer():
            pass  # __enter__ calls start(), which should raise

    assert exc_info.value is launch_error

    remaining = _wait_for_driver_count(baseline_count)
    assert len(remaining) == baseline_count


# ─── Slice 2: stop() resource-driven, idempotent, safe ──────────────────


def test_stop_after_failed_start_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """After a failed start(), explicit stop() is safe and a no-op."""
    from playwright.sync_api._generated import BrowserType

    def _fail_launch(self, **kwargs):  # noqa: ANN001
        raise RuntimeError("fail")

    monkeypatch.setattr(BrowserType, "launch", _fail_launch)

    r = PlaywrightRenderer()
    with pytest.raises(RuntimeError):
        r.start()

    r.stop()  # Must not raise.


def test_stop_is_idempotent_after_success() -> None:
    """Calling stop() twice after a successful start is safe."""
    r = PlaywrightRenderer()
    r.start()
    r.stop()
    r.stop()  # Second call must not raise.


def test_stop_on_never_started_is_safe() -> None:
    """stop() on a fresh, never-started renderer is safe."""
    r = PlaywrightRenderer()
    r.stop()  # Must not raise.


# ─── Slice 3: cleanup error must not mask original exception ─────────────


def test_playwright_stop_error_does_not_mask_launch_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If playwright.stop() raises during failure cleanup, caller sees original exception."""
    from playwright.sync_api._generated import BrowserType, Playwright

    launch_error = RuntimeError("original launch failure")
    cleanup_error = RuntimeError("cleanup exploded")

    def _fail_launch(self, **kwargs):  # noqa: ANN001
        raise launch_error

    def _fail_stop(self) -> None:  # noqa: ANN001
        raise cleanup_error

    monkeypatch.setattr(BrowserType, "launch", _fail_launch)
    monkeypatch.setattr(Playwright, "stop", _fail_stop)

    r = PlaywrightRenderer()
    with pytest.raises(RuntimeError) as exc_info:
        r.start()

    assert exc_info.value is launch_error, (
        "Caller must see the original launch exception, not the cleanup error"
    )


# ─── Slice 4: executor thread is shut down on the failure path ───────────


def test_executor_thread_gone_after_failed_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """After a failed start(), no playwright-prefixed thread remains alive."""
    from playwright.sync_api._generated import BrowserType

    def _fail_launch(self, **kwargs):  # noqa: ANN001
        raise RuntimeError("fail")

    monkeypatch.setattr(BrowserType, "launch", _fail_launch)

    r = PlaywrightRenderer()
    with pytest.raises(RuntimeError):
        r.start()

    # Poll briefly for any playwright-named threads to terminate.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        pw_threads = [t for t in threading.enumerate() if t.name.startswith("playwright")]
        if not pw_threads:
            break
        time.sleep(0.05)

    pw_threads = [t for t in threading.enumerate() if t.name.startswith("playwright")]
    assert pw_threads == [], f"Playwright threads still alive: {[t.name for t in pw_threads]}"


# ─── Slice 5: control – successful round-trip ───────────────────────────


def test_successful_start_render_stop(tmp_path: Path) -> None:
    """Happy-path: start, render trivial HTML to PNG, stop."""
    html = "<html><body><p>hello</p></body></html>"
    out = tmp_path / "out.png"

    with PlaywrightRenderer() as renderer:
        result = renderer.render(html, out)

    assert Path(result).exists(), "render() should produce a PNG file"
    assert Path(result).stat().st_size > 0, "Output file should be non-empty"
