from __future__ import annotations

import json


class _VerifierClient:
    def __init__(self) -> None:
        self.user_prompt = ""

    def generate_with_image(self, system, user_prompt, image_path=None, purpose="verify"):
        self.user_prompt = user_prompt
        return json.dumps(
            {
                "my_answer": "A",
                "provided_answer": "A",
                "answer_match": True,
                "passed": True,
                "details": "正確",
            },
            ensure_ascii=False,
        )


def _math_group_question():
    from src.schemas import ExamQuestion, LearningContentItem, SubQuestion

    return ExamQuestion(
        id="math-group",
        核心問題="如何比較兩種方案？",
        文本="方案甲每件 10 元，方案乙每件 12 元。",
        subquestions=[
            SubQuestion(
                id="math-group-01",
                序號=1,
                年級=8,
                題型="選擇題",
                題目="第一小題：哪個單價較低？",
                答案="A",
                答案解析="10 小於 12。",
                學習內容=[LearningContentItem(編碼="N-7-1", 說明="數與量")],
            ),
            SubQuestion(
                id="math-group-02",
                序號=2,
                年級=8,
                題型="選擇題",
                題目="第二小題：差多少元？",
                答案="B",
                答案解析="12 減 10 等於 2。",
            ),
            SubQuestion(
                id="math-group-03",
                序號=3,
                年級=8,
                題型="選擇題",
                題目="第三小題：買三件方案甲共多少元？",
                答案="A",
                答案解析="10 乘以 3 等於 30。",
            ),
            SubQuestion(
                id="math-group-04",
                序號=4,
                年級=8,
                題型="選擇題",
                題目="第四小題：兩種方案各買一件相差多少元？",
                答案="B",
                答案解析="12 減 10 等於 2。",
            ),
        ],
        情境=["個人"],
        題型種類="題組題",
        題型="選擇題",
        數學思考=["運用"],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="數與量")],
        題目=[],
        正確解題分析=[],
    )


def test_math_group_verifier_prompt_includes_group_and_each_subquestion() -> None:
    from src.verifier import verify_question

    client = _VerifierClient()
    result = verify_question(client, _math_group_question())

    assert result.passed is True
    for text in (
        "如何比較兩種方案？",
        "方案甲每件 10 元，方案乙每件 12 元。",
        "第一小題：哪個單價較低？",
        "答案：A",
        "第二小題：差多少元？",
        "答案：B",
    ):
        assert text in client.user_prompt


class _CorrectorClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate_json(self, *args, **kwargs):
        return self.payload


def test_math_corrector_applies_all_group_subquestions_and_restores_frozen_fields() -> None:
    from src.corrector import correct_question
    from src.schemas import LearningContentItem, VerificationResult

    original = _math_group_question()
    original.核心素養 = ["數-J-A1"]
    original.學習內容 = [LearningContentItem(編碼="N-7-1", 說明="原始學習內容")]
    original.學習表現 = [LearningContentItem(編碼="n-IV-1", 說明="原始學習表現")]
    original.出題概念 = "原始出題概念"
    original.題目內容類型 = "純文字"
    original_subquestions = [
        {
            "id": f"math-group-{index:02d}",
            "序號": index,
            "年級": 8,
            "題型": "選擇題",
            "題目": f"修正後第{index}小題",
            "答案": "B",
            "答案解析": "修正後解析",
            "誘答分析": {},
            "學習內容": [],
            "學習表現": [],
            "出題概念": f"修正後概念{index}",
        }
        for index in range(1, 5)
    ]
    payload = {
        "情境": ["科學"],
        "題型種類": "單一題",
        "題型": "是非題",
        "數學思考": ["形成"],
        "核心素養": ["數-J-C3"],
        "學習內容": [{"編碼": "S-8-1", "說明": "不應套用"}],
        "學習表現": [{"編碼": "s-IV-2", "說明": "不應套用"}],
        "出題概念": "不應套用",
        "題目內容類型": "含圖片",
        "題目": ["修正後題目"],
        "正確解題分析": ["修正後分析"],
        "subquestions": original_subquestions,
    }

    corrected = correct_question(
        _CorrectorClient(payload),
        original,
        VerificationResult(passed=False, answer_match=False, details="需修正"),
    )

    assert len(corrected.subquestions) == 4
    assert [sub.題目 for sub in corrected.subquestions] == [
        f"修正後第{index}小題" for index in range(1, 5)
    ]
    assert corrected.情境 == original.情境
    assert corrected.題型種類 == original.題型種類
    assert corrected.題型 == original.題型
    assert corrected.數學思考 == original.數學思考
    assert corrected.核心素養 == original.核心素養
    assert corrected.學習內容 == original.學習內容
    assert corrected.學習表現 == original.學習表現
    assert corrected.出題概念 == original.出題概念
    assert corrected.題目內容類型 == original.題目內容類型


def test_math_corrector_preserves_subquestions_when_key_absent() -> None:
    """A correction pass must never silently drop 小題."""
    from src.corrector import correct_question
    from src.schemas import VerificationResult

    original = _math_group_question()
    corrected = correct_question(
        _CorrectorClient({}),
        original,
        VerificationResult(passed=False, answer_match=False, details="需修正"),
    )

    assert len(corrected.subquestions) == 4
    assert corrected.subquestions == original.subquestions


def test_math_corrector_preserves_subquestions_when_empty_list() -> None:
    """A correction pass must never silently drop 小題."""
    from src.corrector import correct_question
    from src.schemas import VerificationResult

    original = _math_group_question()
    corrected = correct_question(
        _CorrectorClient({"subquestions": []}),
        original,
        VerificationResult(passed=False, answer_match=False, details="需修正"),
    )

    assert len(corrected.subquestions) == 4
    assert corrected.subquestions == original.subquestions


def test_math_corrector_preserves_subquestions_when_not_a_list() -> None:
    """A correction pass must never silently drop 小題."""
    from src.corrector import correct_question
    from src.schemas import VerificationResult

    original = _math_group_question()
    corrected = correct_question(
        _CorrectorClient({"subquestions": "not a list"}),
        original,
        VerificationResult(passed=False, answer_match=False, details="需修正"),
    )

    assert len(corrected.subquestions) == 4
    assert corrected.subquestions == original.subquestions


def test_math_corrector_preserves_subquestions_all_or_nothing_on_invalid_entry() -> None:
    """A correction pass must never silently drop 小題."""
    from src.corrector import correct_question
    from src.schemas import VerificationResult

    original = _math_group_question()
    corrected = correct_question(
        _CorrectorClient(
            {
                "subquestions": [
                    {"題目": "不應套用的第一小題"},
                    {"題型": "不是有效題型"},
                    {"題目": "不應套用的第三小題"},
                    {"題目": "不應套用的第四小題"},
                ]
            }
        ),
        original,
        VerificationResult(passed=False, answer_match=False, details="需修正"),
    )

    assert len(corrected.subquestions) == 4
    assert corrected.subquestions == original.subquestions
