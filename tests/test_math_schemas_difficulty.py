"""Math schemas must expose a difficulty field on SampledParams + QuestionMetadata."""

from __future__ import annotations


def test_sampled_params_difficulty_default_medium():
    from src.common.difficulty import Difficulty
    from src.schemas import SampledParams
    p = SampledParams(
        grade=8,
        情境=[],
        題型種類=next(iter(__import__("src.schemas", fromlist=["QuestionSetType"]).QuestionSetType)),
        題型=next(iter(__import__("src.schemas", fromlist=["QuestionType"]).QuestionType)),
        數學思考=[],
        學習內容=[],
        style=next(iter(__import__("src.schemas", fromlist=["QuestionStyle"]).QuestionStyle)),
    )
    assert p.difficulty is Difficulty.medium


def test_sampled_params_difficulty_accepts_all_three_values():
    from src.common.difficulty import Difficulty
    from src.schemas import QuestionSetType, QuestionStyle, QuestionType, SampledParams
    for value in ("easy", "medium", "hard"):
        p = SampledParams(
            grade=8,
            情境=[],
            題型種類=next(iter(QuestionSetType)),
            題型=next(iter(QuestionType)),
            數學思考=[],
            學習內容=[],
            style=next(iter(QuestionStyle)),
            difficulty=value,
        )
        assert p.difficulty is Difficulty(value)


def test_question_metadata_difficulty_default_medium():
    from src.common.difficulty import Difficulty
    from src.schemas import QuestionMetadata, QuestionStyle
    md = QuestionMetadata(grade=8, style=next(iter(QuestionStyle)), model="x")
    assert md.difficulty is Difficulty.medium
