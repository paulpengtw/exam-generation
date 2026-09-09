"""Pytest plugin: session-level Playwright browser precheck for ``requires_browser`` tests.

If any test marked ``requires_browser`` is collected, a single probe
starts and stops a real :class:`~src.html_renderer.PlaywrightRenderer` before
any test runs.  On failure the probe writes the cause once to the terminal
summary and skips every marked test; unmarked tests continue unaffected.
If no marked tests are collected the probe is skipped entirely.
The probe itself cannot leak a driver process: on a failed start the
:class:`~src.html_renderer.PlaywrightRenderer` cleans up its own resources
(issue #657), so this plugin does nothing extra for that case.
"""

from __future__ import annotations

import pytest

# Module-level state.  In subprocess (pytester) runs each subprocess starts
# fresh; in in-process runs these are reset between tests only via the
# reset helper used by pytester tests.
_BROWSER_SKIP_REASON: str | None = None
_PROBE_DONE: bool = False


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_browser: mark test as requiring a working Playwright Chromium browser",
    )


def pytest_collection_finish(session: pytest.Session) -> None:
    """After collection: probe the browser if any ``requires_browser`` tests are present."""
    global _BROWSER_SKIP_REASON, _PROBE_DONE
    if _PROBE_DONE:
        return
    _PROBE_DONE = True

    marked = [
        item for item in session.items if item.get_closest_marker("requires_browser")
    ]
    if not marked:
        return

    from src.html_renderer import PlaywrightRenderer

    try:
        with PlaywrightRenderer() as renderer:  # noqa: F841 — probe only
            pass
    except Exception as exc:  # noqa: BLE001
        # Build the skip reason including the fix command (appears once total:
        # in the terminal summary).  The skip reason embedded in each skipped
        # test also names the command so developers see it without searching.
        _BROWSER_SKIP_REASON = (
            f"Playwright Chromium browser is not available "
            f"({type(exc).__name__}: {exc}). "
            f"Fix: uv run playwright install chromium"
        )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip ``requires_browser`` tests when the browser probe failed."""
    if _BROWSER_SKIP_REASON and item.get_closest_marker("requires_browser"):
        pytest.skip(_BROWSER_SKIP_REASON)


def pytest_terminal_summary(
    terminalreporter,  # noqa: ANN001
    exitstatus: int,  # noqa: ARG001
    config: pytest.Config,  # noqa: ARG001
) -> None:
    """Write the browser unavailability cause exactly once in the terminal summary.

    The fix command (``uv run playwright install chromium``) is written only
    here — not as a separate extra line — so it appears exactly once in the
    overall output.
    """
    if _BROWSER_SKIP_REASON:
        terminalreporter.write_sep("=", "Playwright browser precheck failure")
        terminalreporter.write_line(
            f"Browser not available: {_BROWSER_SKIP_REASON}",
            red=True,
        )
