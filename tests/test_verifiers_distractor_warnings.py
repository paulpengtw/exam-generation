"""verify_question appends distractor warnings without failing the question."""

from __future__ import annotations

import json

import pytest


class _FakeVerifierClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def generate_with_image(self, system, user, image_path=None, purpose="verify"):
        return json.dumps(self._payload, ensure_ascii=False)


def _passed_payload() -> dict:
    return {
        "my_answer": "B", "provided_answer": "B",
        "answer_match": True, "passed": True,
        "details": "看起來沒問題。",
    }


def test_math_verifier_appends_distractor_warning_when_keys_mismatch() -> None:
    from src.schemas import ExamQuestion
    from src.verifier import verify_question

    q = ExamQuestion(
        情境=["個人"], 題型種類="單一題", 題型="選擇題",
        數學思考=["形成"], 學習內容=[],
        題目=["Q? (A) 3 (B) 4 (C) 5 (D) 6"],
        正確解題分析=["B"],
        誘答分析={"A": "x", "B": "正確答案：4。", "C": "x"},  # missing D
    )
    client = _FakeVerifierClient(_passed_payload())
    result = verify_question(client, q)
    assert result.passed is True
    assert "誘答分析提醒" in result.details
    assert "D" in result.details


def test_ss_verifier_appends_distractor_warning() -> None:
    from src.social_studies.schemas import ExamQuestion as SSExamQuestion
    from src.social_studies.schemas import SubQuestion
    from src.social_studies.verifier import verify_question

    q = SSExamQuestion(
        情境=["公共"], 題型種類="題組題", 題型="選擇題",
        閱讀歷程=["擷取訊息"], 文本形式="連續文本—敘事文",
        subquestions=[
            SubQuestion(
                序號=1, 題型="選擇題",
                題目="Q? (A) x (B) y (C) z (D) w",
                答案="A", 誘答分析={"A": "正確答案：x。"},  # missing B/C/D
            ),
        ],
    )
    client = _FakeVerifierClient(_passed_payload())
    result = verify_question(client, q)
    assert result.passed is True
    assert "誘答分析提醒" in result.details


def test_ns_verifier_appends_distractor_warning() -> None:
    from src.natural_sciences.schemas import ExamQuestion as NSExamQuestion
    from src.natural_sciences.schemas import LearningContentRef, SubQuestion
    from src.natural_sciences.verifier import verify_question

    q = NSExamQuestion(
        情境=["Personal"], 題型種類="題組題", 題型="Simple multiple-choice",
        subquestions=[
            SubQuestion(
                序號=1, 題型="Simple multiple-choice",
                題目="Q? (A) x (B) y (C) z (D) w",
                答案="A", 誘答分析={"A": "正確答案：x。"},
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1")],
            ),
        ],
    )
    client = _FakeVerifierClient(_passed_payload())
    result = verify_question(client, q)
    assert result.passed is True
    assert "誘答分析提醒" in result.details


def test_math_distractor_warning_join_separator_is_chinese_semicolon() -> None:
    """AC4: Math verifier must join multiple distractor-warning strings with '；'
    (Chinese semicolon), consistent with SS and NS verifiers.

    A question with 4 option labels but a 誘答分析 that has 1 valid key (A)
    and 1 unknown key (X) produces two warning strings from
    ``validate_distractor_keys``:
      1. "誘答分析缺少選項 B, C, D（...）"
      2. "誘答分析出現題目未定義的鍵 X"

    With the current space-join in ``src/verifier.py`` the two strings are
    joined by a plain space; this test is red until the separator is changed
    to '；' to match SS and NS.
    """
    from src.schemas import ExamQuestion
    from src.verifier import verify_question

    q = ExamQuestion(
        情境=["個人"], 題型種類="單一題", 題型="選擇題",
        數學思考=["形成"], 學習內容=[],
        題目=["Q? (A) 3 (B) 4 (C) 5 (D) 6"],
        正確解題分析=["A"],
        # Missing B, C, D  +  unknown key X → two separate warning strings
        誘答分析={"A": "正確答案：3。", "X": "未知鍵"},
    )
    result = verify_question(_FakeVerifierClient(_passed_payload()), q)
    assert "誘答分析提醒" in result.details
    block = result.details.split("[誘答分析提醒]")[1].strip()
    assert "；" in block, (
        f"Expected '；' (Chinese semicolon) between distractor warnings, "
        f"consistent with SS and NS verifiers. Got: {block!r}"
    )


@pytest.mark.parametrize("subject", ["math", "ss", "ns"])
def test_verifier_leaves_details_unchanged_when_no_warnings(subject: str) -> None:
    payload = _passed_payload()
    if subject == "math":
        from src.schemas import ExamQuestion
        from src.verifier import verify_question
        q = ExamQuestion(
            情境=["個人"], 題型種類="單一題", 題型="選擇題",
            數學思考=["形成"], 學習內容=[],
            題目=["Q?"], 正確解題分析=["A"],
        )
    elif subject == "ss":
        from src.social_studies.schemas import ExamQuestion as SSQ
        from src.social_studies.schemas import SubQuestion
        from src.social_studies.verifier import verify_question
        q = SSQ(
            情境=["公共"], 題型種類="題組題", 題型="選擇題",
            閱讀歷程=["擷取訊息"], 文本形式="連續文本—敘事文",
            subquestions=[SubQuestion(序號=1, 題型="選擇題", 題目="Q?", 答案="A")],
        )
    else:
        from src.natural_sciences.schemas import ExamQuestion as NSQ
        from src.natural_sciences.schemas import LearningContentRef, SubQuestion
        from src.natural_sciences.verifier import verify_question
        q = NSQ(
            情境=["Personal"], 題型種類="題組題", 題型="Simple multiple-choice",
            subquestions=[
                SubQuestion(
                    序號=1, 題型="Simple multiple-choice", 題目="Q?", 答案="A",
                    學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1")],
                    學習表現=[LearningContentRef(編碼="tr-Ⅳ-1")],
                ),
            ],
        )
    client = _FakeVerifierClient(payload)
    result = verify_question(client, q)
    assert result.passed is True
    assert "誘答分析提醒" not in result.details
