"""NS corrector: frozen originals stay verbatim; LLM-added subquestions get
their 學習內容/學習表現 codes canonicalized deterministically (issue #92)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.natural_sciences.corrector import correct_question
from src.natural_sciences.curriculum_codes import validate_question_codes
from src.natural_sciences.schemas import (
    ExamQuestion,
    LearningContentRef,
    SubQuestion,
    VerificationResult,
)


def _base_question() -> ExamQuestion:
    return ExamQuestion(
        id="ns1",
        情境=["Personal"],
        題型種類="題組題",
        題型="Simple multiple-choice",
        subquestions=[
            SubQuestion(
                id="sq1", 序號=1, 題型="Simple multiple-choice",
                題目="Q? (A) x (B) y", 答案="A",
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="物質的粒子模型與物質三態。")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="說明")],
            ),
        ],
    )


def _client(payload: dict) -> MagicMock:
    client = MagicMock()
    client.generate_json.return_value = payload
    return client


_VERIFICATION = VerificationResult(passed=False, answer_match=False, details="需修正")


def test_corrector_freezes_valid_original_codes() -> None:
    """Rows with an original counterpart keep the original codes verbatim."""
    payload = {
        "subquestions": [{
            "序號": 1, "題型": "Simple multiple-choice",
            "題目": "Q? (A) x (B) y", "答案": "B", "答案解析": "改正",
            "學習內容": [{"編碼": "INc-Ⅳ-1", "說明": "LLM 亂改"}],
            "學習表現": [{"編碼": "xx-Ⅳ-99", "說明": "LLM 亂改"}],
        }],
    }
    corrected = correct_question(_client(payload), _base_question(), _VERIFICATION)
    assert [r.編碼 for r in corrected.subquestions[0].學習內容] == ["Ab-Ⅳ-1"]
    assert [r.編碼 for r in corrected.subquestions[0].學習表現] == ["tr-Ⅳ-1"]


def test_corrector_canonicalizes_codes_on_llm_added_subquestion() -> None:
    payload = {
        "subquestions": [
            {
                "序號": 1, "題型": "Simple multiple-choice",
                "題目": "Q? (A) x (B) y", "答案": "A", "答案解析": "原題",
            },
            {
                "序號": 2, "題型": "Simple multiple-choice",
                "題目": "新增題 (A) 甲 (B) 乙", "答案": "B", "答案解析": "新增",
                "學習內容": [
                    {"編碼": "Ab-IV-2", "說明": ""},       # ASCII → canonical Ab-Ⅳ-2
                    {"編碼": "bogus-code", "說明": ""},    # unknown → dropped
                ],
                "學習表現": [{"編碼": "tr-IV-1", "說明": ""}],
            },
        ],
    }
    corrected = correct_question(_client(payload), _base_question(), _VERIFICATION)
    assert len(corrected.subquestions) == 2
    added = corrected.subquestions[1]
    assert [r.編碼 for r in added.學習內容] == ["Ab-Ⅳ-2"]
    assert added.學習內容[0].說明  # 說明 filled from curriculum
    assert [r.編碼 for r in added.學習表現] == ["tr-Ⅳ-1"]
    assert validate_question_codes(corrected) == []


def test_corrector_drops_all_invalid_codes_on_llm_added_subquestion() -> None:
    """No pool in the corrector: an all-invalid added row ends up empty and
    is rejected by the verifier's deterministic check on re-verify."""
    payload = {
        "subquestions": [
            {
                "序號": 1, "題型": "Simple multiple-choice",
                "題目": "Q? (A) x (B) y", "答案": "A", "答案解析": "原題",
            },
            {
                "序號": 2, "題型": "Simple multiple-choice",
                "題目": "新增題", "答案": "B", "答案解析": "新增",
                "學習內容": [{"編碼": "bogus-code", "說明": ""}],
                "學習表現": [{"編碼": "xx-Ⅳ-99", "說明": ""}],
            },
        ],
    }
    corrected = correct_question(_client(payload), _base_question(), _VERIFICATION)
    added = corrected.subquestions[1]
    assert added.學習內容 == []
    assert added.學習表現 == []
    issues = validate_question_codes(corrected)
    assert "第2小題：缺少學習內容編碼" in issues
    assert "第2小題：缺少學習表現編碼" in issues
