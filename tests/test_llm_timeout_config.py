"""Tests for B1: LLM_TIMEOUT_SECONDS and IMAGE_TIMEOUT_SECONDS (issue #628)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.config import Config
from src.llm_client import LLMClient

# ---------------------------------------------------------------------------
# B1-a: Config.from_env reads LLM_TIMEOUT_SECONDS (default 600)
# ---------------------------------------------------------------------------


def test_config_llm_timeout_seconds_dataclass_default() -> None:
    assert Config().llm_timeout_seconds == 600


def test_config_llm_timeout_seconds_defaults_to_600_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    cfg = Config.from_env()
    assert cfg.llm_timeout_seconds == 600


@pytest.mark.parametrize("value,expected", [("60", 60), ("120", 120), ("0", 0)])
def test_config_llm_timeout_seconds_reads_env_var(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: int
) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", value)
    cfg = Config.from_env()
    assert cfg.llm_timeout_seconds == expected


# ---------------------------------------------------------------------------
# B1-b: Config.from_env reads IMAGE_TIMEOUT_SECONDS (default 300)
# ---------------------------------------------------------------------------


def test_config_image_timeout_seconds_dataclass_default() -> None:
    assert Config().image_timeout_seconds == 300


def test_config_image_timeout_seconds_defaults_to_300_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IMAGE_TIMEOUT_SECONDS", raising=False)
    cfg = Config.from_env()
    assert cfg.image_timeout_seconds == 300


@pytest.mark.parametrize("value,expected", [("30", 30), ("600", 600)])
def test_config_image_timeout_seconds_reads_env_var(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: int
) -> None:
    monkeypatch.setenv("IMAGE_TIMEOUT_SECONDS", value)
    cfg = Config.from_env()
    assert cfg.image_timeout_seconds == expected


# ---------------------------------------------------------------------------
# B1-c: LLMClient passes timeout= to OpenAI(...) in _openai_compat_client
# ---------------------------------------------------------------------------


def test_openai_compat_client_passes_llm_timeout_kwarg(monkeypatch: pytest.MonkeyPatch) -> None:
    """_openai_compat_client must forward config.llm_timeout_seconds as timeout=."""
    captured: list[dict] = []

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.append(dict(kwargs))

    monkeypatch.setattr("src.llm_client.OpenAI", FakeOpenAI)

    cfg = Config(api_key="x", gemini_api_key="g-key", llm_timeout_seconds=42, llm_stream=False)
    client = LLMClient(cfg)
    try:
        client._openai_compat_client("gemini")
    except Exception:
        pass  # Errors are fine; we only care about captured kwargs.

    assert captured, "OpenAI was not constructed"
    assert captured[0].get("timeout") == 42, (
        f"Expected timeout=42 in OpenAI kwargs; got {captured[0]}"
    )


# ---------------------------------------------------------------------------
# B1-d: LLMClient passes timeout= to OpenAI(...) in generate_image
# ---------------------------------------------------------------------------


def test_generate_image_passes_image_timeout_kwarg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """generate_image must forward config.image_timeout_seconds as timeout= to OpenAI(...)."""
    captured: list[dict] = []

    class FakeImages:
        def generate(self, **kwargs: Any) -> Any:
            raise RuntimeError("stop-sentinel")

    class FakeOpenAI:
        images = FakeImages()

        def __init__(self, **kwargs: Any) -> None:
            captured.append(dict(kwargs))

    monkeypatch.setattr("src.llm_client.OpenAI", FakeOpenAI)

    cfg = Config(
        api_key="x",
        image_api_key="img-key",
        image_timeout_seconds=99,
        llm_stream=False,
    )
    client = LLMClient(cfg)
    output = tmp_path / "out.png"
    try:
        client.generate_image("prompt", str(output))
    except Exception:
        pass  # We expect an error; we only care about captured kwargs.

    assert captured, "OpenAI was not constructed for image client"
    assert captured[0].get("timeout") == 99, (
        f"Expected timeout=99 in image OpenAI kwargs; got {captured[0]}"
    )
