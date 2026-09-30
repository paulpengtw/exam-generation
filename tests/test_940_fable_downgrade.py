"""Tests for LLM_FABLE_DOWNGRADE switch (issue #940).

Covers:
1. Config.fable_downgrade parsing
2. Config.dispatch_model
3. Config.dispatch_effort
4. WARNING log on substitution (no prompt content)
5. Switch-off: SDK arguments unchanged for a fable call
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.config import FABLE_DOWNGRADE_TARGET, Config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeMessagesAPI:
    """Minimal fake that records kwargs passed to .create() and .stream()."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"ok": true}')],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )

    @contextmanager
    def stream(self, **kwargs):
        final = self.create(**kwargs)

        class FakeStream:
            def __iter__(self):
                return iter([
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(type="text_delta", text='{"ok": true}'),
                    )
                ])

            def get_final_message(self):
                return final

        yield FakeStream()


def make_llm_client(
    *,
    fable_downgrade: bool = False,
    model_execute: str = "claude-fable-5",
    model_verify: str = "",
    effort_execute: str = "high",
    streaming: bool = False,
) -> tuple:
    """Return (LLMClient, FakeMessagesAPI)."""
    from src.llm_client import LLMClient

    cfg = Config(
        api_key="test-only",
        model_execute=model_execute,
        model_verify=model_verify,
        model_plan=model_execute,
        model_correct="",
        effort_execute=effort_execute,
        effort_verify="",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=streaming,
        fable_downgrade=fable_downgrade,
    )
    client = LLMClient(cfg)
    fake = FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)
    return client, fake


