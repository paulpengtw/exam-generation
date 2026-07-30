"""Tests for the natural-sciences verifier's multimodal payload wiring and disclaimer leniency."""

from __future__ import annotations

import json

import pytest

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.natural_sciences.schemas import (
    ExamQuestion,
    LearningContentRef,
    RubricEntry,
    SubQuestion,
)
from src.natural_sciences.verifier import VERIFICATION_SYSTEM_PROMPT, verify_question


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.system_prompt = ""
        self.user_prompt = ""
        self.image_path: str | None = None

    def generate_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None = None,
        purpose: str = "generate",
    ) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.image_path = image_path
        return json.dumps(self.payload, ensure_ascii=False)


def _ns_question() -> ExamQuestion:
    """Construct a valid natural-sciences exam question per schema.

    Adaptations from brief:
    - 情境: "Local and national" (CSV matches exact spacing)
    - 情境子類別: "Environmental impact" (real value from CSV; parent="Local and national")
    - 題型: "Simple multiple-choice" (CSV confirms exact string)
    - 科學能力: Full string "能力一：以科學的角度解釋現象" (CSV matches)
    """
    return ExamQuestion(
        id="ns-test",
        核心問題="某地區水源氯離子濃度變化的原因為何？",
        文本="某地區在颱風前後量測河川水的氯離子濃度……",
        情境=["Local and national"],
        情境子類別="Environmental impact",
        題型種類="題組題",
        題型="Simple multiple-choice",
        科學能力=["能力一：以科學的角度解釋現象"],
        subquestions=[
            SubQuestion(
                序號=1,
                年級=8,
                科目=["自然科學"],
                科學能力=["能力一：以科學的角度解釋現象"],
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="範例學習內容")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="範例學習表現")],
                題型="Simple multiple-choice",
                題目="下列何者最可能造成氯離子濃度上升？(A) 海水入侵 (B) 大雨稀釋",
                答案="A",
                答案解析="颱風常帶來海水入侵造成氯離子上升。",
            )
        ],
    )


def test_ns_verifier_threads_chart_image_path_and_prompts_附圖(tmp_path) -> None:
    """When chart_image_path is given, the NS verifier must pass it to the
    client and inject the 「## 附圖」 section into the user prompt."""
    png_path = tmp_path / "chart.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    client = FakeClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "圖表資料支持答案。",
            "chart_verification": {
                "chart_data_match": True,
                "chart_labels_correct": True,
                "chart_details": "圖表標籤與題目一致。",
            },
        }
    )

    result = verify_question(client, _ns_question(), chart_image_path=str(png_path))

    assert client.image_path == str(png_path)
    assert "## 附圖" in client.user_prompt
    assert result.passed is True
    assert result.chart_verification is not None
    assert result.chart_verification.chart_data_match is True


def test_ns_verifier_omits_附圖_when_no_image() -> None:
    """Without a chart_image_path, the client must be called with image_path=None
    and 「## 附圖」 must not appear in the user prompt."""
    client = FakeClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "無圖題，答案正確。",
        }
    )

    result = verify_question(client, _ns_question())

    assert client.image_path is None
    assert "## 附圖" not in client.user_prompt
    assert result.passed is True


def test_natural_sciences_verifier_prompt_contains_illustrative_figure_leniency_line() -> None:
    assert "示意圖" in VERIFICATION_SYSTEM_PROMPT
    assert IMAGE_DISCLAIMER in VERIFICATION_SYSTEM_PROMPT
    assert "不得僅因" in VERIFICATION_SYSTEM_PROMPT
    assert "數值" in VERIFICATION_SYSTEM_PROMPT
    assert "標籤" in VERIFICATION_SYSTEM_PROMPT


def _passing_payload() -> dict:
    return {
        "my_answer": "A",
        "provided_answer": "A",
        "answer_match": True,
        "passed": True,
        "details": "審核通過。",
    }


def test_ns_verifier_fails_deterministically_on_unknown_curriculum_code() -> None:
    """Unknown 編碼 forces passed=False even when the LLM verdict is passed=True."""
    q = _ns_question()
    q.subquestions[0].學習內容 = [LearningContentRef(編碼="INc-Ⅳ-1", 說明="不存在的代碼")]
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is False
    assert "[課綱代碼檢核]" in result.details
    assert "INc-Ⅳ-1" in result.details


