"""Tests for LLM effort routing via output_config (issue #254).

Mirrors the pattern from tests/test_llm_temperature.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config import Config
from src.llm_client import LLMClient

# ---------------------------------------------------------------------------
# 1. Config defaults and env parsing
# ---------------------------------------------------------------------------


def test_config_effort_plan_default_is_high() -> None:
    assert Config().effort_plan == "high"


def test_config_effort_execute_default_is_high() -> None:
    assert Config().effort_execute == "high"


def test_config_effort_plan_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_EFFORT_PLAN", "high")
    monkeypatch.delenv("LLM_EFFORT_EXECUTE", raising=False)
    cfg = Config.from_env()
    assert cfg.effort_plan == "high"


def test_config_effort_execute_from_env(monkeypatch) -> None:
    monkeypatch.delenv("LLM_EFFORT_PLAN", raising=False)
    monkeypatch.setenv("LLM_EFFORT_EXECUTE", "low")
    cfg = Config.from_env()
    assert cfg.effort_execute == "low"


def test_config_effort_both_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_EFFORT_PLAN", "xhigh")
    monkeypatch.setenv("LLM_EFFORT_EXECUTE", "max")
    cfg = Config.from_env()
    assert cfg.effort_plan == "xhigh"
    assert cfg.effort_execute == "max"


# ---------------------------------------------------------------------------
# Helpers shared by call-site tests — mirrors test_llm_temperature.py
# ---------------------------------------------------------------------------


class _FakeMessagesAPI:
    """Records calls to .create() without hitting the network."""

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


def _make_client(
    effort_plan: str = "medium",
    effort_execute: str = "medium",
    model: str = "claude-opus-5",
) -> tuple[LLMClient, _FakeMessagesAPI]:
    """Build a non-streaming LLMClient with effort config and a recorder."""
    cfg = Config(
        api_key="x",
        llm_stream=False,
        model_execute=model,
        model_verify="",  # Verify uses the fixture's provider/model.
        model_plan=model,
        effort_plan=effort_plan,
        effort_execute=effort_execute,
        effort_verify="",  # These call-site tests exercise execute-effort inheritance.
    )
    client = LLMClient(cfg)
    fake = _FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)
    return client, fake


# ---------------------------------------------------------------------------
# 2. plan purpose → effort_plan
# ---------------------------------------------------------------------------


def test_plan_purpose_carries_effort_plan() -> None:
    client, fake = _make_client(effort_plan="high", effort_execute="low")
    client.generate("sys", "user", purpose="plan")
    assert len(fake.calls) == 1
    extra_body = fake.calls[0].get("extra_body", {})
    assert extra_body.get("output_config", {}).get("effort") == "high"


def test_plan_purpose_different_from_execute() -> None:
    client, fake = _make_client(effort_plan="xhigh", effort_execute="medium")
    client.plan("sys", "user")
    assert len(fake.calls) == 1
    extra_body = fake.calls[0].get("extra_body", {})
    assert extra_body.get("output_config", {}).get("effort") == "xhigh"


# ---------------------------------------------------------------------------
# 3. generate/verify/correct purposes → effort_execute
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("purpose", ["generate", "verify", "correct", "html_image", "fact_check"])
def test_execute_purposes_carry_effort_execute(purpose: str) -> None:
    client, fake = _make_client(effort_plan="low", effort_execute="high")
    client.generate("sys", "user", purpose=purpose)
    assert len(fake.calls) == 1
    extra_body = fake.calls[0].get("extra_body", {})
    assert extra_body.get("output_config", {}).get("effort") == "high"


def test_sub_generator_purpose_carries_effort_execute() -> None:
    """sub_generator#1 style purpose → effort_execute."""
    client, fake = _make_client(effort_plan="low", effort_execute="max")
    client.generate("sys", "user", purpose="sub_generator#1")
    assert len(fake.calls) == 1
    extra_body = fake.calls[0].get("extra_body", {})
    assert extra_body.get("output_config", {}).get("effort") == "max"


# ---------------------------------------------------------------------------
# 4. generate_with_tools: effort passes through
# ---------------------------------------------------------------------------


def test_generate_with_tools_carries_effort_execute() -> None:
    client, fake = _make_client(effort_plan="low", effort_execute="high")
    client.generate_with_tools("sys", "user", tools=[], purpose="fact_check")
    assert len(fake.calls) >= 1
    extra_body = fake.calls[0].get("extra_body", {})
    assert extra_body.get("output_config", {}).get("effort") == "high"


# ---------------------------------------------------------------------------
# 5. Default medium effort always present in extra_body
# ---------------------------------------------------------------------------


