"""Correctors update 誘答分析 when the LLM emits a new version; else preserve it."""

from __future__ import annotations


class _FakeMathClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate_json(self, *_a, **_kw):
        return self.payload


def _math_question():
    from src.schemas import ExamQuestion
    return ExamQuestion(
        情境=["個人"], 題型種類="單一題", 題型="選擇題",
        數學思考=["形成"], 學習內容=[],
        題目=["Q? (A) 3 (B) 4 (C) 5 (D) 6"],
        正確解題分析=["B"],
        誘答分析={"A": "old", "B": "old-correct", "C": "old", "D": "old"},
    )


def test_math_corrector_replaces_distractor_when_llm_emits_new() -> None:
    from src.corrector import correct_question
    from src.schemas import VerificationResult
    q = _math_question()
    client = _FakeMathClient({
        "題目": q.題目, "正確解題分析": ["A"],
        "誘答分析": {
            "A": "正確答案：新解答。",
            "B": "誘導：新概念混淆。",
            "C": "n", "D": "n",
        },
    })
    corrected = correct_question(
        client, q,
        VerificationResult(passed=False, answer_match=False, details="wrong"),
    )
    assert corrected.誘答分析["A"].startswith("正確答案")
    assert corrected.誘答分析["B"].startswith("誘導")


def test_math_corrector_preserves_original_distractor_when_llm_omits_it() -> None:
    from src.corrector import correct_question
    from src.schemas import VerificationResult
    q = _math_question()
    client = _FakeMathClient({"題目": q.題目, "正確解題分析": ["A"]})
    corrected = correct_question(
        client, q,
        VerificationResult(passed=False, answer_match=False, details="x"),
    )
    assert corrected.誘答分析 == {"A": "old", "B": "old-correct", "C": "old", "D": "old"}


class _FakeSSClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate_json(self, *_a, **_kw):
        return self.payload


def test_ss_corrector_updates_subquestion_distractor() -> None:
    from src.social_studies.corrector import correct_question
    from src.social_studies.schemas import ExamQuestion, SubQuestion, VerificationResult
    q = ExamQuestion(
        情境=["公共"], 題型種類="題組題", 題型="選擇題",
        閱讀歷程=["擷取訊息"], 文本形式="連續文本—敘事文",
        subquestions=[
            SubQuestion(
                id="sq1", 序號=1, 題型="選擇題",
                題目="Q?", 答案="A",
                誘答分析={"A": "old-correct", "B": "old"},
            ),
        ],
    )
    client = _FakeSSClient({
        "subquestions": [{
            "序號": 1, "題型": "選擇題", "題目": "Q?", "答案": "B",
            "答案解析": "corrected",
            "誘答分析": {"A": "誘導：舊解答其實不對。", "B": "正確答案：B。"},
        }],
    })
    corrected = correct_question(
        client, q,
        VerificationResult(passed=False, answer_match=False, details="wrong answer"),
    )
    assert corrected.subquestions[0].誘答分析["B"].startswith("正確答案")


class _FakeNSClient(_FakeSSClient):
    pass


def test_ns_corrector_updates_subquestion_distractor() -> None:
    from src.natural_sciences.corrector import correct_question
    from src.natural_sciences.schemas import ExamQuestion, SubQuestion, VerificationResult
    q = ExamQuestion(
        情境=["Personal"], 題型種類="題組題", 題型="Simple multiple-choice",
        subquestions=[
            SubQuestion(
                id="sq1", 序號=1, 題型="Simple multiple-choice",
                題目="Q?", 答案="A",
                誘答分析={"A": "old-correct", "B": "old"},
            ),
        ],
    )
    client = _FakeNSClient({
        "subquestions": [{
            "序號": 1, "題型": "Simple multiple-choice",
            "題目": "Q?", "答案": "B", "答案解析": "corrected",
            "誘答分析": {"A": "誘導：舊解答其實不對。", "B": "正確答案：B。"},
        }],
    })
    corrected = correct_question(
        client, q,
        VerificationResult(passed=False, answer_match=False, details="wrong answer"),
    )
    assert corrected.subquestions[0].誘答分析["B"].startswith("正確答案")