def test_ns_verifier_fails_deterministically_on_missing_learning_performance() -> None:
    q = _ns_question()
    q.subquestions[0].學習表現 = []
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is False
    assert "缺少學習表現編碼" in result.details


def test_ns_verifier_accepts_either_roman_numeral_spelling() -> None:
    q = _ns_question()
    q.subquestions[0].學習內容 = [LearningContentRef(編碼="Ab-IV-1")]  # ASCII spelling
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is True
    assert "[課綱代碼檢核]" not in result.details


# --- issue #92 unit-test matrix: one valid + one invalid case per item family ---

_FAMILY_CASES = [
    pytest.param(
        "Simple multiple-choice",
        "下列何者正確？(A) 甲 (B) 乙 (C) 丙 (D) 丁",
        "A",
        [],
        id="simple-mc",
    ),
    pytest.param(
        "Complex multiple-choice",
        "請逐項判斷下列敘述是非：(1)…… (2)…… (3)……",
        "(1)是 (2)非 (3)是",
        [],
        id="complex-mc",
    ),
    pytest.param(
        "Constructed response",
        "請說明水溫上升如何影響水中溶氧量，並舉一例。",
        "水溫上升使溶氧量下降，例如夏季魚群浮頭。",
        [
            RubricEntry(
                code="2",
                規準說明="完整說明趨勢並舉例",
                學生作答實例=["溶氧下降，夏季魚群浮頭"],
            ),
            RubricEntry(code="0", 規準說明="無法說明趨勢", 學生作答實例=["不知道"]),
        ],
        id="constructed-response",
    ),
]


def _family_question(q_type, 題目, 答案, rubric, lc_code, lp_code):
    return ExamQuestion(
        id="ns-family",
        核心問題="測試核心問題",
        文本="測試文本素材……",
        情境=["Personal"],
        題型種類="題組題",
        題型=q_type,
        subquestions=[
            SubQuestion(
                序號=1,
                年級=8,
                科目=["自然科學"],
                題型=q_type,
                題目=題目,
                答案=答案,
                答案解析="解析。",
                評分規準=rubric,
                學習內容=[LearningContentRef(編碼=lc_code)],
                學習表現=[LearningContentRef(編碼=lp_code)],
            )
        ],
    )


@pytest.mark.parametrize("q_type,題目,答案,rubric", _FAMILY_CASES)
def test_ns_verifier_valid_codes_pass_per_item_family(q_type, 題目, 答案, rubric) -> None:
    q = _family_question(q_type, 題目, 答案, rubric, "Ab-Ⅳ-1", "tr-Ⅳ-1")
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is True
    assert "[課綱代碼檢核]" not in result.details


@pytest.mark.parametrize("q_type,題目,答案,rubric", _FAMILY_CASES)
def test_ns_verifier_unknown_codes_fail_per_item_family(q_type, 題目, 答案, rubric) -> None:
    q = _family_question(q_type, 題目, 答案, rubric, "Ab-Ⅳ-1", "xx-Ⅳ-99")
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is False
    assert "[課綱代碼檢核]" in result.details
    assert "xx-Ⅳ-99" in result.details


def test_ns_verifier_fails_on_off_stage_lc_when_grade_in_metadata() -> None:
    """Verifier forces passed=False for an off-stage LC code when metadata.grade is set.

    Grade 10 → 第五學習階段.  "Aa-IV-3" belongs to 第四學習階段.
    LLM verdict is passed=True; [課綱代碼檢核] must override it (issue #287).
    """
    from src.natural_sciences.schemas import QuestionMetadata

    q = _ns_question()
    q.metadata = QuestionMetadata(grade=10, model="test")
    # Off-stage LC code (第四) on a 第五 question
    q.subquestions[0].學習內容 = [LearningContentRef(編碼="Aa-IV-3")]
    # Valid 第五 LP code to isolate the LC failure
    q.subquestions[0].學習表現 = [LearningContentRef(編碼="pa-Ⅴa-1")]

    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is False
    assert "[課綱代碼檢核]" in result.details
    # The reported code may use either the submitted or canonical spelling
    assert "Aa-IV-3" in result.details or "Aa-Ⅳ-3" in result.details