def test_default_medium_effort_always_in_extra_body() -> None:
    """Even with default 'medium' effort, extra_body must be present."""
    client, fake = _make_client()  # both default to "medium"
    client.generate("sys", "user", purpose="generate")
    assert len(fake.calls) == 1
    extra_body = fake.calls[0].get("extra_body", {})
    assert extra_body.get("output_config", {}).get("effort") == "medium"


# ---------------------------------------------------------------------------
# 6. Real planning purposes → effort_plan on Anthropic (issue #346)
#
# Callers in src/common/planner.py call client.plan(..., purpose="plan_core_questions")
# and client.plan(..., purpose="plan_context_angles") — these are the purpose
# strings real planners send.  Both must select the plan effort tier, not the
# execute tier.  Fixed by widening _effort_kwargs to check purpose in _PLAN_PURPOSES.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("purpose", ["plan_core_questions", "plan_context_angles"])
def test_real_plan_purposes_carry_effort_plan_anthropic(purpose: str) -> None:
    """plan_core_questions / plan_context_angles → effort_plan tier (Anthropic).

    Real planning callers (src/common/planner.py) send these purpose strings;
    the Anthropic extra_body effort must reflect effort_plan, not effort_execute.
    """
    client, fake = _make_client(effort_plan="high", effort_execute="low")
    client.generate("sys", "user", purpose=purpose)
    assert len(fake.calls) == 1
    extra_body = fake.calls[0].get("extra_body", {})
    assert extra_body.get("output_config", {}).get("effort") == "high"


# ---------------------------------------------------------------------------
# 7. Real planning purposes → effort_plan on Gemini (issue #346)
#
# Same requirement on the OpenAI-compat (Gemini) provider.  For low/medium/high
# effort values the provider uses reasoning_effort; real planning purposes must
# select the plan tier so reasoning_effort reflects effort_plan, not effort_execute.
# ---------------------------------------------------------------------------


class _FakeGeminiCompletions:
    """Records chat.completions.create() calls without hitting the network."""

    def __init__(self, content: str = '{"ok": true}') -> None:
        self.calls: list[dict] = []
        self._content = content

    def create(self, **kwargs):
        self.calls.append(kwargs)
        msg = SimpleNamespace(content=self._content)
        choice = SimpleNamespace(message=msg)
        usage = SimpleNamespace(
            prompt_tokens=1,
            completion_tokens=1,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )
        return SimpleNamespace(choices=[choice], usage=usage)


def _make_gemini_effort_client(
    effort_plan: str = "medium",
    effort_execute: str = "medium",
    model: str = "gemini-3.1-pro-preview",
) -> tuple[LLMClient, _FakeGeminiCompletions]:
    """Build a non-streaming Gemini LLMClient with separate plan/execute effort config."""
    cfg = Config(
        api_key="x",
        gemini_api_key="g-key",
        llm_stream=False,
        model_execute=model,
        model_plan=model,
        effort_plan=effort_plan,
        effort_execute=effort_execute,
    )
    client = LLMClient(cfg)
    fake = _FakeGeminiCompletions()
    client._compat_clients["gemini"] = SimpleNamespace(
        chat=SimpleNamespace(completions=fake)
    )
    return client, fake


@pytest.mark.parametrize("purpose", ["plan_core_questions", "plan_context_angles"])
def test_real_plan_purposes_carry_effort_plan_gemini(purpose: str) -> None:
    """plan_core_questions / plan_context_angles → effort_plan tier (Gemini).

    Real planning callers (src/common/planner.py) send these purpose strings;
    the Gemini reasoning_effort must reflect effort_plan, not effort_execute.
    """
    client, fake = _make_gemini_effort_client(effort_plan="high", effort_execute="low")
    client.generate("sys", "user", purpose=purpose)
    assert len(fake.calls) == 1
    assert fake.calls[0].get("reasoning_effort") == "high"


# ---------------------------------------------------------------------------
# 8. Events from real planning purposes carry agent == "planner" (issue #346)
#
# _PURPOSE_TO_AGENT maps both "plan_core_questions" and "plan_context_angles"
# to "planner" so that observer events emitted by these real planning callers
# (src/common/planner.py) carry the canonical planner agent id, not the raw
# purpose string.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("purpose", ["plan_core_questions", "plan_context_angles"])
def test_real_plan_purposes_emit_planner_agent_in_request_event(purpose: str) -> None:
    """llm_request event for real plan purposes must have agent == 'planner'.

    Both plan_core_questions and plan_context_angles are real planning callers
    (src/common/planner.py); their observer events must identify the agent as
    "planner", not expose the raw purpose string.
    """
    client, _fake = _make_client(effort_plan="high", effort_execute="low")
    events: list[dict] = []
    client.set_observer(events.append)
    client.generate("sys", "user", purpose=purpose)

    request_events = [e for e in events if e["type"] == "llm_request"]
    assert len(request_events) == 1
    assert request_events[0]["agent"] == "planner"
