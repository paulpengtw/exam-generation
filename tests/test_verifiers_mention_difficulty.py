"""Verifier prompts must include a difficulty context line."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.common.difficulty import Difficulty


def _capture_prompt(monkeypatch, module):
    captured: dict = {}

    def fake_generate_with_image(system, user_prompt, image_path=None, purpose="verify"):
        captured["system"] = system
        captured["user"] = user_prompt
        return '{"passed": true, "answer_match": true, "details": "ok"}'

    client = MagicMock()
    client.generate_with_image = fake_generate_with_image
    return client, captured


def test_math_verifier_mentions_difficulty(monkeypatch):
    from src import verifier as mod
    from src.schemas import (
        ExamQuestion,
        LearningContentItem,
        QuestionMetadata,
        QuestionSetType,
        QuestionStyle,
        QuestionType,
    )
    client, captured = _capture_prompt(monkeypatch, mod)
    q = ExamQuestion(
        id="q",
        情境=[],
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        數學思考=[],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="")],
        題目=["a"],
        正確解題分析=["b"],
        metadata=QuestionMetadata(
            grade=8, style=next(iter(QuestionStyle)), model="m", difficulty=Difficulty.hard,
        ),
    )
    mod.verify_question(client, q)
    assert "難度" in captured["user"]
    assert "hard" in captured["user"]
    assert "僅供參考" in captured["user"]


def test_social_studies_verifier_mentions_difficulty(monkeypatch):
    from src.social_studies import verifier as mod
    from src.social_studies.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionType,
        TextForm,
    )
    client, captured = _capture_prompt(monkeypatch, mod)
    q = ExamQuestion(
        id="ss",
        subquestions=[],
        情境=[],
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        閱讀歷程=[],
        文本形式=next(iter(TextForm)),
        metadata=QuestionMetadata(grade=8, model="m", difficulty=Difficulty.easy),
    )
    mod.verify_question(client, q)
    assert "難度" in captured["user"]
    assert "easy" in captured["user"]
    assert "僅供參考" in captured["user"]


def test_natural_sciences_verifier_has_no_difficulty_line(monkeypatch):
    """NS verifier must NOT mention 難度 (issue #282 — 難度 leaves NS pipeline)."""
    from src.natural_sciences import verifier as mod
    from src.natural_sciences.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionSubContext,
        QuestionType,
    )
    client, captured = _capture_prompt(monkeypatch, mod)
    q = ExamQuestion(
        id="ns",
        subquestions=[],
        情境=[],
        情境子類別=next(iter(QuestionSubContext)),
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        metadata=QuestionMetadata(grade=8, model="m"),
    )
    mod.verify_question(client, q)
    assert "難度" not in captured["user"]
    assert "Reporting Scale" not in captured["user"]
