"""Tests for ServerConfig effort fields and _EFFORT_LEVELS roster (issue #254)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from server.config import ServerConfig, _EFFORT_LEVELS


# ---------------------------------------------------------------------------
# 1. _EFFORT_LEVELS module-level constant
# ---------------------------------------------------------------------------


def test_effort_levels_contains_five_models() -> None:
    assert "claude-opus-5" in _EFFORT_LEVELS
    assert "claude-fable-5" in _EFFORT_LEVELS
    assert "claude-sonnet-5" in _EFFORT_LEVELS
    assert "claude-sonnet-4-6" in _EFFORT_LEVELS
    assert "claude-opus-4-6" in _EFFORT_LEVELS


def test_effort_levels_opus5_has_xhigh() -> None:
    assert "xhigh" in _EFFORT_LEVELS["claude-opus-5"]
    assert "max" in _EFFORT_LEVELS["claude-opus-5"]


def test_effort_levels_fable5_has_xhigh() -> None:
    assert "xhigh" in _EFFORT_LEVELS["claude-fable-5"]
    assert "max" in _EFFORT_LEVELS["claude-fable-5"]


def test_effort_levels_sonnet5_has_xhigh() -> None:
    assert "xhigh" in _EFFORT_LEVELS["claude-sonnet-5"]
    assert "max" in _EFFORT_LEVELS["claude-sonnet-5"]


def test_effort_levels_sonnet4_6_no_xhigh() -> None:
    levels = _EFFORT_LEVELS["claude-sonnet-4-6"]
    assert "xhigh" not in levels
    assert "max" in levels
    assert set(levels) == {"low", "medium", "high", "max"}


def test_effort_levels_opus4_6_no_xhigh() -> None:
    levels = _EFFORT_LEVELS["claude-opus-4-6"]
    assert "xhigh" not in levels
    assert "max" in levels
    assert set(levels) == {"low", "medium", "high", "max"}


def test_effort_levels_five_model_roster_all_have_low_medium_high() -> None:
    for model, levels in _EFFORT_LEVELS.items():
        assert "low" in levels, f"{model} missing 'low'"
        assert "medium" in levels, f"{model} missing 'medium'"
        assert "high" in levels, f"{model} missing 'high'"


# ---------------------------------------------------------------------------
# 2. ServerConfig defaults
# ---------------------------------------------------------------------------


def test_server_config_effort_plan_default_is_medium() -> None:
    cfg = ServerConfig(api_key="x", jwt_secret="s")
    assert cfg.effort_plan == "medium"


def test_server_config_effort_execute_default_is_medium() -> None:
    cfg = ServerConfig(api_key="x", jwt_secret="s")
    assert cfg.effort_execute == "medium"


# ---------------------------------------------------------------------------
# 3. ServerConfig.from_env() env parsing
# ---------------------------------------------------------------------------


def test_server_config_effort_plan_from_env(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s", "LLM_EFFORT_PLAN": "high"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.effort_plan == "high"


def test_server_config_effort_execute_from_env(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s", "LLM_EFFORT_EXECUTE": "low"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.effort_execute == "low"


def test_server_config_effort_both_from_env(tmp_path: Path) -> None:
    env = {
        "LLM_API_KEY": "x",
        "JWT_SECRET": "s",
        "LLM_EFFORT_PLAN": "xhigh",
        "LLM_EFFORT_EXECUTE": "max",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.effort_plan == "xhigh"
    assert cfg.effort_execute == "max"


def test_server_config_effort_unset_gives_medium(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.effort_plan == "medium"
    assert cfg.effort_execute == "medium"
