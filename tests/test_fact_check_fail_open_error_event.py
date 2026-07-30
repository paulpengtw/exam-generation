"""Fact-check fail-open emits an error stage event (issue #257 slice 4).

The fail-open contract is preserved: a failing fact-check must never alter
the generation result. But the user is now told the check did not run.
"""

from __future__ import annotations

import json

from src.social_studies.fact_check import fact_check_question, is_current_events
from src.social_studies.schemas import (
    ExamQuestion,
    LearningContentRef,
    QuestionMetadata,
    SubQuestion,
    VerificationResult,
)


def _question() -> ExamQuestion:
    """Return a question classified as current-events."""
    subqs = [
        SubQuestion(
            id="fc-test-01",
            序號=1,
            年級=8,
            科目=["公民與社會"],
            核心素養=[],
            學習內容=[LearningContentRef(編碼="公Ba-Ⅳ-3", 說明="")],
            學習表現=[],
            出題概念="",
            題型="選擇題",
            題目="測試題目",
        )
    ]
    return ExamQuestion(
        id="fc-test",
        核心問題="近年來全球暖化對台灣有何衝擊？",
        文本="本題組文本。",
        subquestions=subqs,
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—說明文",
        題目=["測試題目"],
        正確解題分析=["A"],
        metadata=QuestionMetadata(grade=8, model="fake-model"),
    )


class _RaisingClient:
    """Always raises on generate_with_tools."""
    def generate_with_tools(self, *args, **kwargs):
        raise RuntimeError("tool call failed: connection error")


class _MalformedJsonClient:
    """Returns non-JSON text."""
    def generate_with_tools(self, *args, **kwargs):
        return "this is not JSON", []


class _MissingVerifiedClient:
    """Returns JSON without the 'verified' field."""
    def generate_with_tools(self, *args, **kwargs):
        return json.dumps({"result": "ok"}), []


# ── Tests for fact_check_question on_error callback ──────────────────────────

def test_tool_call_failure_calls_on_error() -> None:
    """When the tool call raises, on_error is called with the exception text."""
    errors: list[str] = []
    result = fact_check_question(
        _RaisingClient(), _question(),
        provider="anthropic", max_uses=5,
        on_error=errors.append,
    )
    assert result is None
    assert len(errors) == 1
    assert "tool call failed" in errors[0]
    assert "connection error" in errors[0]


def test_malformed_json_calls_on_error() -> None:
    """When JSON parse fails, on_error is called."""
    errors: list[str] = []
    result = fact_check_question(
        _MalformedJsonClient(), _question(),
        provider="anthropic", max_uses=5,
        on_error=errors.append,
    )
    assert result is None
    assert len(errors) == 1
    assert len(errors[0]) > 0


def test_missing_verified_field_calls_on_error() -> None:
    """When JSON is valid but missing 'verified' boolean, on_error is called."""
    errors: list[str] = []
    result = fact_check_question(
        _MissingVerifiedClient(), _question(),
        provider="anthropic", max_uses=5,
        on_error=errors.append,
    )
    assert result is None
    assert len(errors) == 1
    assert "verified" in errors[0].lower() or "field" in errors[0].lower()


def test_provider_disabled_does_not_call_on_error() -> None:
    """When provider is not 'anthropic', on_error is never called (intentional skip)."""
    errors: list[str] = []
    result = fact_check_question(
        _RaisingClient(), _question(),
        provider="none", max_uses=5,
        on_error=errors.append,
    )
    assert result is None
    assert errors == []  # provider disabled, not an error


def test_fail_open_contract_preserved_on_tool_failure() -> None:
    """fact_check_question still returns None (not raises) on tool failure."""
    result = fact_check_question(
        _RaisingClient(), _question(),
        provider="anthropic", max_uses=5,
    )
    assert result is None  # not an exception


# ── Tests for _ss_fact_check_hook integration ─────────────────────────────────

def test_ss_fact_check_hook_emits_error_stage_event() -> None:
    """_ss_fact_check_hook emits a stage error event when fact_check fails."""
    from src.social_studies.verifier import _ss_fact_check_hook

    events: list[dict] = []

    class _ClientWithObs:
        def get_observer(self):
            return events.append

        def generate_with_tools(self, *args, **kwargs):
            raise RuntimeError("hook test: tool call failed")

        config = type("cfg", (), {
            "web_search_provider": "anthropic",
            "web_search_max_uses": 5,
        })()

    question = _question()
    assert is_current_events(question)

    result = VerificationResult(
        passed=True, answer_match=True, details="", my_answer="A", provided_answer="A"
    )

    _ss_fact_check_hook(question, result, _ClientWithObs())

    error_events = [
        e for e in events
        if e.get("type") == "stage" and e.get("status") == "error"
    ]
    assert len(error_events) >= 1, f"Expected error events, got: {events}"
    assert any("hook test" in e.get("message", "") for e in error_events)


def test_ss_fact_check_hook_fail_open_passed_unchanged() -> None:
    """The fail-open contract: result.passed stays True when fact_check fails."""
    from src.social_studies.verifier import _ss_fact_check_hook

    class _ClientWithObs:
        def get_observer(self):
            return lambda e: None

        def generate_with_tools(self, *args, **kwargs):
            raise RuntimeError("fail")

        config = type("cfg", (), {
            "web_search_provider": "anthropic",
            "web_search_max_uses": 5,
        })()

    question = _question()
    result = VerificationResult(
        passed=True, answer_match=True, details="", my_answer="A", provided_answer="A"
    )

    _ss_fact_check_hook(question, result, _ClientWithObs())

    # Fail-open: passed must remain True (fact check failure doesn't block)
    assert result.passed is True


def test_ss_fact_check_hook_disabled_provider_emits_no_error_event() -> None:
    """When provider is not 'anthropic', _ss_fact_check_hook must not emit any error event.

    fc is None (disabled path, not an exception), so no error is expected.
    """
    from src.social_studies.verifier import _ss_fact_check_hook

    events: list[dict] = []

    class _ClientDisabledProvider:
        def get_observer(self):
            return events.append

        def generate_with_tools(self, *args, **kwargs):
            # Should never be called when provider is disabled
            raise RuntimeError("must not be called")

        config = type("cfg", (), {
            "web_search_provider": "none",
            "web_search_max_uses": 5,
        })()

    question = _question()
    result = VerificationResult(
        passed=True, answer_match=True, details="", my_answer="A", provided_answer="A"
    )

    _ss_fact_check_hook(question, result, _ClientDisabledProvider())

    error_events = [
        e for e in events
        if e.get("type") == "stage" and e.get("status") == "error"
    ]
    assert error_events == [], f"No error events expected when provider disabled, got: {error_events}"
