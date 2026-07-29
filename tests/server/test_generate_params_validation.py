"""Request-boundary validation for generation parameters."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.generate.models import GenerateParams

MATH_UNSUPPORTED_PARAMS: list[tuple[str, object]] = [
    ("text_word_limit", 500),
    ("sub_question_count", 3),
    ("question_word_limit", 80),
    ("option_word_limit", 30),
    ("subquestion_configs", "[]"),
]


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


@pytest.mark.parametrize(("field", "value"), MATH_UNSUPPORTED_PARAMS)
def test_generate_params_rejects_unhonoured_math_parameter(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match=field):
        GenerateParams(subject="math", **{field: value})


def test_generate_params_lists_all_unhonoured_math_parameters() -> None:
    with pytest.raises(
        ValidationError,
        match=r"text_word_limit.*question_word_limit.*subquestion_configs",
    ):
        GenerateParams(
            subject="math",
            text_word_limit=500,
            question_word_limit=80,
            subquestion_configs="[]",
        )


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
@pytest.mark.parametrize(("field", "value"), MATH_UNSUPPORTED_PARAMS)
def test_generate_params_accepts_math_unsupported_parameter_for_curriculum_subject(
    subject: str,
    field: str,
    value: object,
) -> None:
    params = GenerateParams(subject=subject, **{field: value})

    assert getattr(params, field) == value


def test_generate_params_accepts_plain_math_request() -> None:
    params = GenerateParams(subject="math")

    assert params.subject == "math"


@pytest.mark.parametrize("disable_reference_fewshot", [False, True])
def test_generate_params_accepts_math_disable_reference_fewshot(
    disable_reference_fewshot: bool,
) -> None:
    params = GenerateParams(
        subject="math",
        disable_reference_fewshot=disable_reference_fewshot,
    )

    assert params.disable_reference_fewshot is disable_reference_fewshot


def test_generate_params_rejects_count_above_ten() -> None:
    with pytest.raises(ValidationError, match="count"):
        GenerateParams(count=11)


def test_generate_params_accepts_count_of_ten() -> None:
    params = GenerateParams(count=10)

    assert params.count == 10


def test_generate_params_defaults_count_to_one() -> None:
    params = GenerateParams()

    assert params.count == 1


def test_generate_params_rejects_count_below_one() -> None:
    with pytest.raises(ValidationError, match="count"):
        GenerateParams(count=0)


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
