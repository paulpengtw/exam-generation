"""Tests for Config.creative_planning env-var wiring (issue #114)."""

from __future__ import annotations

import pytest

from src.config import Config


@pytest.mark.parametrize("value,expected", [
    ("1", True),
    ("true", True),
    ("True", True),
    ("0", False),
    ("false", False),
    ("False", False),
    ("", False),
])
def test_creative_planning_reads_env_var(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("CREATIVE_PLANNING", value)
    cfg = Config.from_env()
    assert cfg.creative_planning is expected


def test_creative_planning_defaults_to_true_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("CREATIVE_PLANNING", raising=False)
    cfg = Config.from_env()
    assert cfg.creative_planning is True


def test_server_config_creative_planning_defaults_to_true() -> None:
    from server.config import ServerConfig
    cfg = ServerConfig(api_key="x")
    assert cfg.creative_planning is True


def test_server_config_creative_planning_reads_env(monkeypatch) -> None:
    from server.config import ServerConfig
    monkeypatch.setenv("CREATIVE_PLANNING", "0")
    cfg = ServerConfig.from_env()
    assert cfg.creative_planning is False
