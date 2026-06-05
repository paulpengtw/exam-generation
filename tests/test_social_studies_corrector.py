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
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—說明文",
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
