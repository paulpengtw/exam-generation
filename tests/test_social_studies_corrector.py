from __future__ import annotations

from src.social_studies.corrector import correct_question
from src.social_studies.schemas import ExamQuestion, SubQuestion, VerificationResult


class _FakeCorrectClient:
    def generate_json(self, *_args, **_kwargs):
        return {
            "subquestions": [
                {
                    "序號": 1,
                    "年級": 8,
                    "科目": ["地理"],
                    "核心素養": ["社-J-A2"],
                    "出題概念": "修正後概念",
                    "出題指示": "錯誤改寫的指示",
                    "題型": "開放式建構反應題",
                    "題目": "修正後題目",
                    "答案": "修正後答案",
                    "答案解析": "修正後解析",
                    "評分規準": [],
                }
            ],
        }


def test_social_studies_corrector_preserves_subquestion_instruction() -> None:
    question = ExamQuestion(
        id="ss-test",
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        subquestions=[
            SubQuestion(
                id="ss-test-01",
                序號=1,
                年級=8,
                科目=["地理"],
                核心素養=["社-J-A2"],
                出題概念="原始概念",
                出題指示="請聚焦在資料判讀",
                題型="選擇題",
                題目="原始題目",
                答案="A",
                答案解析="原始解析",
            )
        ],
    )
    verification = VerificationResult(
        passed=False,
        answer_match=False,
        details="答案需要修正。",
    )

    corrected = correct_question(_FakeCorrectClient(), question, verification)

    assert corrected.subquestions[0].出題指示 == "請聚焦在資料判讀"
    assert corrected.subquestions[0].出題概念 == "原始概念"
    assert corrected.subquestions[0].題型.value == "選擇題"
    assert corrected.subquestions[0].答案 == "修正後答案"


def test_social_studies_corrector_preserves_fixed_gap_identity() -> None:
    class _GapCorrectClient:
        def generate_json(self, *_args, **_kwargs):
            return {
                "subquestions": [
                    {
                        "id": "model-renumbered-1",
                        "序號": 91,
                        "題型": "選擇題",
                        "題目": "修正第一題",
                        "答案": "A",
                        "答案解析": "解析一",
                        "評分規準": [],
                    },
                    {
                        "id": "model-renumbered-2",
                        "序號": 92,
                        "題型": "選擇題",
                        "題目": "修正第三題",
                        "答案": "B",
                        "答案解析": "解析三",
                        "評分規準": [],
                    },
                ],
            }

    question = ExamQuestion(
        id="ss-gap",
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        subquestions=[
            SubQuestion(
                id="ss-gap-sq001",
                序號=1,
                年級=8,
                科目=["地理"],
                題型="選擇題",
                題目="原始第一題",
            ),
            SubQuestion(
                id="ss-gap-sq003",
                序號=3,
                年級=8,
                科目=["地理"],
                題型="選擇題",
                題目="原始第三題",
            ),
        ],
    )
    question.subquestions[0]._plan_index = 1
    question.subquestions[1]._plan_index = 3
    verification = VerificationResult(
        passed=False,
        answer_match=False,
        details="答案需要修正。",
    )

    corrected = correct_question(_GapCorrectClient(), question, verification)

    assert [sub.id for sub in corrected.subquestions] == [
        "ss-gap-sq001",
        "ss-gap-sq003",
    ]
    assert [sub.序號 for sub in corrected.subquestions] == [1, 3]
    assert [sub._plan_index for sub in corrected.subquestions] == [1, 3]
