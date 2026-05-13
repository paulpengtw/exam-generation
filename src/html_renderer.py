"""Playwright-based HTML-to-PNG renderer for exam question images."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class PlaywrightRenderer:
    """Manages Playwright browser lifecycle for HTML-to-PNG rendering.

    Usage:
        with PlaywrightRenderer() as renderer:
            path = renderer.render(html_string, output_path)

    The browser is started once and reused across multiple render() calls,
    avoiding per-question startup latency (~1-2s).

    All Playwright calls are dispatched to a dedicated single-worker thread so
    that the sync API never encounters a running asyncio event loop (which would
    cause a crash when start() is called from a FastAPI lifespan coroutine).
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._started = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")

    def _start_impl(self) -> None:
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()

    def start(self) -> None:
        """Launch the Playwright Chromium browser in a dedicated worker thread."""
        self._executor.submit(self._start_impl).result()
        self._started = True

    def _stop_impl(self) -> None:
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def stop(self) -> None:
        """Close the browser and stop Playwright. Idempotent."""
        if not self._started:
            return
        self._executor.submit(self._stop_impl).result()
        self._executor.shutdown(wait=True)
        self._started = False

    def _render_impl(self, html: str, output_path: Path, width: int) -> str:
        page = self._browser.new_page(viewport={"width": width, "height": 600})
        try:
            page.set_content(html, wait_until="networkidle")
            content_height = page.evaluate("document.body.scrollHeight")
            page.set_viewport_size({"width": width, "height": max(content_height, 100)})
            page.screenshot(path=str(output_path), full_page=True)
        finally:
            page.close()
        return str(output_path)

    def render(self, html: str, output_path: str | Path, width: int = 800) -> str:
        """Render an HTML string to a PNG file.

        Auto-sizes the viewport height to fit the full content.
        Returns the output path as a string.
        """
        return self._executor.submit(self._render_impl, html, Path(output_path), width).result()

    def __enter__(self) -> PlaywrightRenderer:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()
