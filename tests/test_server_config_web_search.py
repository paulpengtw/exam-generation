"""ServerConfig.from_env() must forward WEB_SEARCH_* env vars (issue #104).

Regression test for the finding where ServerConfig.from_env() constructed
`cls(...)` with explicit kwargs but omitted web_search_provider /
web_search_max_uses, silently disabling the fact-check feature for all web
users regardless of env var configuration.
"""

from __future__ import annotations

import pytest

from server.config import ServerConfig


def test_from_env_forwards_web_search_provider_and_max_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "anthropic")
    monkeypatch.setenv("WEB_SEARCH_MAX_USES", "7")

    cfg = ServerConfig.from_env()

    assert cfg.web_search_provider == "anthropic"
    assert cfg.web_search_max_uses == 7


def test_from_env_defaults_web_search_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("WEB_SEARCH_MAX_USES", raising=False)

    cfg = ServerConfig.from_env()

    assert cfg.web_search_provider == "none"
    assert cfg.web_search_max_uses == 5
