"""Tests for src.social_studies.fact_check (issue #104)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.social_studies.fact_check import fact_check_question, is_current_events
from src.social_studies.schemas import (
    ExamQuestion,
    FactCheckResult,
    LearningContentRef,
    QuestionMetadata,
    SubQuestion,
)


def _question(
    *,
    core_question: str = "本題組核心問題。",
    passage: str = "本題組文本。",
    lc_codes: list[str] | None = None,
) -> ExamQuestion:
    codes = lc_codes or ["歷Ka-Ⅳ-1"]
    subqs = [
        SubQuestion(
            id="ss-test-01",
            序號=1,
            年級=8,
            科目=["歷史"],
            核心素養=[],
            學習內容=[LearningContentRef(編碼=c, 說明="") for c in codes],
            學習表現=[],
            出題概念="",
            題型="選擇題",
            題目="測試題目",
        )
    ]
    return ExamQuestion(
        id="ss-test",
        核心問題=core_question,
        文本=passage,
        subquestions=subqs,
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        題目=[passage, "測試題目"],
        正確解題分析=["A"],
        metadata=QuestionMetadata(grade=8, model="fake-model"),
    )


def test_is_current_events_true_when_公民_learning_content_present() -> None:
    q = _question(lc_codes=["公Ba-Ⅳ-3"], core_question="說明地方治理原則。", passage="…")
    assert is_current_events(q) is True


def test_is_current_events_true_when_核心問題_matches_regex() -> None:
    q = _question(
        lc_codes=["歷Ka-Ⅳ-1"], core_question="近年來全球暖化對台灣有何衝擊？", passage="…",
    )
    assert is_current_events(q) is True


def test_is_current_events_true_when_文本_matches_regex() -> None:
    q = _question(
        lc_codes=["歷Ka-Ⅳ-1"],
        core_question="工業革命的影響。",
        passage="根據今年公布的資料…",
    )
    assert is_current_events(q) is True


def test_is_current_events_true_when_explicit_flag() -> None:
    q = _question(lc_codes=["歷Ka-Ⅳ-1"], core_question="…", passage="…")
    assert is_current_events(q) is False
    assert is_current_events(q, explicit=True) is True


def test_is_current_events_false_for_non_time_sensitive_question() -> None:
    q = _question(
        lc_codes=["歷Ka-Ⅳ-1"],
        core_question="工業革命的重要性。",
        passage="十八世紀後半，蒸汽動力興起。",
    )
    assert is_current_events(q) is False


class _StubClient:
    """Records the last call and replays a scripted (text, citations) tuple."""

    def __init__(
        self,
        text: str = "",
        citations: list[dict] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._text = text
        self._citations = citations or []
        self._raises = raises
        self.last_tools: list[dict] | None = None
        self.last_purpose: str | None = None
        self.calls = 0

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
        self.last_tools = tools
        self.last_purpose = purpose
        if self._raises is not None:
            raise self._raises
        from src.llm_client import Citation
        cits = [Citation(url=c["url"], title=c.get("title", "")) for c in self._citations]
        return self._text, cits


def test_fact_check_question_returns_none_when_provider_disabled() -> None:
    client = _StubClient(text=json.dumps({"verified": False, "issues": ["x"]}))
    result = fact_check_question(
        client, _question(), provider="none", max_uses=5,
    )
    assert result is None
    assert client.calls == 0


def test_fact_check_question_returns_verified_result_on_success() -> None:
    payload = {
        "verified": False,
        "issues": ["文本聲稱2024年台北市長為某某，實際為另一人。"],
    }
    client = _StubClient(
        text=json.dumps(payload, ensure_ascii=False),
        citations=[
            {"url": "https://gov.tw/report", "title": "公開資料"},
            {"url": "https://news.example/2024", "title": "新聞報導"},
        ],
    )
    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )
    assert isinstance(result, FactCheckResult)
    assert result.verified is False
    assert result.issues == ["文本聲稱2024年台北市長為某某，實際為另一人。"]
    assert result.citations == ["https://gov.tw/report", "https://news.example/2024"]
    assert client.last_purpose == "fact_check"
    assert client.last_tools is not None
    assert client.last_tools[0]["type"] == "web_search_20250305"
    assert client.last_tools[0]["max_uses"] == 5


def test_fact_check_question_fails_open_on_client_exception() -> None:
    client = _StubClient(raises=RuntimeError("boom"))
    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )
    assert result is None


def test_fact_check_question_fails_open_on_malformed_json() -> None:
    client = _StubClient(text="not json at all")
    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )
    assert result is None


def test_fact_check_question_fails_open_on_result_construction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a broken FactCheckResult(...) construction must not raise."""
    import src.social_studies.fact_check as fact_check_module

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(fact_check_module, "FactCheckResult", _boom)
    client = _StubClient(text=json.dumps({"verified": True, "issues": []}))
    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )
    assert result is None
