"""Tests for LLM temperature env-config and per-model sampling guard (issue #251)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from src.config import Config
from src.llm_client import LLMClient, _accepts_sampling


# ---------------------------------------------------------------------------
# 1. Config.from_env — temperature parsing
# ---------------------------------------------------------------------------

def test_config_temperature_default_is_none() -> None:
    assert Config().temperature is None


def test_config_temperature_from_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    cfg = Config.from_env()
    assert cfg.temperature is None


def test_config_temperature_from_env_empty_string(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TEMPERATURE", "")
    cfg = Config.from_env()
    assert cfg.temperature is None


def test_config_temperature_from_env_float(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TEMPERATURE", "0.3")
    cfg = Config.from_env()
    assert cfg.temperature == pytest.approx(0.3)


def test_config_temperature_from_env_07(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    cfg = Config.from_env()
    assert cfg.temperature == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# 2. _accepts_sampling helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model", [
    "claude-opus-5",
    "claude-opus-5-20250901",          # dated variant
    "claude-sonnet-5",
    "claude-sonnet-5-20250901",
    "claude-fable-5",
    "claude-fable-5-20250901",
    "claude-opus-4-7",
    "claude-opus-4-7-20250601",        # dated variant, issue spec example
    "claude-opus-4-8",
    "claude-opus-4-8-20250701",
    # issue #340 additions — gemini/openai reasoning models reject sampling
    "gemini-3.1-pro-preview",          # dot separator
    "gpt-5.2",                         # dot separator
    "o3-mini",
    "o4-mini",
    "o1",
])
def test_accepts_sampling_false_for_rejected_models(model: str) -> None:
    assert _accepts_sampling(model) is False


@pytest.mark.parametrize("model", [
    "claude-sonnet-4-6",
    "claude-sonnet-4-6-20250401",
    "claude-opus-4-5",
    "claude-haiku-3-5",
    "gpt-4o",
    # issue #340 additions — these DO accept sampling
    "gemini-2.5-flash",
])
def test_accepts_sampling_true_for_normal_models(model: str) -> None:
    assert _accepts_sampling(model) is True


# ---------------------------------------------------------------------------
# Helpers shared by call-site tests
# ---------------------------------------------------------------------------

class _FakeMessagesAPI:
    """Records calls to .create() — mirrors the pattern in test_llm_client_generate_with_tools.py."""

    def __init__(self, response_text: str = '{"ok": true}') -> None:
        self.calls: list[dict] = []
        self._response_text = response_text

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content_block = SimpleNamespace(text=self._response_text)
        usage = SimpleNamespace(
            input_tokens=1,
            output_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return SimpleNamespace(
            content=[content_block],
            stop_reason="end_turn",
            usage=usage,
        )


def _make_client(temperature: float | None = None, model: str = "claude-sonnet-4-6") -> tuple[LLMClient, _FakeMessagesAPI]:
    """Build a non-streaming LLMClient with temperature config and a recorder."""
    cfg = Config(
        api_key="x",
        llm_stream=False,
        model_execute=model,
        temperature=temperature,
    )
    client = LLMClient(cfg)
    fake = _FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)
    return client, fake


# ---------------------------------------------------------------------------
# 3. _call path (non-streaming): unset temperature → no kwarg
# ---------------------------------------------------------------------------

def test_call_no_temperature_kwarg_when_unset() -> None:
    client, fake = _make_client(temperature=None)
    client.generate("sys", "user", purpose="generate")
    assert len(fake.calls) == 1
    assert "temperature" not in fake.calls[0]


# ---------------------------------------------------------------------------
# 4. _call path: temperature set + model accepts sampling → forwarded
# ---------------------------------------------------------------------------

def test_call_forwards_temperature_when_model_accepts() -> None:
    client, fake = _make_client(temperature=0.7, model="claude-sonnet-4-6")
    client.generate("sys", "user", purpose="generate")
    assert len(fake.calls) == 1
    assert fake.calls[0]["temperature"] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# 5. _call path: temperature set + model rejects sampling → dropped + warning
# ---------------------------------------------------------------------------

def test_call_drops_temperature_and_warns_for_rejecting_model(caplog) -> None:
    client, fake = _make_client(temperature=0.7, model="claude-opus-5")
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate("sys", "user", purpose="generate")
    assert len(fake.calls) == 1
    assert "temperature" not in fake.calls[0]
    assert any("LLM_TEMPERATURE" in r.message or "temperature" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# 6. generate_with_tools: unset temperature → no kwarg
# ---------------------------------------------------------------------------

def test_generate_with_tools_no_temperature_when_unset() -> None:
    client, fake = _make_client(temperature=None)
    client.generate_with_tools("sys", "user", tools=[], purpose="generate")
    assert len(fake.calls) == 1
    assert "temperature" not in fake.calls[0]


# ---------------------------------------------------------------------------
# 7. generate_with_tools: temperature set + model accepts → forwarded
# ---------------------------------------------------------------------------

def test_generate_with_tools_forwards_temperature_when_model_accepts() -> None:
    client, fake = _make_client(temperature=0.7, model="claude-sonnet-4-6")
    client.generate_with_tools("sys", "user", tools=[], purpose="generate")
    assert len(fake.calls) == 1
    assert fake.calls[0]["temperature"] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# 8. generate_with_tools: temperature set + model rejects → dropped + warning
# ---------------------------------------------------------------------------

def test_generate_with_tools_drops_temperature_and_warns(caplog) -> None:
    client, fake = _make_client(temperature=0.7, model="claude-opus-5")
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate_with_tools("sys", "user", tools=[], purpose="generate")
    assert len(fake.calls) == 1
    assert "temperature" not in fake.calls[0]
    assert any("LLM_TEMPERATURE" in r.message or "temperature" in r.message.lower() for r in caplog.records)
