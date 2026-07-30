"""Tests for ServerConfig.llm_models_allowed env plumbing."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from server.config import ServerConfig, _DEFAULT_MODELS_ALLOWED


def _base_env() -> dict[str, str]:
    return {
        "LLM_API_KEY": "x",
        "JWT_SECRET": "s",
        "LLM_MODEL_PLAN": "claude-opus-5",
        "LLM_MODEL_EXECUTE": "claude-sonnet-4-6",
    }


def test_allowlist_unset_falls_back_to_defaults(tmp_path: Path) -> None:
    env = _base_env()
    env.pop("LLM_MODELS_ALLOWED", None)
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    # When LLM_MODELS_ALLOWED is unset, the built-in roster is used.
    # plan (claude-opus-5) and execute (claude-sonnet-4-6) are already in it.
    assert cfg.llm_models_allowed == _DEFAULT_MODELS_ALLOWED


def test_allowlist_env_parsed_comma_separated(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "claude-opus-4-6, claude-sonnet-4-6 ,claude-haiku-4-6"
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    # plan (claude-opus-5) not in explicit list → appended at the end.
    assert cfg.llm_models_allowed == (
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-6",
        "claude-opus-5",
    )


def test_allowlist_dedupe_when_defaults_match_env_entries(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "claude-opus-4-6,claude-opus-4-6,claude-sonnet-4-6"
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    # Duplicate claude-opus-4-6 collapses; plan (claude-opus-5) is appended.
    assert cfg.llm_models_allowed == (
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-opus-5",
    )


def test_allowlist_env_missing_defaults_are_appended(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "claude-haiku-4-6"
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    # Neither plan (claude-opus-5) nor execute (claude-sonnet-4-6) is in the
    # explicit list → both are appended in plan-first order.
    assert cfg.llm_models_allowed == (
        "claude-haiku-4-6",
        "claude-opus-5",
        "claude-sonnet-4-6",
    )


def test_allowlist_empty_string_falls_back_to_defaults(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "   "
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    # Whitespace-only env var is treated as unset → built-in roster.
    assert cfg.llm_models_allowed == _DEFAULT_MODELS_ALLOWED


def test_fresh_env_config_has_six_model_roster_and_gemini_default(tmp_path: Path) -> None:
    """With no LLM_MODELS_ALLOWED set, from_env() returns the built-in 6-model
    roster and the new plan default (gemini-3.1-pro-preview)."""
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.model_plan == "gemini-3.1-pro-preview"
    assert cfg.model_execute == "gemini-3.1-pro-preview"
    assert cfg.llm_models_allowed == _DEFAULT_MODELS_ALLOWED
