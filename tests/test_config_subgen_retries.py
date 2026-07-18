"""Tests for Config.subgen_retries env-var wiring (issue #117 remaining scope)."""

from __future__ import annotations

import pytest

from src.config import Config


def test_subgen_retries_dataclass_default() -> None:
    assert Config().subgen_retries == 1


def test_subgen_retries_defaults_to_1_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("SUBGEN_RETRIES", raising=False)
    cfg = Config.from_env()
    assert cfg.subgen_retries == 1


@pytest.mark.parametrize("value,expected", [("0", 0), ("1", 1), ("3", 3)])
def test_subgen_retries_reads_env_var(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("SUBGEN_RETRIES", value)
    cfg = Config.from_env()
    assert cfg.subgen_retries == expected
