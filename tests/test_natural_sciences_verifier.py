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
                規準說明="完整說明水溫升高導致溶氧量下降的趨勢，並附一個具體例子。"
                "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。",
                學生作答實例=["水溫升高時溶氧量下降，夏季魚群浮頭就是一例。"],
            ),
            RubricEntry(
                code="1",
                規準說明="說明了趨勢或舉了例子，但推理鏈條有缺口：缺口一為有趨勢但未說明原因，缺口二為有例子但未連結到溶氧量。",
                學生作答實例=[
                    "水溫越高，溶氧量會下降，因為溫度高水分子跑得快。",
                    "夏天魚群常浮頭，應該和溫度有關。",
                ],
            ),
            RubricEntry(
                code="0",
                規準說明="未說明溶氧量趨勢，或方向錯誤。",
                學生作答實例=["水溫越高溶解的氧氣越多，所以魚會更活躍。"],
            ),
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


# ---- Issue #866: rubric shape check hook tests ----

def _conforming_cr_rubric() -> list:
    """Conforming 2/1/0 rubric with 1/2/1 examples and fixed sentence."""
    return [
        RubricEntry(
            code="2",
            規準說明=(
                "完整說明水溫升高導致溶氧量下降的趨勢，並附一個具體例子。"
                "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
            ),
            學生作答實例=["水溫升高時溶氧量下降，夏季魚群浮頭就是一例。"],
        ),
        RubricEntry(
            code="1",
            規準說明="說明了趨勢或舉了例子，但推理鏈條有缺口：缺口一為有趨勢但未說明原因，缺口二為有例子但未連結到溶氧量。",
            學生作答實例=[
                "水溫越高溶氧量會下降，因為溫度高水分子跑得快。",
                "夏天魚群常浮頭，應該和溫度有關。",
            ],
        ),
        RubricEntry(
            code="0",
            規準說明="未說明溶氧量趨勢，或方向錯誤。",
            學生作答實例=["水溫越高溶解的氧氣越多，所以魚會更活躍。"],
        ),
    ]


def _cr_question_with_rubric(rubric: list, sq_type: str = "Constructed response") -> ExamQuestion:
    return ExamQuestion(
        id="ns-cr-test",
        核心問題="水溫對溶氧量的影響",
        文本="河川在夏天水溫偏高，溶氧量測量結果顯示明顯差異……",
        情境=["Personal"],
        題型種類="題組題",
        題型=sq_type,
        subquestions=[
            SubQuestion(
                序號=1,
                年級=8,
                科目=["自然科學"],
                題型=sq_type,
                題目="請說明水溫上升如何影響水中溶氧量，並舉一例。",
                答案="水溫上升，溶氧量下降；例如夏季魚群浮頭。",
                答案解析="溫度升高使氣體溶解度降低，溶氧量因此下降。",
                評分規準=rubric,
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="水的溶解度")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="資料推論")],
            )
        ],
    )


def test_ns_rubric_shape_hook_passes_conforming_rubric() -> None:
    """A conforming 2/1/0 rubric with 1/2/1 examples and fixed sentence passes."""
    q = _cr_question_with_rubric(_conforming_cr_rubric())
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is True
    assert "[評分規準形狀檢核]" not in result.details


