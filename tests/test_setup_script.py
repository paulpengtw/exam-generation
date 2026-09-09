"""tests/test_setup_script.py — Contract test for scripts/setup.sh (issue #659).

Verifies, without executing a real `uv sync`, that:
  (a) scripts/setup.sh is executable.
  (b) Running it with `uv` stubbed records
      `sync --all-extras --all-groups` and
      `run playwright install chromium` in that order.
  (c) A second run makes the same two calls (idempotency is delegated to
      Playwright's own cache check; the shim documents that both calls happen
      every time, which is the correct and intentional behaviour).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import textwrap

SCRIPT = pathlib.Path(__file__).parent.parent / "scripts" / "setup.sh"


def _make_uv_shim(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Return (shim_dir, log_file).

    The shim records each invocation as a line in log_file and exits 0.
    """
    log = tmp_path / "uv-calls.log"
    shim = tmp_path / "uv"
    shim.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            echo "$@" >> {log}
            exit 0
            """
        )
    )
    shim.chmod(0o755)
    return tmp_path, log


def _run_setup(
    shim_dir: pathlib.Path, extra_args: list[str] | None = None
) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}"}
    cmd = ["bash", str(SCRIPT)] + (extra_args or [])
    return subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
    )


def _read_log_lines(log: pathlib.Path) -> list[str]:
    return [line.strip() for line in log.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# (a) Executable bit
# ---------------------------------------------------------------------------

def test_setup_script_exists_and_is_executable() -> None:
    assert SCRIPT.exists(), f"scripts/setup.sh not found at {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "scripts/setup.sh is not executable"


# ---------------------------------------------------------------------------
# (b) Two-call sequence: sync → run playwright install chromium
# ---------------------------------------------------------------------------

def test_setup_script_calls_uv_sync_then_playwright_install(tmp_path: pathlib.Path) -> None:
    shim_dir, log = _make_uv_shim(tmp_path)
    result = _run_setup(shim_dir)
    assert result.returncode == 0, (
        f"setup.sh exited {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    lines = _read_log_lines(log)
    assert len(lines) >= 2, f"Expected at least 2 uv calls, got: {lines}"
    assert lines[0] == "sync --all-extras --all-groups", (
        f"First call should be 'sync --all-extras --all-groups', got {lines[0]!r}"
    )
    # The playwright install call may be prefixed with extra flags; the key tokens
    # must appear in the correct positions.
    assert "run" in lines[1], f"Second call should include 'run', got {lines[1]!r}"
    assert "playwright" in lines[1], (
        f"Second call should include 'playwright', got {lines[1]!r}"
    )
    assert "install" in lines[1], (
        f"Second call should include 'install', got {lines[1]!r}"
    )
    assert "chromium" in lines[1], (
        f"Second call should include 'chromium', got {lines[1]!r}"
    )


# ---------------------------------------------------------------------------
# (c) Idempotency: second run makes the same calls
# ---------------------------------------------------------------------------

def test_setup_script_idempotent(tmp_path: pathlib.Path) -> None:
    """A second invocation must make the same uv calls; playwright's cache check
    handles the skip-if-present logic, not this script."""
    shim_dir, log = _make_uv_shim(tmp_path)

    result1 = _run_setup(shim_dir)
    assert result1.returncode == 0, f"First run failed: {result1.stderr}"
    lines_after_first = _read_log_lines(log)

    result2 = _run_setup(shim_dir)
    assert result2.returncode == 0, f"Second run failed: {result2.stderr}"
    lines_after_second = _read_log_lines(log)

    # The second run should append the same pattern as the first.
    new_lines = lines_after_second[len(lines_after_first):]
    assert len(new_lines) >= 2, (
        f"Second run did not produce new uv calls; log after second run: {lines_after_second}"
    )
    assert new_lines[0] == "sync --all-extras --all-groups", (
        f"Second run first call should be 'sync --all-extras --all-groups', "
        f"got {new_lines[0]!r}"
    )
    second_call = new_lines[1]
    assert "playwright" in second_call and "install" in second_call and "chromium" in second_call, (
        f"Second run second call should include playwright install chromium, "
        f"got {second_call!r}"
    )


# ---------------------------------------------------------------------------
# Optional: --web flag also calls npm --prefix web install
# ---------------------------------------------------------------------------

def test_setup_script_web_flag_calls_npm(tmp_path: pathlib.Path) -> None:
    """With --web, npm --prefix web install is also called."""
    shim_dir, log = _make_uv_shim(tmp_path)

    # Also stub npm
    npm_shim = shim_dir / "npm"
    npm_log = tmp_path / "npm-calls.log"
    npm_shim.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            echo "$@" >> {npm_log}
            exit 0
            """
        )
    )
    npm_shim.chmod(0o755)

    result = _run_setup(shim_dir, extra_args=["--web"])
    assert result.returncode == 0, (
        f"setup.sh --web exited {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    assert npm_log.exists(), "npm was not called when --web flag was given"
    npm_lines = _read_log_lines(npm_log)
    assert any(
        "--prefix" in line and "web" in line and "install" in line
        for line in npm_lines
    ), f"Expected 'npm --prefix web install', got: {npm_lines}"
