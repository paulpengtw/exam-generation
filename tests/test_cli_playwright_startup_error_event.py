"""Playwright startup failure in the math CLI emits an error stage event (issue #257 slice 2b)."""

from __future__ import annotations

import pytest

from src.cli import _start_html_renderer
from src.html_renderer import PlaywrightRenderer


class _FakeClient:
    """Minimal stand-in with a capturing observer."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def get_observer(self):
        return self.events.append


def test_playwright_startup_failure_emits_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(self) -> None:
        raise RuntimeError("no display found")

    monkeypatch.setattr(PlaywrightRenderer, "start", _fail)

    client = _FakeClient()
    result = _start_html_renderer(client)

    assert result is None
    assert len(client.events) == 1
    event = client.events[0]
    assert event["type"] == "stage"
    assert event["agent"] == "image_agent"
    assert event["stage"] == "renderer_startup"
    assert event["status"] == "error"
    assert "no display found" in event["message"]


def test_playwright_startup_success_emits_no_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Playwright starts fine, no error event is emitted."""
    started = [False]

    def _fake_start(self) -> None:
        started[0] = True
        self._started = True

    def _fake_stop(self) -> None:
        pass

    monkeypatch.setattr(PlaywrightRenderer, "start", _fake_start)
    monkeypatch.setattr(PlaywrightRenderer, "stop", _fake_stop)

    client = _FakeClient()
    result = _start_html_renderer(client)

    assert result is not None
    assert client.events == []
    assert started[0] is True


def test_playwright_startup_failure_no_client_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When client is None and Playwright fails, no crash occurs."""

    def _fail(self) -> None:
        raise RuntimeError("no display found")

    monkeypatch.setattr(PlaywrightRenderer, "start", _fail)

    result = _start_html_renderer(None)
    assert result is None
