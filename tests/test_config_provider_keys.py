"""Tests for Config provider-key fields (issue #337)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from src.config import Config


def test_gemini_api_key_default() -> None:
    assert Config().gemini_api_key == ""


def test_gemini_base_url_default() -> None:
    assert Config().gemini_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_openai_api_key_default() -> None:
    assert Config().openai_api_key == ""


def test_openai_base_url_default() -> None:
    assert Config().openai_base_url == "https://api.openai.com/v1"


def test_from_env_reads_gemini_api_key(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x", "GEMINI_API_KEY": "gemini-secret"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = Config.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.gemini_api_key == "gemini-secret"


def test_from_env_reads_gemini_base_url(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x", "GEMINI_BASE_URL": "https://custom.gemini.api/v1beta/openai/"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = Config.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.gemini_base_url == "https://custom.gemini.api/v1beta/openai/"


def test_from_env_reads_openai_api_key(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x", "OPENAI_API_KEY": "openai-secret"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = Config.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.openai_api_key == "openai-secret"


def test_from_env_reads_openai_base_url(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x", "OPENAI_BASE_URL": "https://custom.openai.api/v1"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = Config.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.openai_base_url == "https://custom.openai.api/v1"


def test_from_env_defaults_when_unset(tmp_path: Path) -> None:
    env = {"LLM_API_KEY": "x"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = Config.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.gemini_api_key == ""
    assert cfg.gemini_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert cfg.openai_api_key == ""
    assert cfg.openai_base_url == "https://api.openai.com/v1"
