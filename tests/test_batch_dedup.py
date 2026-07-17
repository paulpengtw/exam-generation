"""Unit tests for the batch-level prior-scope helper (issue #111)."""

from __future__ import annotations

import logging

from src.common.batch_dedup import (
    _PRIOR_SCOPES_CAP,
    PriorScope,
    extract_math_prior_scope,
    extract_ns_prior_scope,
    extract_ss_prior_scope,
    format_prior_scopes_block,
)


def test_format_returns_empty_string_when_no_scopes() -> None:
    assert format_prior_scopes_block([]) == ""


def test_format_renders_summary_and_codes() -> None:
    scopes = [
        PriorScope(summary="人口老化如何影響社區資源？", codes=["歷Ka-Ⅳ-1", "地Ab-Ⅳ-2"]),
        PriorScope(summary="能源轉型的取捨", codes=["自Nc-Ⅳ-3"]),
    ]
    block = format_prior_scopes_block(scopes)
    assert "## 已生成題目（請避免相似範圍）" in block
    assert "1. 核心問題：人口老化如何影響社區資源？；學習內容：歷Ka-Ⅳ-1, 地Ab-Ⅳ-2" in block
    assert "2. 核心問題：能源轉型的取捨；學習內容：自Nc-Ⅳ-3" in block


def test_format_renders_empty_codes_as_placeholder() -> None:
    block = format_prior_scopes_block([PriorScope(summary="測試主題", codes=[])])
    assert "1. 核心問題：測試主題；學習內容：（無）" in block


def test_format_caps_at_ten_most_recent_entries() -> None:
    scopes = [
        PriorScope(summary=f"主題{i}", codes=[f"X-{i}"]) for i in range(1, 13)
    ]
    assert _PRIOR_SCOPES_CAP == 10
    block = format_prior_scopes_block(scopes)
    # Oldest two dropped; the surviving ten start with 主題3 and end with 主題12.
    assert "主題1；" not in block
    assert "主題2；" not in block
    assert "1. 核心問題：主題3；" in block
    assert "10. 核心問題：主題12；" in block


def test_extract_math_uses_出題概念_and_學習內容_codes() -> None:
    from src.schemas import ExamQuestion, LearningContentItem

    question = ExamQuestion.model_construct(
        id="q_test",
        情境=[],
        題型種類="單一題",
        題型="選擇題",
        數學思考=[],
        學習內容=[
            LearningContentItem(編碼="N-7-1", 說明="整數運算"),
            LearningContentItem(編碼="N-7-2", 說明="有理數"),
            LearningContentItem(編碼="N-7-1", 說明="整數運算"),  # duplicate
        ],
        題目=[],
        正確解題分析=[],
        出題概念="評量學生能否比較有理數大小",
    )
    scope = extract_math_prior_scope(question)
    assert scope is not None
    assert scope.summary == "評量學生能否比較有理數大小"
    assert scope.codes == ["N-7-1", "N-7-2"]  # order preserved, deduped


def test_extract_math_returns_none_when_both_summary_and_codes_missing(caplog) -> None:
    from src.schemas import ExamQuestion

    question = ExamQuestion.model_construct(
        id="q_empty",
        情境=[],
        題型種類="單一題",
        題型="選擇題",
        數學思考=[],
        學習內容=[],
        題目=[],
        正確解題分析=[],
        出題概念="",
    )
    with caplog.at_level(logging.DEBUG, logger="src.common.batch_dedup"):
        scope = extract_math_prior_scope(question)
    assert scope is None
    assert any("skipping prior scope" in rec.message for rec in caplog.records)


def test_extract_ss_uses_核心問題_and_aggregated_subquestion_codes() -> None:
    from src.social_studies.schemas import (
        ExamQuestion,
        LearningContentRef,
        SubQuestion,
    )

    question = ExamQuestion.model_construct(
        id="ss_test",
        核心問題="工業革命如何改變勞動條件？",
        文本="…",
        取材來源=[],
        subquestions=[
            SubQuestion.model_construct(
                id="ss_test-01",
                序號=1,
                年級=8,
                科目=["歷史"],
                核心素養=[],
                學習內容=[LearningContentRef(編碼="歷Ka-Ⅳ-1", 說明="工業革命")],
                學習表現=[],
                題型="選擇題",
                題目="…",
            ),
            SubQuestion.model_construct(
                id="ss_test-02",
                序號=2,
                年級=8,
                科目=["公民與社會"],
                核心素養=[],
                學習內容=[
                    LearningContentRef(編碼="公Ab-Ⅳ-2", 說明="勞動權益"),
                    LearningContentRef(編碼="歷Ka-Ⅳ-1", 說明="工業革命"),
                ],
                學習表現=[],
                題型="選擇題",
                題目="…",
            ),
        ],
        情境=[],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=[],
        文本形式="連續文本",
    )
    scope = extract_ss_prior_scope(question)
    assert scope is not None
    assert scope.summary == "工業革命如何改變勞動條件？"
    assert scope.codes == ["歷Ka-Ⅳ-1", "公Ab-Ⅳ-2"]


def test_extract_ns_uses_核心問題_and_aggregated_subquestion_codes() -> None:
    from src.natural_sciences.schemas import (
        ExamQuestion,
        LearningContentRef,
        SubQuestion,
    )

    question = ExamQuestion.model_construct(
        id="ns_test",
        核心問題="海洋酸化對生態的影響",
        文本="…",
        取材來源=[],
        subquestions=[
            SubQuestion.model_construct(
                id="ns_test-01",
                序號=1,
                年級=8,
                科目=["自然科學"],
                科學能力=["能力一"],
                核心素養=[],
                學習內容=[LearningContentRef(編碼="INc-Ⅳ-1", 說明="…")],
                學習表現=[],
                題型="Simple-multiple-choice",
                題目="…",
            ),
        ],
        情境=[],
        情境子類別="Environment",
        題型種類="題組題",
        題型="Simple-multiple-choice",
        科學能力=["能力一"],
    )
    scope = extract_ns_prior_scope(question)
    assert scope is not None
    assert scope.summary == "海洋酸化對生態的影響"
    assert scope.codes == ["INc-Ⅳ-1"]
