"""Tests for ServerConfig.llm_models_allowed env plumbing."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from server.config import ServerConfig


def _base_env() -> dict[str, str]:
    return {
        "LLM_API_KEY": "x",
        "JWT_SECRET": "s",
        "LLM_MODEL_PLAN": "claude-opus-4-6",
        "LLM_MODEL_EXECUTE": "claude-sonnet-4-6",
    }


def test_allowlist_unset_falls_back_to_defaults(tmp_path: Path) -> None:
    env = _base_env()
    env.pop("LLM_MODELS_ALLOWED", None)
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.llm_models_allowed == ("claude-opus-4-6", "claude-sonnet-4-6")


def test_allowlist_env_parsed_comma_separated(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "claude-opus-4-6, claude-sonnet-4-6 ,claude-haiku-4-6"
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.llm_models_allowed == (
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-6",
    )


def test_allowlist_dedupe_when_defaults_match_env_entries(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "claude-opus-4-6,claude-opus-4-6,claude-sonnet-4-6"
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.llm_models_allowed == ("claude-opus-4-6", "claude-sonnet-4-6")


def test_allowlist_env_missing_defaults_are_appended(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "claude-haiku-4-6"
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.llm_models_allowed == (
        "claude-haiku-4-6",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
    )


def test_allowlist_empty_string_falls_back_to_defaults(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "   "
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.llm_models_allowed == ("claude-opus-4-6", "claude-sonnet-4-6")