def test_ns_rubric_shape_hook_fails_when_llm_already_failed() -> None:
    """When LLM verdict is already failed, shape check appends to existing details."""
    rubric = [
        RubricEntry(
            code="2",
            規準說明="完整說明趨勢並舉例。學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。",  # noqa: E501
            學生作答實例=["水溫升高溶氧量下降，夏季魚群浮頭。"],
        ),
        # [1] is missing — only 1 example instead of 2
        RubricEntry(
            code="1",
            規準說明="說明了趨勢但未舉例，或舉例但未連結原因。",
            學生作答實例=["水溫升高，溶氧量下降。"],
        ),
        RubricEntry(
            code="0",
            規準說明="未說明趨勢，或方向錯誤。",
            學生作答實例=["水溫越高溶氧越多。"],
        ),
    ]
    q = _cr_question_with_rubric(rubric)
    failed_payload = {
        "my_answer": "水溫升高，溶氧量下降",
        "provided_answer": "水溫升高，溶氧量下降",
        "answer_match": False,
        "passed": False,
        "details": "答案與素材矛盾。",
    }
    result = verify_question(FakeClient(failed_payload), q)
    assert result.passed is False
    assert "答案與素材矛盾" in result.details
    assert "[評分規準形狀檢核]" in result.details
    assert "第1題 [1] 級距需要 2 個學生作答實例" in result.details


def test_ns_rubric_shape_hook_mixed_question_group() -> None:
    """In a 題組 with headline CMC, only the CR subquestion is checked.

    The CMC subquestion with 0X code and no examples reports nothing.
    """

    cr_rubric = _conforming_cr_rubric()
    q = ExamQuestion(
        id="ns-mixed",
        核心問題="混合題型測試",
        文本="測試文本……",
        情境=["Personal"],
        題型種類="題組題",
        題型="Complex multiple-choice",  # headline is CMC
        subquestions=[
            SubQuestion(
                序號=1,
                年級=8,
                科目=["自然科學"],
                題型="Complex multiple-choice",  # CMC 小題 — not in scope
                題目="請判斷下列敘述是非：(1)水溫升高溶氧量下降 (2)魚群浮頭表示溶氧充足",
                答案="(1)是 (2)非",
                答案解析="溫度升高氣體溶解度降低。",
                評分規準=[
                    RubricEntry(code="2", 規準說明="全對", 學生作答實例=[]),
                    RubricEntry(code="1", 規準說明="部分正確", 學生作答實例=[]),
                    RubricEntry(code="0", 規準說明="錯誤", 學生作答實例=[]),
                    RubricEntry(code="0X", 規準說明="未作答", 學生作答實例=[]),
                ],
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="水的溶解度")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="資料推論")],
            ),
            SubQuestion(
                序號=2,
                年級=8,
                科目=["自然科學"],
                題型="Constructed response",  # CR 小題 — in scope
                題目="請說明水溫升高為何導致溶氧量下降。",
                答案="溫度升高使氣體溶解度降低。",
                答案解析="溫度升高時水分子熱運動加速，氣體難以留在水中。",
                評分規準=cr_rubric,
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="水的溶解度")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="資料推論")],
            ),
        ],
    )
    result = verify_question(FakeClient(_passing_payload()), q)
    # CR subquestion has a conforming rubric → should pass
    assert result.passed is True
    assert "[評分規準形狀檢核]" not in result.details


def test_ns_rubric_shape_hook_cmc_with_0x_reports_nothing() -> None:
    """CMC subquestion with 0X code and no examples is not checked by shape hook."""
    q = ExamQuestion(
        id="ns-cmc-only",
        核心問題="選擇題型測試",
        文本="測試文本……",
        情境=["Personal"],
        題型種類="題組題",
        題型="Complex multiple-choice",
        subquestions=[
            SubQuestion(
                序號=1,
                年級=8,
                科目=["自然科學"],
                題型="Complex multiple-choice",
                題目="請判斷下列敘述是非。",
                答案="(1)是 (2)非",
                答案解析="正確答案。",
                評分規準=[
                    RubricEntry(code="2", 規準說明="全對", 學生作答實例=[]),
                    RubricEntry(code="1", 規準說明="部分", 學生作答實例=[]),
                    RubricEntry(code="0", 規準說明="錯", 學生作答實例=[]),
                    RubricEntry(code="0X", 規準說明="未答", 學生作答實例=[]),
                ],
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="溶解")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="推論")],
            ),
        ],
    )
    result = verify_question(FakeClient(_passing_payload()), q)
    assert "[評分規準形狀檢核]" not in result.details
