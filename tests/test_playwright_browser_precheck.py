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

import os
import sys
from pathlib import Path

import pytest

# Enable pytester for this module.
pytest_plugins = ["pytester"]

# Project root — the inner conftest inserts it into sys.path so that
# "tests.plugins.playwright_browser" is importable inside the subprocess.
_PROJECT_ROOT = str(Path(__file__).parent.parent)


# The developer's real HOME, captured at import time.  Playwright derives its
# browser cache from HOME, and pytester replaces HOME with a temp directory for
# the duration of each test, so the real value must be recorded before any
# pytester fixture runs.
_REAL_HOME = os.environ.get("HOME")


def _browsers_root_and_revision() -> tuple[Path, str]:
    """Registry root and Chromium revision this interpreter's Playwright resolves.

    Asked of Playwright rather than hardcoded: the cache location is
    OS-dependent (``~/.cache/ms-playwright`` on Linux,
    ``~/Library/Caches/ms-playwright`` on macOS, ``%LOCALAPPDATA%`` on
    Windows).  An explicit path is needed at all because pytester sets HOME to
    a temp directory, which breaks Playwright's default HOME-relative lookup —
    so HOME is restored here while Playwright resolves the path.
    """
    from playwright.sync_api import sync_playwright

    swapped = _REAL_HOME is not None and os.environ.get("HOME") != _REAL_HOME
    previous = os.environ.get("HOME")
    if swapped:
        os.environ["HOME"] = _REAL_HOME  # type: ignore[assignment]
    try:
        with sync_playwright() as pw:
            executable = Path(pw.chromium.executable_path)
    finally:
        if swapped:
            if previous is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous

    for ancestor in executable.parents:
        if ancestor.name.startswith("chromium-"):
            return ancestor.parent, ancestor.name.split("-", 1)[1]
    raise AssertionError(
        f"Could not derive the Playwright browsers root from {str(executable)!r}"
    )


def _real_browsers_path() -> str:
    """The browsers root alone, as a string for PLAYWRIGHT_BROWSERS_PATH."""
    return str(_browsers_root_and_revision()[0])


def _headless_shell_relpath() -> Path:
    """Headless-shell binary path relative to the browsers root.

    Globbed from the real installation rather than hardcoded: the revision
    directory (``chromium_headless_shell-<rev>``) tracks the Playwright
    version and the platform directory (``chrome-headless-shell-linux64`` /
    ``-mac-arm64`` / ...) tracks the host OS.  Pinning either one turns the
    "broken browser" slice below into a second "missing browser" slice without
    failing, so it is derived.  The revision is taken from the Chromium build
    Playwright resolves, because the headless shell shares that revision.
    """
    root, revision = _browsers_root_and_revision()
    binary = "chrome-headless-shell.exe" if sys.platform == "win32" else "chrome-headless-shell"
    matches = sorted(root.glob(f"chromium_headless_shell-{revision}/*/{binary}"))
    if not matches:
        raise AssertionError(
            f"No headless-shell binary for revision {revision} under {root}. "
            f"Fix: {_INSTALL_CMD}"
        )
    return matches[0].relative_to(root)

_INNER_CONFTEST = f"""
import sys
sys.path.insert(0, {_PROJECT_ROOT!r})
pytest_plugins = ["tests.plugins.playwright_browser"]
"""

# The exact command users must run to install the browser.
_INSTALL_CMD = "uv run playwright install chromium"


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
    binary = browsers_dir / _headless_shell_relpath()
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
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", _real_browsers_path())

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


@pytest.mark.requires_browser  # needs a real install to learn the platform layout
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
    assert "Executable doesn't exist" not in out, (
        "The fixture must produce a binary Playwright actually tries to run, so this "
        f"slice exercises a *broken* browser rather than a missing one:\n{out}"
    )
    assert _INSTALL_CMD in out, (
        f"Install message should appear even with a broken binary:\n{out}"
    )
    count = out.count(_INSTALL_CMD)
    assert count == 1, (
        f"Expected install message exactly once, got {count} times:\n{out}"
    )
