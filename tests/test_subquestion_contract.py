"""Fixed-slot subquestion contract tests for issues #975-#978."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.common.subquestion_contract import normalize_rubric_student_examples
from src.natural_sciences.schemas import RubricEntry


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
