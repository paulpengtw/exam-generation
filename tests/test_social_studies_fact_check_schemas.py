"""Schema surface for the fact-check pass (issue #104)."""

from __future__ import annotations

from src.social_studies.schemas import FactCheckResult, VerificationResult


def test_fact_check_result_defaults() -> None:
    result = FactCheckResult(verified=True)
    assert result.verified is True
    assert result.citations == []
    assert result.issues == []


def test_fact_check_result_carries_citations_and_issues() -> None:
    result = FactCheckResult(
        verified=False,
        citations=["https://example.org/a", "https://example.org/b"],
        issues=["文本聲稱2024年的選舉結果與公開紀錄不符。"],
    )
    assert result.verified is False
    assert result.citations == ["https://example.org/a", "https://example.org/b"]
    assert result.issues == ["文本聲稱2024年的選舉結果與公開紀錄不符。"]


def test_verification_result_fact_check_defaults_to_none() -> None:
    result = VerificationResult(
        passed=True,
        answer_match=True,
        details="通過。",
    )
    assert result.fact_check is None


def test_verification_result_carries_fact_check_payload() -> None:
    fc = FactCheckResult(
        verified=False,
        citations=["https://example.org/report"],
        issues=["文本引用的資料不存在。"],
    )
    result = VerificationResult(
        passed=False,
        answer_match=False,
        details="事實查證未通過：文本引用的資料不存在。",
        fact_check=fc,
    )
    assert result.fact_check is fc
    dumped = result.model_dump()
    assert dumped["fact_check"]["verified"] is False
    assert dumped["fact_check"]["citations"] == ["https://example.org/report"]