# ---------------------------------------------------------------------------
# 1. Config.fable_downgrade env-var parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    # enabling values
    ("1", True),
    ("true", True),
    ("TRUE", True),
    (" 1 ", True),
    (" true ", True),
    # non-enabling values
    ("0", False),
    ("false", False),
    ("yes", False),
    ("", False),
])
def test_fable_downgrade_env_parsing(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("LLM_FABLE_DOWNGRADE", value)
    cfg = Config.from_env()
    assert cfg.fable_downgrade is expected


def test_fable_downgrade_defaults_off_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("LLM_FABLE_DOWNGRADE", raising=False)
    cfg = Config.from_env()
    assert cfg.fable_downgrade is False


def test_fable_downgrade_field_default() -> None:
    cfg = Config(api_key="x")
    assert cfg.fable_downgrade is False


def test_server_config_inherits_fable_downgrade(monkeypatch) -> None:
    from server.config import ServerConfig
    monkeypatch.setenv("LLM_FABLE_DOWNGRADE", "1")
    cfg = ServerConfig.from_env()
    assert cfg.fable_downgrade is True


# ---------------------------------------------------------------------------
# 2. Config.dispatch_model
# ---------------------------------------------------------------------------

FABLE_IDS = [
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-fable-5-20250901",
]
NON_FABLE_IDS = [
    "claude-opus-5",
    "claude-sonnet-5",
    "gemini-3.1-pro-preview",
    "claude-opus-4-6",
]


@pytest.mark.parametrize("model_id", FABLE_IDS)
def test_dispatch_model_substitutes_fable_when_on(model_id: str) -> None:
    cfg = Config(api_key="x", fable_downgrade=True)
    result = cfg.dispatch_model(model_id)
    assert result == FABLE_DOWNGRADE_TARGET


@pytest.mark.parametrize("model_id", FABLE_IDS)
def test_dispatch_model_leaves_fable_unchanged_when_off(model_id: str) -> None:
    cfg = Config(api_key="x", fable_downgrade=False)
    result = cfg.dispatch_model(model_id)
    assert result == model_id


@pytest.mark.parametrize("model_id", NON_FABLE_IDS)
def test_dispatch_model_leaves_non_fable_unchanged(model_id: str) -> None:
    cfg = Config(api_key="x", fable_downgrade=True)
    result = cfg.dispatch_model(model_id)
    assert result == model_id


# ---------------------------------------------------------------------------
# 3. Config.dispatch_effort — signature: (requested_model, effort)
#
# Rules:
#   - fable_downgrade=True + requested_model contains "fable" + effort NOT in
#     EFFORT_LEVELS[FABLE_DOWNGRADE_TARGET] → return "high"
#   - fable_downgrade=True + requested_model contains "fable" + effort IN
#     EFFORT_LEVELS[FABLE_DOWNGRADE_TARGET] → return effort unchanged
#   - fable_downgrade=True + requested_model does NOT contain "fable" → no clamp
#   - fable_downgrade=False → no clamp regardless of model
#   - effort is None → None returned
# ---------------------------------------------------------------------------


def test_dispatch_effort_clamps_xhigh_when_fable_requested_downgrade_on() -> None:
    """xhigh is clamped to high when fable model is requested with switch on."""
    cfg = Config(api_key="x", fable_downgrade=True)
    assert cfg.dispatch_effort("claude-fable-5", "xhigh") == "high"


@pytest.mark.parametrize("effort", ["low", "medium", "high", "max"])
def test_dispatch_effort_leaves_target_roster_efforts_unchanged_on_substitution(
    effort: str,
) -> None:
    """Efforts that ARE in the target's roster are not clamped on substitution."""
    cfg = Config(api_key="x", fable_downgrade=True)
    assert cfg.dispatch_effort("claude-fable-5", effort) == effort


def test_dispatch_effort_leaves_xhigh_unchanged_for_direct_opus_call() -> None:
    """A direct claude-opus-4-6 call with xhigh must NOT be clamped.

    Clamping is only for substituted (fable → opus) calls.
    """
    cfg = Config(api_key="x", fable_downgrade=True)
    result = cfg.dispatch_effort(FABLE_DOWNGRADE_TARGET, "xhigh")
    assert result == "xhigh"


def test_dispatch_effort_leaves_xhigh_unchanged_when_switch_off() -> None:
    """With switch off, no clamping even if model contains 'fable'."""
    cfg = Config(api_key="x", fable_downgrade=False)
    assert cfg.dispatch_effort("claude-fable-5", "xhigh") == "xhigh"


def test_dispatch_effort_leaves_xhigh_unchanged_for_non_fable_model() -> None:
    """Non-fable model with xhigh is never clamped."""
    cfg = Config(api_key="x", fable_downgrade=True)
    assert cfg.dispatch_effort("claude-opus-5", "xhigh") == "xhigh"


def test_dispatch_effort_none_effort_unchanged() -> None:
    cfg = Config(api_key="x", fable_downgrade=True)
    result = cfg.dispatch_effort("claude-fable-5", None)
    assert result is None


# ---------------------------------------------------------------------------
# 4. WARNING log on substitution — no prompt content
# ---------------------------------------------------------------------------

def test_warning_emitted_on_substitution(caplog) -> None:
    client, fake = make_llm_client(fable_downgrade=True, model_execute="claude-fable-5")
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate("system prompt", "user prompt")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    fable_warnings = [r for r in warnings if "fable_downgrade" in r.message]
    assert len(fable_warnings) >= 1, "Expected at least one fable_downgrade WARNING"
    w = fable_warnings[0]
    assert "claude-fable-5" in w.message
    assert FABLE_DOWNGRADE_TARGET in w.message
    # No prompt content in the log
    assert "system prompt" not in w.message
    assert "user prompt" not in w.message


def test_no_warning_when_switch_off(caplog) -> None:
    client, fake = make_llm_client(fable_downgrade=False, model_execute="claude-fable-5")
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate("system", "user")

    fable_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "fable_downgrade" in r.message
    ]
    assert len(fable_warnings) == 0


# ---------------------------------------------------------------------------
# 5. SDK arguments: substituted call dispatches to claude-opus-4-6
# ---------------------------------------------------------------------------

