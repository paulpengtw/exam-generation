"""End-to-end tests for Fable → Opus dispatch through the fact-check path (issue #941).

Drives fact_check_question() directly with a real LLMClient whose Anthropic SDK
client is replaced by a fake that captures SDK kwargs.  Verifies that the guard in
generate_with_tools() causes the fact-check call to use claude-opus-4-6 when the
verify tier is a Fable model and the switch is on.

Also verifies the provider gate still evaluates the *requested* model's provider
(Fable → anthropic, gate passes), independent of the downgrade switch.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from src.config import FABLE_DOWNGRADE_TARGET, Config
from src.llm_client import LLMClient
from src.social_studies.fact_check import fact_check_question
from src.social_studies.schemas import (
    ExamQuestion,
    LearningContentRef,
    QuestionMetadata,
    SubQuestion,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeMessages:
    """Records kwargs passed to .create() and returns a scripted JSON response."""

    def __init__(
        self,
        response_json: str = '{"verified": true, "issues": []}',
    ) -> None:
        self._response_json = response_json
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._response_json)],
            stop_reason="end_turn",
        )


def _make_client(
    *,
    fable_downgrade: bool,
    model_verify: str = "claude-fable-5",
    effort_verify: str = "xhigh",
) -> tuple[LLMClient, _FakeMessages]:
    cfg = Config(
        api_key="test-only",
        model_execute="gemini-3.1-pro-preview",  # irrelevant — fact_check uses verify tier
        model_verify=model_verify,
        model_plan="claude-opus-4-6",
        model_correct="",
        effort_execute="high",
        effort_verify=effort_verify,
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=fable_downgrade,
    )
    client = LLMClient(cfg)
    fake = _FakeMessages()
    client.client = SimpleNamespace(messages=fake)
    return client, fake


def _question() -> ExamQuestion:
    """Minimal social-studies question for the fact-check call path."""
    return ExamQuestion(
        id="fc-941-01",
        核心問題="近年來台灣公民社會的發展趨勢為何？",
        文本="測試文本。",
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        題目=["測試題目"],
        正確解題分析=["A"],
        subquestions=[
            SubQuestion(
                id="fc-941-01-sq1",
                序號=1,
                年級=8,
                科目=["公民與社會"],
                核心素養=[],
                學習內容=[LearningContentRef(編碼="公Ba-Ⅳ-3", 說明="")],
                學習表現=[],
                出題概念="",
                題型="選擇題",
                題目="測試",
            )
        ],
        metadata=QuestionMetadata(grade=8, model="fake"),
    )


# ---------------------------------------------------------------------------
# AC1: Switch on + Fable verify + xhigh effort → SDK gets claude-opus-4-6
# ---------------------------------------------------------------------------


def test_fact_check_dispatches_to_opus_when_fable_verify_switch_on() -> None:
    """Switch on + Fable verify model: SDK call uses claude-opus-4-6."""
    client, fake = _make_client(
        fable_downgrade=True,
        model_verify="claude-fable-5",
        effort_verify="xhigh",
    )

    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )

    assert result is not None, "fact_check_question should return a result (not fail-open)"
    assert len(fake.calls) >= 1
    call = fake.calls[0]

    assert call["model"] == FABLE_DOWNGRADE_TARGET, (
        f"Expected SDK model={FABLE_DOWNGRADE_TARGET!r}, got {call['model']!r}"
    )


def test_fact_check_substituted_call_has_opus_thinking_options() -> None:
    """Substituted fact-check call carries claude-opus-4-6 adaptive thinking + max_tokens=16384."""
    client, fake = _make_client(
        fable_downgrade=True,
        model_verify="claude-fable-5",
        effort_verify="xhigh",
    )

    fact_check_question(client, _question(), provider="anthropic", max_uses=5)

    assert fake.calls, "Expected at least one SDK call"
    call = fake.calls[0]
    assert call.get("thinking") == {"type": "adaptive"}, (
        f"Expected adaptive thinking, got: {call.get('thinking')!r}"
    )
    assert call.get("max_tokens") == 16384, (
        f"Expected max_tokens=16384, got: {call.get('max_tokens')!r}"
    )


def test_fact_check_xhigh_effort_clamped_to_high_on_substitution() -> None:
    """xhigh effort is clamped to high when Fable is substituted to opus-4-6."""
    client, fake = _make_client(
        fable_downgrade=True,
        model_verify="claude-fable-5",
        effort_verify="xhigh",
    )

    fact_check_question(client, _question(), provider="anthropic", max_uses=5)

    assert fake.calls
    effort = fake.calls[0].get("extra_body", {}).get("output_config", {}).get("effort")
    assert effort == "high", f"Expected effort='high' (clamped from xhigh), got {effort!r}"


def test_fact_check_web_search_tool_present_on_substituted_call() -> None:
    """The web_search_20250305 tool is present in the substituted fact-check call."""
    client, fake = _make_client(
        fable_downgrade=True,
        model_verify="claude-fable-5",
        effort_verify="xhigh",
    )

    fact_check_question(client, _question(), provider="anthropic", max_uses=7)

    assert fake.calls
    tools = fake.calls[0].get("tools", [])
    web_search_tools = [t for t in tools if t.get("type") == "web_search_20250305"]
    assert web_search_tools, f"Expected web_search_20250305 tool, got: {tools}"
    assert web_search_tools[0].get("max_uses") == 7


# ---------------------------------------------------------------------------
# AC2: One WARNING naming both ids; no prompt content in the WARNING
# ---------------------------------------------------------------------------


def test_fact_check_one_warning_emitted_on_substitution(caplog) -> None:
    """One WARNING per substituted fact-check call naming both requested and dispatched ids."""
    client, _ = _make_client(fable_downgrade=True, model_verify="claude-fable-5")

    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        fact_check_question(client, _question(), provider="anthropic", max_uses=5)

    fable_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "fable_downgrade" in r.message
    ]
    assert len(fable_warnings) >= 1, "Expected at least one fable_downgrade WARNING"
    w = fable_warnings[0]
    assert "claude-fable-5" in w.message
    assert FABLE_DOWNGRADE_TARGET in w.message


def test_fact_check_warning_contains_no_prompt_text(caplog) -> None:
    """The substitution WARNING must not include any system/user prompt content."""
    client, _ = _make_client(fable_downgrade=True, model_verify="claude-fable-5")

    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        fact_check_question(client, _question(), provider="anthropic", max_uses=3)

    for r in caplog.records:
        if r.levelno == logging.WARNING and "fable_downgrade" in r.message:
            # The prompt contains Chinese text from the system/user prompts
            assert "事實查證" not in r.message
            assert "查證員" not in r.message
            assert "近年來" not in r.message


# ---------------------------------------------------------------------------
# AC3: Switch off → fact-check for Fable verify model unchanged
# ---------------------------------------------------------------------------


def test_fact_check_unchanged_when_switch_off() -> None:
    """Switch off: the Fable verify model is sent to the SDK without substitution."""
    client, fake = _make_client(
        fable_downgrade=False,
        model_verify="claude-fable-5",
        effort_verify="high",
    )

    fact_check_question(client, _question(), provider="anthropic", max_uses=5)

    assert fake.calls
    assert fake.calls[0]["model"] == "claude-fable-5", (
        f"Expected Fable model unchanged, got {fake.calls[0]['model']!r}"
    )


def test_no_fable_warning_emitted_when_switch_off(caplog) -> None:
    """No fable_downgrade WARNING when the switch is off."""
    client, _ = _make_client(
        fable_downgrade=False,
        model_verify="claude-fable-5",
    )

    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        fact_check_question(client, _question(), provider="anthropic", max_uses=5)

    fable_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "fable_downgrade" in r.message
    ]
    assert fable_warnings == [], "Expected no fable_downgrade WARNING when switch is off"


# ---------------------------------------------------------------------------
# AC4: Provider gate evaluates the *requested* model's provider — unchanged
# ---------------------------------------------------------------------------


def test_provider_gate_passes_for_fable_anthropic_verify_model() -> None:
    """provider=anthropic + claude-fable-5 verify → gate PASSES (both anthropic).

    resolve_provider('claude-fable-5') == 'anthropic', so the gate should not skip.
    """
    client, fake = _make_client(fable_downgrade=True, model_verify="claude-fable-5")

    result = fact_check_question(client, _question(), provider="anthropic", max_uses=5)

    assert result is not None, (
        "Expected fact_check to run: resolve_provider('claude-fable-5') == 'anthropic'"
    )
    assert fake.calls, "Expected at least one SDK call"


def test_provider_gate_skips_when_provider_is_gemini_but_model_is_anthropic() -> None:
    """provider=gemini + claude-fable-5 verify → gate SKIPS (anthropic ≠ gemini).

    The gate evaluates the *requested* model's provider; the downgrade switch does not
    affect what the gate compares.
    """
    client, fake = _make_client(fable_downgrade=True, model_verify="claude-fable-5")

    result = fact_check_question(client, _question(), provider="gemini", max_uses=5)

    assert result is None, (
        "Expected fact_check to skip: 'gemini' != resolve_provider('claude-fable-5')"
    )
    assert not fake.calls, "Expected no SDK call when gate skips"
