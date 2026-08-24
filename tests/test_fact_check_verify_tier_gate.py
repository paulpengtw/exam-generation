"""Tests for the #378 fact-check verify-tier gate."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from src.llm_client import Citation, _extract_google_search_citations
from src.social_studies.fact_check import fact_check_question
from src.social_studies.schemas import (
    ExamQuestion,
    LearningContentRef,
    QuestionMetadata,
    SubQuestion,
)


def _question() -> ExamQuestion:
    """Return a minimal current-events social-studies question."""
    return ExamQuestion(
        id="verify-tier-gate",
        核心問題="近年來的公共政策如何改變？",
        文本="本題組文本。",
        subquestions=[
            SubQuestion(
                id="verify-tier-gate-01",
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
        ],
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        題目=["測試題目"],
        正確解題分析=["A"],
        metadata=QuestionMetadata(grade=8, model="fake-model"),
    )


class _RecordingClient:
    """Record the Anthropic tool call and return a valid envelope."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.calls = 0
        self.google_calls = 0

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
        return json.dumps({"verified": True, "issues": []}), []

    def generate_with_google_search(
        self,
        system: str,
        user: str,
        purpose: str = "fact_check",
        max_uses: int = 5,
        model: str | None = None,
    ) -> tuple[str, list[Citation]]:
        self.google_calls += 1
        return json.dumps({"verified": True, "issues": []}), [
            Citation(url="https://example.org/source", title="Source")
        ]


def test_verify_model_controls_anthropic_gate_when_execute_is_gemini() -> None:
    """An Anthropic fact-check proceeds when the effective verify model is Claude."""
    client = _RecordingClient(SimpleNamespace(
        model_verify="claude-opus-5",
        model_execute="gemini-3.1-pro-preview",
    ))

    result = fact_check_question(client, _question(), provider="anthropic", max_uses=5)

    assert result is not None
    assert client.calls == 1


def test_empty_verify_model_falls_back_to_anthropic_execute_model() -> None:
    """An empty verify model falls back to an Anthropic execute model."""
    client = _RecordingClient(SimpleNamespace(
        model_verify="",
        model_execute="claude-sonnet-4-6",
    ))

    result = fact_check_question(client, _question(), provider="anthropic", max_uses=5)

    assert result is not None
    assert client.calls == 1


def test_anthropic_provider_skips_when_effective_verify_model_is_gemini() -> None:
    """An Anthropic fact-check skips when the effective verify model is Gemini."""
    client = _RecordingClient(SimpleNamespace(
        model_verify="gemini-3.1-pro-preview",
        model_execute="claude-sonnet-4-6",
    ))

    result = fact_check_question(client, _question(), provider="anthropic", max_uses=5)

    assert result is None
    assert client.calls == 0


def test_gemini_provider_uses_google_search_path() -> None:
    """Gemini fact-checking calls Google grounding and returns citations."""
    client = _RecordingClient(SimpleNamespace(
        model_verify="gemini-3.1-pro-preview",
        model_execute="claude-sonnet-4-6",
    ))

    result = fact_check_question(client, _question(), provider="gemini", max_uses=5)

    assert result is not None
    assert result.citations == ["https://example.org/source"]
    assert client.google_calls == 1
    assert client.calls == 0


def test_gemini_provider_skips_when_effective_verify_model_is_anthropic() -> None:
    """Gemini fact-checking skips when the effective verify model is Claude."""
    client = _RecordingClient(SimpleNamespace(
        model_verify="claude-opus-5",
        model_execute="gemini-3.1-pro-preview",
    ))

    result = fact_check_question(client, _question(), provider="gemini", max_uses=5)

    assert result is None
    assert client.google_calls == 0
    assert client.calls == 0


def test_extract_google_search_citations_from_dict_grounding_payload() -> None:
    """Dict-shaped grounding chunks produce URL/title citations."""
    response = {
        "model_extra": {
            "candidates": [{
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://example.org/a", "title": "A"}},
                        {"web": {"uri": "https://example.org/b", "title": "B"}},
                    ]
                }
            }]
        }
    }

    assert _extract_google_search_citations(response) == [
        Citation(url="https://example.org/a", title="A"),
        Citation(url="https://example.org/b", title="B"),
    ]


def test_extract_google_search_citations_from_attribute_grounding_payload() -> None:
    """Attribute-shaped grounding metadata is read like a dict payload."""
    response = SimpleNamespace(
        candidates=[SimpleNamespace(
            grounding_metadata=SimpleNamespace(
                grounding_chunks=[
                    SimpleNamespace(web=SimpleNamespace(uri="https://example.org/a", title="A"))
                ]
            )
        )]
    )

    assert _extract_google_search_citations(response) == [
        Citation(url="https://example.org/a", title="A")
    ]


def test_extract_google_search_citations_returns_empty_without_grounding_metadata() -> None:
    """Missing grounding metadata is an accepted empty-citation outcome."""
    assert _extract_google_search_citations(SimpleNamespace(choices=[])) == []


def test_extract_google_search_citations_deduplicates_urls() -> None:
    """Grounding citations are deduplicated by URL while preserving order."""
    response = {
        "model_extra": {
            "groundingChunks": [
                {"web": {"uri": "https://example.org/a", "title": "A"}},
                {"web": {"uri": "https://example.org/a", "title": "A duplicate"}},
            ]
        }
    }

    assert _extract_google_search_citations(response) == [
        Citation(url="https://example.org/a", title="A")
    ]
