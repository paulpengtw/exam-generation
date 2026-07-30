"""Correctors must restore metadata.difficulty from the original question."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.common.difficulty import Difficulty


def test_math_corrector_freezes_difficulty(monkeypatch):
    from src.corrector import correct_question
    from src.schemas import (
        ExamQuestion,
        LearningContentItem,
        QuestionMetadata,
        QuestionSetType,
        QuestionStyle,
        QuestionType,
        VerificationResult,
    )

    q = ExamQuestion(
        id="q1",
        情境=[],
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        數學思考=[],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="")],
        題目=["a"],
        正確解題分析=["b"],
        metadata=QuestionMetadata(
            grade=8, style=next(iter(QuestionStyle)), model="m", difficulty=Difficulty.hard
        ),
    )
    verification = VerificationResult(passed=False, answer_match=False, details="wrong")

    client = MagicMock()
    # Simulate LLM trying to change difficulty by returning metadata.difficulty=easy
    client.generate_json.return_value = {
        "題目": ["fixed"],
        "正確解題分析": ["fixed"],
        "metadata": {"difficulty": "easy"},
    }

    fixed = correct_question(client, q, verification)
    assert fixed.metadata.difficulty is Difficulty.hard


def test_social_studies_corrector_freezes_difficulty():
    from src.social_studies.corrector import correct_question
    from src.social_studies.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionType,
        TextForm,
        VerificationResult,
    )

    q = ExamQuestion(
        id="ss1",
        subquestions=[],
        情境=[],
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        閱讀歷程=[],
        文本形式=next(iter(TextForm)),
        metadata=QuestionMetadata(grade=8, model="m", difficulty=Difficulty.easy),
    )
    verification = VerificationResult(passed=False, answer_match=False, details="wrong")

    client = MagicMock()
    client.generate_json.return_value = {"metadata": {"difficulty": "hard"}}

    fixed = correct_question(client, q, verification)
    assert fixed.metadata.difficulty is Difficulty.easy


def test_natural_sciences_corrector_old_difficulty_in_output_ignored():
    """NS QuestionMetadata no longer has difficulty (#282); old JSON with
    difficulty=easy in the LLM correction output must be silently ignored."""
    from src.natural_sciences.corrector import correct_question
    from src.natural_sciences.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionSubContext,
        QuestionType,
        VerificationResult,
    )

    q = ExamQuestion(
        id="ns1",
        subquestions=[],
        情境=[],
        情境子類別=next(iter(QuestionSubContext)),
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        metadata=QuestionMetadata(grade=8, model="m"),
    )
    verification = VerificationResult(passed=False, answer_match=False, details="wrong")

    client = MagicMock()
    # LLM may still emit difficulty in its correction JSON — it must be ignored
    client.generate_json.return_value = {"metadata": {"difficulty": "easy"}}

    fixed = correct_question(client, q, verification)
    # No AttributeError — the field simply doesn't exist on NS QuestionMetadata
    assert not hasattr(fixed.metadata, "difficulty") or fixed.metadata.difficulty is None
