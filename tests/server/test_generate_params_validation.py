"""Request-boundary validation for generation parameters."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from server.generate.models import GenerateParams

MATH_UNSUPPORTED_PARAMS: list[tuple[str, object]] = [
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


def test_generate_params_uses_admitted_by_for_ns_pair_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.natural_sciences import schema_loader

    monkeypatch.setattr(
        schema_loader,
        "load_schemas",
        lambda: {
            "情境子類別": [
                {
                    "value": "Synthetic child",
                    "parent": "Personal",
                    "admitted_by": {"情境": ["Global"]},
                },
            ],
        },
    )

    compatible = GenerateParams(
        subject="natural_sciences",
        context=["Global"],
        sub_context="Synthetic child",
    )
    assert compatible.context == ["Global"]

    with pytest.raises(
        ValidationError,
        match=r"context.*sub_context.*incompatible",
    ):
        GenerateParams(
            subject="natural_sciences",
            context=["Personal"],
            sub_context="Synthetic child",
        )


def test_generate_params_accepts_a_compatible_ns_context_pair() -> None:
    params = GenerateParams(
        subject="natural_sciences",
        context=["Global"],
        sub_context="Food security",
    )

    assert params.sub_context == "Food security"


@pytest.mark.parametrize(
    ("field", "code", "subject"),
    [
        ("learning_content", "地Aa-Ⅳ-1", "歷史"),
        ("learning_performance", "地1a-Ⅳ-2", "歷史"),
    ],
)
def test_generate_params_rejects_a_cross_subject_curriculum_pair(
    field: str,
    code: str,
    subject: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match=rf"{subject}.*{code}",
    ):
        GenerateParams(
            subject="social_studies",
            subject_filter=[subject],
            **{field: [code]},
        )


def test_generate_params_rejects_cross_subject_pair_in_per_question_params() -> None:
    with pytest.raises(
        ValidationError,
        match=r"歷史.*地Aa-Ⅳ-1",
    ):
        GenerateParams(
            subject="social_studies",
            count=1,
            per_question_params=json.dumps(
                [{"subject_filter": ["歷史"], "learning_content": ["地Aa-Ⅳ-1"]}],
                ensure_ascii=False,
            ),
        )


def test_generate_params_rejects_cross_subject_pair_in_subquestion_configs() -> None:
    with pytest.raises(
        ValidationError,
        match=r"歷史.*地Aa-Ⅳ-1",
    ):
        GenerateParams(
            subject="social_studies",
            subject_filter=["歷史"],
            subquestion_configs=json.dumps(
                [{"learning_content": ["地Aa-Ⅳ-1"]}],
                ensure_ascii=False,
            ),
        )


@pytest.mark.parametrize("subject", ["歷史", "地理", "公民與社會", "跨科"])
def test_generate_params_accepts_shared_social_curriculum_entries(subject: str) -> None:
    params = GenerateParams(
        subject="social_studies",
        subject_filter=[subject],
        learning_content=["Aa-Ⅱ-1"],
        learning_performance=["社1a-Ⅳ-1"],
        subquestion_configs=json.dumps(
            [{
                "learning_content": ["Aa-Ⅱ-1"],
                "learning_performance": ["社1a-Ⅳ-1"],
            }],
            ensure_ascii=False,
        ),
    )

    assert params.learning_content == ["Aa-Ⅱ-1"]


def test_generate_params_accepts_a_cross_subject_math_pair() -> None:
    params = GenerateParams(
        subject="math",
        subject_filter=["跨領域"],
        learning_content=["A-7-1"],
        learning_performance=["a-IV-1"],
    )

    assert params.subject_filter == ["跨領域"]


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("learning_content", "A-7-1"),
        ("learning_performance", "a-IV-1"),
    ],
)
def test_generate_params_rejects_a_cross_strand_math_pair(
    field: str,
    code: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match=rf"數與量.*{code}",
    ):
        GenerateParams(
            subject="math",
            subject_filter=["數與量"],
            **{field: [code]},
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
        match=r"question_word_limit.*option_word_limit.*subquestion_configs",
    ):
        GenerateParams(
            subject="math",
            question_word_limit=80,
            option_word_limit=30,
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


def test_generate_params_accepts_math_thinking_values() -> None:
    params = GenerateParams(
        subject="math",
        math_thinking=["形成", "詮釋評估"],
    )

    assert params.math_thinking == ["形成", "詮釋評估"]


@pytest.mark.parametrize(
    "math_thinking",
    [[], ["形成", "運用", "詮釋評估", "形成"], ["不合法"]],
)
def test_generate_params_rejects_invalid_math_thinking(
    math_thinking: list[str],
) -> None:
    with pytest.raises(ValidationError, match="math_thinking"):
        GenerateParams(subject="math", math_thinking=math_thinking)


def test_generate_params_accepts_optional_drawn_paths() -> None:
    drawn = ["learning_content", "per_question_params[0].learning_content"]

    params = GenerateParams(subject="math", drawn=drawn)

    assert params.drawn == drawn
    assert params.model_dump(mode="json")["drawn"] == drawn


def test_generate_params_without_drawn_remains_valid() -> None:
    params = GenerateParams(subject="math")

    assert params.drawn is None


def test_generate_params_accepts_math_text_word_limit() -> None:
    params = GenerateParams(subject="math", text_word_limit=500)

    assert params.text_word_limit == 500


def test_generate_params_rejects_math_text_word_limit_with_user_passage() -> None:
    with pytest.raises(ValidationError, match=r"text_word_limit.*passage"):
        GenerateParams(
            subject="math",
            text_word_limit=500,
            passage="使用者提供的文本",
        )


def test_generate_params_accepts_math_sub_question_count() -> None:
    params = GenerateParams(subject="math", sub_question_count=4)

    assert params.sub_question_count == 4


def test_generate_params_rejects_math_count_with_explicit_single_question_type() -> None:
    with pytest.raises(
        ValidationError,
        match=r"sub_question_count.*題組題.*單一題",
    ):
        GenerateParams(
            subject="math",
            sub_question_count=4,
            set_type="單一題",
        )


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


def test_generate_params_defaults_image_generation_mode_to_html() -> None:
    """Backend/CLI default stays html; only the web form defaults to gpt_image."""
    params = GenerateParams()

    assert params.image_generation_mode == "html"


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


# ── Issue #279: 題組-level Reporting Scale wire boundary ──────────────────────


@pytest.mark.parametrize("level", ["1c", "1b", "1a", "2", "3", "4", "5", "6"])
def test_generate_params_accepts_all_reporting_scale_levels_for_ns(level: str) -> None:
    params = GenerateParams(subject="natural_sciences", reporting_scale=level)
    assert params.reporting_scale == level


@pytest.mark.parametrize("bad", ["7", "0", "99", "easy", "medium", "hard"])
def test_generate_params_rejects_invalid_reporting_scale_for_ns(bad: str) -> None:
    with pytest.raises(ValidationError, match="reporting_scale"):
        GenerateParams(subject="natural_sciences", reporting_scale=bad)


def test_generate_params_rejects_empty_reporting_scale() -> None:
    with pytest.raises(ValidationError, match="reporting_scale"):
        GenerateParams(subject="natural_sciences", reporting_scale="")


@pytest.mark.parametrize("subject", ["math", "social_studies"])
def test_generate_params_accepts_reporting_scale_for_non_ns_subjects(subject: str) -> None:
    """Mirror science_competency pattern: non-NS subjects accept (and ignore) the field."""
    params = GenerateParams(subject=subject, reporting_scale="4")
    assert params.reporting_scale == "4"
