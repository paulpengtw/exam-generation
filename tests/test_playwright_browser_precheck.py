"""TDD tests for the playwright_browser pytest plugin (issue #658).

Each slice uses pytester (subprocess mode) to run a tiny inner session that
collects a mix of ``requires_browser`` and unmarked tests, then asserts on the
outcome counts and terminal output.

Slice 1 — browser missing      → marked tests SKIP, unmarked passes, cause once.
Slice 2 — browser present      → marked tests run and pass, no skip, no cause.
Slice 3 — no marked collected  → probe does not run, no skip, no install text.
Slice 4 — present but unusable → marked tests SKIP, cause appears once.

Note on pytester HOME isolation
--------------------------------
``pytester.runpytest_subprocess`` sets HOME to the pytester basetemp so that
the subprocess does not read the developer's ``~/.pytest.ini``.  Playwright
derives its default browser cache from HOME, so slices that need a working
browser must set ``PLAYWRIGHT_BROWSERS_PATH`` explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Enable pytester for this module.
pytest_plugins = ["pytester"]

# Project root — the inner conftest inserts it into sys.path so that
# "tests.plugins.playwright_browser" is importable inside the subprocess.
_PROJECT_ROOT = str(Path(__file__).parent.parent)

# Real browser cache: HOME=/home/claude so the browsers live here.  The
# explicit path is required because pytester sets HOME to a temp directory,
# breaking Playwright's default HOME-relative lookup.
_REAL_BROWSERS_PATH = str(Path.home() / ".cache" / "ms-playwright")

_INNER_CONFTEST = f"""
import sys
sys.path.insert(0, {_PROJECT_ROOT!r})
pytest_plugins = ["tests.plugins.playwright_browser"]
"""

# The exact command users must run to install the browser.
_INSTALL_CMD = "uv run playwright install chromium"

# Chromium headless shell binary path relative to the browsers root.
_CHROME_REL_PATH = (
    "chromium_headless_shell-1208"
    "/chrome-headless-shell-linux64"
    "/chrome-headless-shell"
)


# ─── helpers ──────────────────────────────────────────────────────────────────


def _output(result) -> str:  # type: ignore[no-untyped-def]
    """Flatten pytester result output lines into a single string."""
    return "\n".join(result.outlines + result.errlines)


def _make_empty_browsers_dir(tmp_path: Path) -> Path:
    """Return a fresh empty directory for PLAYWRIGHT_BROWSERS_PATH."""
    d = tmp_path / "empty_pw"
    d.mkdir()
    return d


def _make_broken_browsers_dir(tmp_path: Path) -> Path:
    """Return a browsers dir whose Chromium binary exists but always exits 127."""
    browsers_dir = tmp_path / "broken_pw"
    binary = browsers_dir / _CHROME_REL_PATH
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 127\n")
    binary.chmod(0o755)
    return browsers_dir


# ─── Slice 1: browser missing ─────────────────────────────────────────────────


def test_missing_browser_skips_marked_and_reports_cause_once(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no browser installed: marked tests SKIP, unmarked passes, cause printed once."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(_make_empty_browsers_dir(tmp_path)))

    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.requires_browser
        def test_needs_browser_1():
            assert True

        @pytest.mark.requires_browser
        def test_needs_browser_2():
            assert True

        def test_no_browser():
            assert 1 + 1 == 2
        """
    )

    result = pytester.runpytest_subprocess("-q")
    result.assert_outcomes(passed=1, skipped=2)

    out = _output(result)
    count = out.count(_INSTALL_CMD)
    assert count == 1, (
        f"Expected {_INSTALL_CMD!r} exactly once in output, got {count} times:\n{out}"
    )


# ─── Slice 2: browser present ─────────────────────────────────────────────────


@pytest.mark.requires_browser  # inner session actually starts a real browser
def test_present_browser_runs_marked_and_no_skip(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With browser installed: marked tests run and pass, no skip, no install message.

    PLAYWRIGHT_BROWSERS_PATH is set explicitly because pytester sets HOME to a
    temp directory, breaking Playwright's default HOME-relative cache lookup.
    """
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", _REAL_BROWSERS_PATH)

    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.requires_browser
        def test_needs_browser():
            from src.html_renderer import PlaywrightRenderer
            r = PlaywrightRenderer()
            r.start()
            r.stop()

        def test_no_browser():
            assert True
        """
    )

    result = pytester.runpytest_subprocess("-q")
    result.assert_outcomes(passed=2)

    out = _output(result)
    assert _INSTALL_CMD not in out, (
        f"Install message should be absent when browser is present:\n{out}"
    )
    assert "SKIPPED" not in out


# ─── Slice 3: no marked tests collected ───────────────────────────────────────


def test_no_marked_tests_probe_does_not_run(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no requires_browser tests: probe is skipped entirely, no skip/install text."""
    # Use empty browsers dir so probe *would* fail if it ran.
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(_make_empty_browsers_dir(tmp_path)))

    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(
        """
        def test_ordinary():
            assert True
        """
    )

    result = pytester.runpytest_subprocess("-q")
    result.assert_outcomes(passed=1)

    out = _output(result)
    assert _INSTALL_CMD not in out, (
        f"Install message should not appear when no marked tests are collected:\n{out}"
    )
    assert "SKIPPED" not in out


# ─── Slice 4: present but unusable ────────────────────────────────────────────


def test_broken_browser_skips_marked_and_reports_cause(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With a broken browser binary: marked tests SKIP and cause appears once."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(_make_broken_browsers_dir(tmp_path)))

    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.requires_browser
        def test_needs_browser():
            assert True

        def test_no_browser():
            assert True
        """
    )

    result = pytester.runpytest_subprocess("-q")
    result.assert_outcomes(passed=1, skipped=1)

    out = _output(result)
    assert _INSTALL_CMD in out, (
        f"Install message should appear even with a broken binary:\n{out}"
    )
    count = out.count(_INSTALL_CMD)
    assert count == 1, (
        f"Expected install message exactly once, got {count} times:\n{out}"
    )
