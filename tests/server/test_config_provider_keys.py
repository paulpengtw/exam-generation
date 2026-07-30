"""Tests for ServerConfig.from_env() provider-key forwarding (issue #337)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from server.config import ServerConfig


def _base_env() -> dict[str, str]:
    return {"LLM_API_KEY": "x", "JWT_SECRET": "s"}


def test_server_from_env_reads_gemini_api_key(tmp_path: Path) -> None:
    env = {**_base_env(), "GEMINI_API_KEY": "gemini-secret"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.gemini_api_key == "gemini-secret"


def test_server_from_env_reads_gemini_base_url(tmp_path: Path) -> None:
    env = {**_base_env(), "GEMINI_BASE_URL": "https://custom.gemini.api/v1beta/openai/"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.gemini_base_url == "https://custom.gemini.api/v1beta/openai/"


def test_server_from_env_reads_openai_api_key(tmp_path: Path) -> None:
    env = {**_base_env(), "OPENAI_API_KEY": "openai-secret"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.openai_api_key == "openai-secret"


def test_server_from_env_reads_openai_base_url(tmp_path: Path) -> None:
    env = {**_base_env(), "OPENAI_BASE_URL": "https://custom.openai.api/v1"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.openai_base_url == "https://custom.openai.api/v1"


def test_server_from_env_defaults_when_unset(tmp_path: Path) -> None:
    env = _base_env()
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.gemini_api_key == ""
    assert cfg.gemini_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert cfg.openai_api_key == ""
    assert cfg.openai_base_url == "https://api.openai.com/v1"
