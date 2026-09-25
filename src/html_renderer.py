"""Playwright-based HTML-to-PNG renderer for exam question images."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.common.generation_events import OperationScope


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
        self._executor_alive = True

    def _start_impl(self) -> None:
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch()
        except BaseException:
            # Clean up the driver process we already spawned.  Any error from
            # playwright.stop() is suppressed so the original launch exception
            # propagates unchanged to the caller.
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
            raise

    def start(self) -> None:
        """Launch the Playwright Chromium browser in a dedicated worker thread."""
        try:
            self._executor.submit(self._start_impl).result()
        except BaseException:
            # Shut down the worker thread so it does not outlive this call.
            try:
                self._executor.shutdown(wait=True)
            except Exception:
                pass
            self._executor_alive = False
            raise
        self._started = True

    def _stop_impl(self) -> None:
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def stop(self) -> None:
        """Close the browser and stop Playwright. Idempotent.

        Driven by which resources are actually held (self._playwright /
        self._browser), not by whether startup completed.  Safe to call after a
        failed start(), after a successful stop(), or on a never-started instance.
        """
        has_resources = self._playwright is not None or self._browser is not None
        if has_resources:
            if self._executor_alive:
                self._executor.submit(self._stop_impl).result()
            else:
                # Executor was already shut down (e.g. on a failed start that
                # somehow left resources — shouldn't happen, but be safe).
                self._stop_impl()
        if self._executor_alive:
            self._executor.shutdown(wait=True)
            self._executor_alive = False
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

    def render(
        self,
        html: str,
        output_path: str | Path,
        width: int = 800,
        *,
        scope: OperationScope | None = None,
    ) -> str:
        """Render an HTML string to a PNG file.

        Auto-sizes the viewport height to fit the full content.
        Returns the output path as a string.
        """
        del scope  # ownership is carried by the caller's provider seam
        return self._executor.submit(self._render_impl, html, Path(output_path), width).result()

    def __enter__(self) -> PlaywrightRenderer:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()
