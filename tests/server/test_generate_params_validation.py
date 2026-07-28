"""Request-boundary validation for generation parameters."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.generate.models import GenerateParams


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("set_type", ""),
        ("sub_context", ""),
        ("style", [""]),
        ("q_type", [""]),
        ("context", [""]),
        ("subject_filter", [""]),
        ("science_competency", [""]),
    ],
)
def test_generate_params_rejects_empty_enum_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        GenerateParams(**{field: value})


def test_generate_params_rejects_incompatible_context_and_sub_context() -> None:
    with pytest.raises(
        ValidationError,
        match=r"context.*sub_context.*incompatible",
    ):
        GenerateParams(
            subject="natural_sciences",
            context=["Global"],
            sub_context="Maintenance of health",
        )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("{not-json", "per_question_params.*valid JSON"),
        ('{"grade": 7}', "per_question_params.*JSON array"),
        ('[{"grade": 7}, "not-an-object"]', "per_question_params.*object"),
    ],
)
def test_generate_params_rejects_malformed_per_question_params(
    raw: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        GenerateParams(count=1, per_question_params=raw)


def test_generate_params_rejects_per_question_params_length_mismatch() -> None:
    with pytest.raises(
        ValidationError,
        match=r"per_question_params array length 1 must equal count 2",
    ):
        GenerateParams(count=2, per_question_params='[{"grade": 7}]')
