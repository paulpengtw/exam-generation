"""Balanced-coverage sampler assignment tests (issue #112)."""

from __future__ import annotations

from src.social_studies.sampler import sample_params
from src.social_studies.schemas import QuestionType


def test_assigned_q_type_forces_that_type_when_user_did_not_pin() -> None:
    p = sample_params(seed=1, assigned_q_type=QuestionType("選擇題"))
    assert [t.value for t in p.題型] == ["選擇題"]


def test_assigned_q_type_ignored_when_user_passed_q_type_pool() -> None:
    # User explicitly narrowed to 開放式建構反應題; batch tried to force 選擇題.
    p = sample_params(
        seed=1,
        q_type=[QuestionType("開放式建構反應題")],
        assigned_q_type=QuestionType("選擇題"),
    )
    for t in p.題型:
        assert t.value == "開放式建構反應題"


def test_assigned_q_type_ignored_when_user_passed_subquestion_configs() -> None:
    from src.social_studies.schemas import SubQuestionConfig

    cfg = SubQuestionConfig(question_type=QuestionType("封閉式建構反應題"))
    p = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[cfg, {}, {}],
        assigned_q_type=QuestionType("選擇題"),
    )
    # Slot 0 stays pinned to 封閉式建構反應題; blanks are filled from the *full*
    # QuestionType pool, not from the ignored assignment.
    assert p.subquestion_configs[0].question_type.value == "封閉式建構反應題"
    fill_types = {c.question_type.value for c in p.subquestion_configs[1:]}
    assert fill_types <= {t.value for t in QuestionType}


def test_assigned_learning_content_forces_pool_when_user_did_not_pin() -> None:
    p = sample_params(
        seed=1,
        assigned_learning_content=["歷Ka-Ⅳ-1"],
    )
    assert p.學習內容_pool == ["歷Ka-Ⅳ-1"]


def test_assigned_learning_content_ignored_when_user_pinned_lc() -> None:
    p = sample_params(
        seed=1,
        learning_content=["公Ab-Ⅳ-1"],
        assigned_learning_content=["歷Ka-Ⅳ-1"],
    )
    assert p.學習內容_pool == ["公Ab-Ⅳ-1"]


def test_default_call_unchanged_without_assignments() -> None:
    p1 = sample_params(seed=42)
    p2 = sample_params(seed=42)
    assert [t.value for t in p1.題型] == [t.value for t in p2.題型]
    assert p1.學習內容_pool == p2.學習內容_pool
