"""Correction prompts carry optional user 修改指示 without weakening freezes."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from src.corrector import correct_question as correct_math_question
from src.natural_sciences.corrector import correct_question as correct_ns_question
from src.natural_sciences.schemas import ExamQuestion as NsExamQuestion
from src.natural_sciences.schemas import QuestionSetType as NsQuestionSetType
from src.natural_sciences.schemas import QuestionSubContext
from src.natural_sciences.schemas import QuestionType as NsQuestionType
from src.natural_sciences.schemas import VerificationResult as NsVerificationResult
from src.schemas import ExamQuestion as MathExamQuestion
from src.schemas import QuestionSetType as MathQuestionSetType
from src.schemas import QuestionType as MathQuestionType
from src.schemas import VerificationResult as MathVerificationResult
from src.social_studies.corrector import correct_question as correct_ss_question
from src.social_studies.schemas import ExamQuestion as SsExamQuestion
from src.social_studies.schemas import QuestionSetType as SsQuestionSetType
from src.social_studies.schemas import QuestionType as SsQuestionType
from src.social_studies.schemas import SubQuestion as SsSubQuestion
from src.social_studies.schemas import TextForm
from src.social_studies.schemas import VerificationResult as SsVerificationResult


class _CaptureCorrectClient:
    """Scripted fake client that observes the prompt at the LLM boundary."""

    def __init__(self, response: dict | None = None) -> None:
        self.response = response or {}
        self.user_prompts: list[str] = []

    def generate_json(
        self,
        _system_prompt: str,
        user_prompt: str,
        **_kwargs: object,
    ) -> dict:
        self.user_prompts.append(user_prompt)
        return self.response


def _math_question() -> MathExamQuestion:
    return MathExamQuestion(
        id="math-annotations",
        情境=[],
        題型種類=next(iter(MathQuestionSetType)),
        題型=next(iter(MathQuestionType)),
        數學思考=[],
        學習內容=[],
        題目=["原始數學題目"],
        正確解題分析=["原始分析"],
    )


def _ss_question() -> SsExamQuestion:
    return SsExamQuestion(
        id="ss-annotations",
        subquestions=[],
        情境=[],
        題型種類=next(iter(SsQuestionSetType)),
        題型=next(iter(SsQuestionType)),
        閱讀歷程=[],
        文本形式=next(iter(TextForm)),
    )


def _ns_question() -> NsExamQuestion:
    return NsExamQuestion(
        id="ns-annotations",
        subquestions=[],
        情境=[],
        情境子類別=next(iter(QuestionSubContext)),
        題型種類=next(iter(NsQuestionSetType)),
        題型=next(iter(NsQuestionType)),
    )


@pytest.mark.parametrize(
    ("corrector", "question_factory", "verification_factory"),
    [
        (correct_math_question, _math_question, MathVerificationResult),
        (correct_ss_question, _ss_question, SsVerificationResult),
        (correct_ns_question, _ns_question, NsVerificationResult),
    ],
    ids=["math", "social-studies", "natural-sciences"],
)
def test_correctors_forward_user_instructions_to_llm_prompt(
    corrector: Callable[..., object],
    question_factory: Callable[[], object],
    verification_factory: Callable[..., object],
) -> None:
    """修改指示 reaches the correction request with preservation wording."""
    annotation = "圈選：第二小題\n修改指示：保留原本的歷史人物與年代。"
    client = _CaptureCorrectClient()

    corrector(
        client,
        question_factory(),
        verification_factory(passed=False, answer_match=False, details="需要修正"),
        annotations=annotation,
    )

    prompt = client.user_prompts[0]
    assert annotation in prompt
    assert "## 修改指示（必須保留）" in prompt
    assert "不得悄悄恢復或撤銷使用者明確要求的內容" in prompt


@pytest.mark.parametrize(
    ("corrector", "question_factory", "verification_factory"),
    [
        (correct_math_question, _math_question, MathVerificationResult),
        (correct_ss_question, _ss_question, SsVerificationResult),
        (correct_ns_question, _ns_question, NsVerificationResult),
    ],
    ids=["math", "social-studies", "natural-sciences"],
)
def test_correctors_keep_default_prompt_bytes_without_annotations(
    corrector: Callable[..., object],
    question_factory: Callable[[], object],
    verification_factory: Callable[..., object],
) -> None:
    """None and an empty 修改指示 are equivalent to the legacy call."""
    verification = verification_factory(
        passed=False,
        answer_match=False,
        details="需要修正",
    )

    default_client = _CaptureCorrectClient()
    corrector(default_client, question_factory(), verification)

    none_client = _CaptureCorrectClient()
    corrector(
        none_client,
        question_factory(),
        verification_factory(passed=False, answer_match=False, details="需要修正"),
        annotations=None,
    )

    empty_client = _CaptureCorrectClient()
    corrector(
        empty_client,
        question_factory(),
        verification_factory(passed=False, answer_match=False, details="需要修正"),
        annotations="",
    )

    assert default_client.user_prompts[0] == none_client.user_prompts[0]
    assert default_client.user_prompts[0] == empty_client.user_prompts[0]
    assert "## 修改指示（必須保留）" not in default_client.user_prompts[0]


def test_social_studies_frozen_fields_survive_correction_with_annotations() -> None:
    """修改指示 must not let the LLM overwrite frozen subquestion metadata."""
    original = SsSubQuestion(
        id="ss-annotations-01",
        序號=1,
        年級=8,
        科目=["歷史"],
        出題概念="原始概念",
        出題指示="請保留原本的人物與年代",
        題型=next(iter(SsQuestionType)),
        題目="原始題目",
        答案="A",
    )
    question = SsExamQuestion(
        id="ss-frozen-annotations",
        subquestions=[original],
        情境=[],
        題型種類=next(iter(SsQuestionSetType)),
        題型=next(iter(SsQuestionType)),
        閱讀歷程=[],
        文本形式=next(iter(TextForm)),
    )
    client = _CaptureCorrectClient(
        {
            "subquestions": [
                {
                    "題目": "修正後題目",
                    "答案": "B",
                    "出題概念": "模型試圖改寫的概念",
                    "出題指示": "模型試圖改寫的指示",
                }
            ]
        }
    )

    corrected = correct_ss_question(
        client,
        question,
        SsVerificationResult(passed=False, answer_match=False, details="需要修正"),
        annotations="保留原本的人物與年代。",
    )

    assert corrected.subquestions[0].出題概念 == "原始概念"
    assert corrected.subquestions[0].出題指示 == "請保留原本的人物與年代"
    assert "保留原本的人物與年代。" in client.user_prompts[0]
