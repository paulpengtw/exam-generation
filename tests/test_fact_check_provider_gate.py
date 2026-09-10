"""Tests for the effective verify-model provider gate (issues #343 and #378).

The Anthropic ``web_search_20250305`` server tool and Gemini grounding are
provider-specific. When the configured provider does not match the effective
verify model, fact_check_question must skip (return None) without making a
client call, and must log an INFO record.
"""

from __future__ import annotations

import json
import types
from typing import Any

import pytest

from src.social_studies.fact_check import fact_check_question
from src.social_studies.schemas import (
    ExamQuestion,
    LearningContentRef,
    QuestionMetadata,
    SubQuestion,
)

# ── shared helpers ────────────────────────────────────────────────────────────


def _question() -> ExamQuestion:
    """Return a minimal but valid ExamQuestion."""
    subqs = [
        SubQuestion(
            id="gate-test-01",
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
        id="gate-test",
        核心問題="近年來全球暖化對台灣有何衝擊？",
        文本="本題組文本。",
        subquestions=subqs,
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        題目=["測試題目"],
        正確解題分析=["A"],
        metadata=QuestionMetadata(grade=8, model="fake-model"),
    )


_GOOD_RESPONSE = json.dumps({"verified": True, "issues": []})


class _RecordingClient:
    """Stub that records calls and returns a scripted successful response."""

    def __init__(
        self,
        *,
        config: Any = None,
        response_text: str = _GOOD_RESPONSE,
    ) -> None:
        self.config = config
        self._response_text = response_text
        self.calls: int = 0

    def generate_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        purpose: str = "generate",
        max_iterations: int = 3,
        model: str | None = None,
    ) -> tuple[str, list[Any]]:
        self.calls += 1
        return self._response_text, []


class _NoConfigClient:
    """Stub without a .config attribute — simulates legacy duck-typed clients."""

    def __init__(self) -> None:
        self.calls: int = 0

    def generate_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        purpose: str = "generate",
        max_iterations: int = 3,
        model: str | None = None,
    ) -> tuple[str, list[Any]]:
        self.calls += 1
        return _GOOD_RESPONSE, []


# ── tests ─────────────────────────────────────────────────────────────────────


def test_non_anthropic_exec_model_returns_none_without_calling_generate() -> None:
    """Case 1: gemini exec model → skipped, generate_with_tools never called."""
    cfg = types.SimpleNamespace(
        model_execute="gemini-3.1-pro-preview",
        web_search_provider="anthropic",
        web_search_max_uses=5,
    )
    client = _RecordingClient(config=cfg)

    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )

    assert result is None
    assert client.calls == 0


def test_anthropic_exec_model_proceeds_and_calls_generate() -> None:
    """Case 2: claude-sonnet-4-6 exec model → proceeds, generate_with_tools called."""
    cfg = types.SimpleNamespace(
        model_execute="claude-sonnet-4-6",
        web_search_provider="anthropic",
        web_search_max_uses=5,
    )
    client = _RecordingClient(config=cfg)

    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )

    assert result is not None
    assert client.calls == 1


def test_client_without_config_attribute_proceeds() -> None:
    """Case 3: no .config attribute → exec_model="" → resolve_provider returns 'anthropic'
    → proceeds.
    """
    client = _NoConfigClient()

    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )

    assert result is not None
    assert client.calls == 1


def test_non_anthropic_exec_model_logs_info(caplog: pytest.LogCaptureFixture) -> None:
    """Case 4: skipped exec model logs an INFO record mentioning the model id."""
    cfg = types.SimpleNamespace(
        model_execute="gemini-3.1-pro-preview",
        web_search_provider="anthropic",
        web_search_max_uses=5,
    )
    client = _RecordingClient(config=cfg)

    import logging

    with caplog.at_level(logging.INFO, logger="src.social_studies.fact_check"):
        fact_check_question(
            client, _question(), provider="anthropic", max_uses=5,
        )

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert info_records, "Expected at least one INFO log record"
    combined = " ".join(r.getMessage() for r in info_records)
    assert "gemini-3.1-pro-preview" in combined
