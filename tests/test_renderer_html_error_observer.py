"""render_image html path propagates failures through on_error (issue #257 slice 2a)."""

from __future__ import annotations

import pathlib

from src.renderer import render_image


class _FakePlaywrightRenderer:
    """Raises RuntimeError on render()."""
    def render(self, html: str, output_path, width: int = 800) -> str:
        raise RuntimeError("Playwright render crash: no display")


def test_html_mode_no_html_calls_on_error(tmp_path: pathlib.Path) -> None:
    """When render_mode='html' and no HTML available (no spec html, no client), on_error fires."""
    errors: list[str] = []
    result = render_image(
        {"render_mode": "html"},
        tmp_path / "out.png",
        html_renderer=None,
        llm_client=None,
        on_error=errors.append,
    )
    assert result is None
    assert len(errors) == 1


def test_html_mode_no_playwright_renderer_calls_on_error(tmp_path: pathlib.Path) -> None:
    """When render_mode='html' with HTML content but no html_renderer, on_error fires."""
    errors: list[str] = []
    result = render_image(
        {"render_mode": "html", "html": "<html><body>test</body></html>"},
        tmp_path / "out.png",
        html_renderer=None,
        llm_client=None,
        on_error=errors.append,
    )
    assert result is None
    assert len(errors) == 1


def test_html_mode_playwright_exception_calls_on_error(tmp_path: pathlib.Path) -> None:
    """When html_renderer.render() raises, on_error is called with the exception text."""
    errors: list[str] = []
    result = render_image(
        {"render_mode": "html", "html": "<html><body>test</body></html>"},
        tmp_path / "out.png",
        html_renderer=_FakePlaywrightRenderer(),
        llm_client=None,
        on_error=errors.append,
    )
    assert result is None
    assert len(errors) == 1
    assert "Playwright render crash" in errors[0]


def test_html_mode_on_error_none_does_not_crash(tmp_path: pathlib.Path) -> None:
    """When on_error is None and html render fails, no exception escapes."""
    result = render_image(
        {"render_mode": "html"},
        tmp_path / "out.png",
        html_renderer=None,
        llm_client=None,
    )
    assert result is None
