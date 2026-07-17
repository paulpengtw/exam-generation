"""Config surface for the web-search fact-check pass (issue #104)."""

from __future__ import annotations

import pytest

from src.config import Config


def test_defaults_disable_web_search() -> None:
    cfg = Config()
    assert cfg.web_search_provider == "none"
    assert cfg.web_search_max_uses == 5


def test_from_env_reads_web_search_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "anthropic")
    monkeypatch.setenv("WEB_SEARCH_MAX_USES", "7")
    cfg = Config.from_env()
    assert cfg.web_search_provider == "anthropic"
    assert cfg.web_search_max_uses == 7


def test_from_env_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("WEB_SEARCH_MAX_USES", raising=False)
    cfg = Config.from_env()
    assert cfg.web_search_provider == "none"
    assert cfg.web_search_max_uses == 5
