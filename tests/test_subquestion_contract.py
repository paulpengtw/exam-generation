"""Fixed-slot subquestion contract tests for issues #975-#978."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE
from src.common.subquestion_contract import (
    apply_fixed_subquestion_contract,
    normalize_rubric_student_examples,
)
from src.common.subquestion_failure import (
    MAX_FAILURE_DETAIL_CHARS,
    sanitize_exception_class,
    sanitize_failure_detail,
)
from src.natural_sciences.schemas import (
    QuestionType,
    RubricEntry,
    SubQuestion,
    SubQuestionConfig,
)


def test_normalize_rubric_student_examples_copies_rows_and_wraps_only_strings() -> None:
    rows = [
        {
            "code": "2",
            "規準說明": "完整",
            "學生作答實例": "學生回答",
        },
        {
            "code": "1",
            "規準說明": "部分",
            "學生作答實例": ["回答一", "回答二"],
        },
    ]

    normalized = normalize_rubric_student_examples(rows)

    assert normalized == [
        {
            "code": "2",
            "規準說明": "完整",
            "學生作答實例": ["學生回答"],
        },
        {
            "code": "1",
            "規準說明": "部分",
            "學生作答實例": ["回答一", "回答二"],
        },
    ]
    assert normalized is not rows
    assert all(copy is not original for copy, original in zip(normalized, rows, strict=True))
    assert rows[0]["學生作答實例"] == "學生回答"


@pytest.mark.parametrize("invalid", [7, {"private": "response"}])
def test_normalize_rubric_student_examples_leaves_other_shapes_invalid(
    invalid: object,
) -> None:
    [normalized] = normalize_rubric_student_examples(
        [{"code": "2", "規準說明": "完整", "學生作答實例": invalid}]
    )

    assert normalized["學生作答實例"] is invalid
    with pytest.raises(ValidationError):
        RubricEntry.model_validate(normalized)


def _valid_open_response_subquestion() -> SubQuestion:
    return SubQuestion(
        id="model-owned",
        序號=77,
        年級=8,
        科目=["自然科學"],
        題型=QuestionType("Simple multiple-choice"),
        題目="請解釋資料所呈現的現象。",
        評分規準=[
            RubricEntry(
                code="2",
                規準說明=f"完整解釋資料與現象。{EXTRA_ITEMS_FIXED_SENTENCE}",
                學生作答實例=["完整回答"],
            ),
            RubricEntry(
                code="1",
                規準說明="推理鏈有缺口。",
                學生作答實例=["缺少證據的回答", "連結錯誤的回答"],
            ),
            RubricEntry(
                code="0",
                規準說明="方向錯誤。",
                學生作答實例=["錯誤觀念的回答"],
            ),
        ],
        題目內容類型="含圖片",
    )


def test_fixed_slot_contract_restores_identity_type_and_content_pins() -> None:
    subquestion = _valid_open_response_subquestion()
    config = SubQuestionConfig(
        question_type=QuestionType("Constructed response"),
        content_type="純文字",
    )

    reason = apply_fixed_subquestion_contract(
        subquestion,
        question_id="q-fixed",
        plan_position=1,
        slot_config=config,
        fixed_identity=True,
    )

    assert reason is None
    assert subquestion.id == "q-fixed-sq002"
    assert subquestion.序號 == 2
    assert subquestion._plan_index == 2
    assert subquestion.題型 == QuestionType("Constructed response")
    assert subquestion.題目內容類型 == "純文字"


def test_fixed_slot_contract_clears_every_visual_alias_for_pure_text() -> None:
    subquestion = SimpleNamespace(
        id="model-owned",
        序號=99,
        _plan_index=99,
        題型="Simple multiple-choice",
        題目內容類型="含圖片",
        chart_spec=object(),
        image_spec=object(),
        圖片="model-owned.png",
        評分規準=[],
    )

    reason = apply_fixed_subquestion_contract(
        subquestion,
        question_id="q-fixed",
        plan_position=2,
        slot_config=SimpleNamespace(
            question_type="Simple multiple-choice",
            content_type="純文字",
        ),
        fixed_identity=True,
    )

    assert reason is None
    assert subquestion.題目內容類型 == "純文字"
    assert subquestion.chart_spec is None
    assert subquestion.image_spec is None
    assert subquestion.圖片 is None


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda rows: rows.insert(2, rows[1].model_copy()),
            "2 / 1 / 0",
        ),
        (
            lambda rows: rows.pop(),
            "2 / 1 / 0",
        ),
        (
            lambda rows: setattr(rows[1], "學生作答實例", ["只有一個"]),
            "需要 2 個學生作答實例",
        ),
        (
            lambda rows: setattr(rows[1], "學生作答實例", [" ", "另一個"]),
            "空白",
        ),
        (
            lambda rows: setattr(rows[0], "規準說明", "缺少固定句"),
            "缺少固定句",
        ),
    ],
    ids=["duplicate-code", "missing-code", "wrong-count", "blank", "fixed-sentence"],
)
def test_fixed_slot_contract_returns_first_safe_rubric_shape_issue(
    mutate,
    expected: str,
) -> None:
    subquestion = _valid_open_response_subquestion()
    subquestion.題型 = QuestionType("Constructed response")
    mutate(subquestion.評分規準)

    reason = apply_fixed_subquestion_contract(
        subquestion,
        question_id="q-fixed",
        plan_position=0,
        slot_config=SubQuestionConfig(
            question_type=QuestionType("Constructed response")
        ),
        fixed_identity=True,
    )

    assert reason is not None
    assert expected in reason


def test_failure_detail_collapses_whitespace_and_is_bounded() -> None:
    detail = sanitize_failure_detail("  safe\n\tshape reason  " + "x" * 300)

    assert detail is not None
    assert detail.startswith("safe shape reason ")
    assert "\n" not in detail
    assert "\t" not in detail
    assert len(detail) == MAX_FAILURE_DETAIL_CHARS


def test_exception_sanitizer_keeps_only_the_class_name() -> None:
    class PrivateProviderFailure(RuntimeError):
        pass

    error = PrivateProviderFailure("secret provider payload")

    assert sanitize_exception_class(error) == "PrivateProviderFailure"
    assert "secret provider payload" not in sanitize_exception_class(error)