def test_sdk_receives_opus_model_when_switch_on() -> None:
    client, fake = make_llm_client(fable_downgrade=True, model_execute="claude-fable-5")
    client.generate("system", "user")
    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == FABLE_DOWNGRADE_TARGET


def test_sdk_receives_fable_model_when_switch_off() -> None:
    client, fake = make_llm_client(fable_downgrade=False, model_execute="claude-fable-5")
    client.generate("system", "user")
    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == "claude-fable-5"


def test_substituted_call_gets_opus_thinking_options() -> None:
    """Substituted call should carry claude-opus-4-6 thinking/ceiling options."""
    client, fake = make_llm_client(fable_downgrade=True, model_execute="claude-fable-5")
    client.generate("system", "user")
    call = fake.calls[0]
    # claude-opus-4-6 gets adaptive thinking + 16384 ceiling
    assert call.get("thinking") == {"type": "adaptive"}
    assert call.get("max_tokens") == 16384


def test_xhigh_effort_clamped_to_high_on_substitution() -> None:
    """xhigh effort → high for the substituted opus-4-6 call."""
    client, fake = make_llm_client(
        fable_downgrade=True,
        model_execute="claude-fable-5",
        effort_execute="xhigh",
    )
    client.generate("system", "user")
    call = fake.calls[0]
    effort = call.get("extra_body", {}).get("output_config", {}).get("effort")
    assert effort == "high", f"Expected clamped effort 'high', got {effort!r}"


def test_max_effort_unchanged_on_substitution() -> None:
    """max effort stays max even when substituted."""
    client, fake = make_llm_client(
        fable_downgrade=True,
        model_execute="claude-fable-5",
        effort_execute="max",
    )
    client.generate("system", "user")
    call = fake.calls[0]
    effort = call.get("extra_body", {}).get("output_config", {}).get("effort")
    assert effort == "max"


def test_switch_off_sdk_args_identical_to_baseline() -> None:
    """With switch off, fable call SDK args are unchanged from baseline (no substitution)."""
    client_on, fake_on = make_llm_client(fable_downgrade=False, model_execute="claude-fable-5")
    client_on.generate("system", "user")

    client_off, fake_off = make_llm_client(fable_downgrade=False, model_execute="claude-fable-5")
    client_off.generate("system", "user")

    # Both should have same model
    assert fake_on.calls[0]["model"] == fake_off.calls[0]["model"] == "claude-fable-5"
    # Same options (max_tokens, effort etc)
    assert fake_on.calls[0].get("max_tokens") == fake_off.calls[0].get("max_tokens")


# ---------------------------------------------------------------------------
# 6. generate_with_tools path also applies dispatch
# ---------------------------------------------------------------------------

def test_generate_with_tools_dispatches_to_opus_when_on() -> None:
    """generate_with_tools() must also apply the fable downgrade."""
    from src.llm_client import LLMClient

    TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
    cfg = Config(
        api_key="test-only",
        model_verify="claude-fable-5",
        model_execute="claude-fable-5",
        model_plan="claude-fable-5",
        model_correct="",
        effort_execute="high",
        effort_verify="",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=True,
    )
    client = LLMClient(cfg)
    fake = FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)

    client.generate_with_tools("system", "user", tools=TOOLS, purpose="fact_check")
    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == FABLE_DOWNGRADE_TARGET


def test_generate_with_tools_leaves_fable_when_off() -> None:
    from src.llm_client import LLMClient

    TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
    cfg = Config(
        api_key="test-only",
        model_verify="claude-fable-5",
        model_execute="claude-fable-5",
        model_plan="claude-fable-5",
        model_correct="",
        effort_execute="high",
        effort_verify="",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=False,
    )
    client = LLMClient(cfg)
    fake = FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)

    client.generate_with_tools("system", "user", tools=TOOLS, purpose="fact_check")
    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == "claude-fable-5"
