"""Playwright-based HTML-to-PNG renderer for exam question images."""

from __future__ import annotations

from pathlib import Path


class PlaywrightRenderer:
    """Manages Playwright browser lifecycle for HTML-to-PNG rendering.

    Usage:
        with PlaywrightRenderer() as renderer:
            path = renderer.render(html_string, output_path)

    The browser is started once and reused across multiple render() calls,
    avoiding per-question startup latency (~1-2s).
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None

    def start(self) -> None:
        """Launch the Playwright Chromium browser."""
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()

    def stop(self) -> None:
        """Close the browser and stop Playwright."""
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def render(self, html: str, output_path: str | Path, width: int = 800) -> str:
        """Render an HTML string to a PNG file.

        Auto-sizes the viewport height to fit the full content.
        Returns the output path as a string.
        """
        output_path = Path(output_path)
        page = self._browser.new_page(viewport={"width": width, "height": 600})
        try:
            page.set_content(html, wait_until="networkidle")
            content_height = page.evaluate("document.body.scrollHeight")
            page.set_viewport_size({"width": width, "height": max(content_height, 100)})
            page.screenshot(path=str(output_path), full_page=True)
        finally:
            page.close()
        return str(output_path)

    def __enter__(self) -> PlaywrightRenderer:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()
