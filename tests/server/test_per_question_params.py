"""Per-question request parameters are applied at the generation fan-out."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from server.config import ServerConfig
from server.generate.models import (
    PER_QUESTION_FIELDS,
    REQUEST_LEVEL_FIELDS,
    SERVER_ONLY_GENERATE_FIELDS,
    GenerateParams,
    decode_per_question_params,
)
from server.generate.service import _sample_worker_params
from server.generate.subjects import SUBJECTS
from src.curriculum_context import load_curriculum_context
from src.data_loader import (
    get_grade_content,
    load_curriculum,
    load_intro_text,
    load_performance_standards,
)


def _app_state() -> SimpleNamespace:
    config = ServerConfig(api_key="x", data_dir=Path("data"))
    curriculum = load_curriculum(config.data_dir / "curriculum" / "學習內容.json")
    return SimpleNamespace(
        curriculum=curriculum,
        performance=load_performance_standards(
            config.data_dir / "curriculum" / "學習表現.json"
        ),
        intro_text=load_intro_text(Path('Introduction to "學習表現" and "學習階段".md')),
        grade_content={
            grade: get_grade_content(curriculum, grade) for grade in (7, 8, 9)
        },
        math_curriculum_context=load_curriculum_context(),
    )


def _sample(
    params: GenerateParams,
    index: int,
    decoded: list[dict] | None,
):
    spec = SUBJECTS[params.subject]
    app_state = _app_state()
    overrides = spec.coerce_overrides(params, app_state)
    return _sample_worker_params(
        index,
        params,
        spec,
        overrides,
        None,
        decoded,
        app_state,
    )


def _learning_content_codes(subject: str, sampled: object) -> list[str]:
    if subject == "math":
        return [item.編碼 for item in sampled.學習內容]
    return sampled.學習內容_pool


def test_per_question_subject_is_rejected_at_index_zero() -> None:
    with pytest.raises(ValueError) as exc_info:
        GenerateParams(
            subject="social_studies",
            count=1,
            per_question_params='[{"subject": "math"}]',
        )

    assert (
        "per_question_params[0] has unknown parameter(s): subject"
        in str(exc_info.value)
    )


def test_per_question_count_is_rejected() -> None:
    with pytest.raises(ValueError) as exc_info:
        GenerateParams(count=1, per_question_params='[{"count": 9999}]')

    assert (
        "per_question_params[0] has unknown parameter(s): count"
        in str(exc_info.value)
    )


def test_per_question_max_retries_is_rejected() -> None:
    with pytest.raises(ValueError) as exc_info:
        GenerateParams(count=1, per_question_params='[{"max_retries": 9}]')

    assert (
        "per_question_params[0] has unknown parameter(s): max_retries"
        in str(exc_info.value)
    )


def test_nested_per_question_params_is_rejected() -> None:
    with pytest.raises(ValueError) as exc_info:
        GenerateParams(count=1, per_question_params='[{"per_question_params": "[]"}]')

    assert (
        "per_question_params[0] has unknown parameter(s): per_question_params"
        in str(exc_info.value)
    )


def test_per_question_grade_and_seed_are_accepted() -> None:
    params = GenerateParams(
        count=1,
        per_question_params='[{"grade": 7, "seed": 1}]',
    )

    assert decode_per_question_params(params.per_question_params) == [
        {"grade": 7, "seed": 1}
    ]


def test_non_object_per_question_param_error_names_index() -> None:
    with pytest.raises(ValueError) as exc_info:
        decode_per_question_params('[{"grade": 7}, "not-object"]')

    assert "per_question_params[1] must be an object" in str(exc_info.value)


@pytest.mark.parametrize("subject", ["math", "social_studies", "natural_sciences"])
def test_one_per_question_param_set_is_applied_without_resampling(subject: str) -> None:
    params = GenerateParams(
        subject=subject,
        count=1,
        seed=184,
        per_question_params='[{"grade": 8}]',
    )

    sampled = _sample(
        params,
        0,
        decode_per_question_params(params.per_question_params),
    )

    assert sampled.grade == 8


@pytest.mark.parametrize("subject", ["math", "social_studies", "natural_sciences"])
def test_multiple_per_question_param_sets_are_zipped_by_worker_index(
    subject: str,
) -> None:
    raw = (
        '[{"grade": 7, "learning_content": ["PINNED-ONE"]},'
        '{"grade": 9, "learning_content": ["PINNED-TWO"]}]'
    )
    params = GenerateParams(
        subject=subject,
        count=2,
        seed=184,
        coverage_mode="random",
        per_question_params=raw,
    )
    decoded = decode_per_question_params(params.per_question_params)

    first = _sample(params, 0, decoded)
    second = _sample(params, 1, decoded)

    assert (first.grade, _learning_content_codes(subject, first)) == (
        7,
        ["PINNED-ONE"],
    )
    assert (second.grade, _learning_content_codes(subject, second)) == (
        9,
        ["PINNED-TWO"],
    )


def test_explicit_per_question_seed_is_used_without_worker_derivation() -> None:
    params = GenerateParams(
        subject="math",
        count=2,
        seed=184,
        coverage_mode="random",
        per_question_params='[{"seed": 901}, {"seed": 902}]',
    )
    decoded = decode_per_question_params(params.per_question_params)
    spec = SUBJECTS[params.subject]
    app_state = _app_state()
    overrides = spec.coerce_overrides(params, app_state)

    second = _sample_worker_params(
        1,
        params,
        spec,
        overrides,
        None,
        decoded,
        app_state,
    )
    expected = spec.do_sample_params(
        params,
        overrides,
        seed=902,
        subquestion_configs_decoded=None,
    )

    assert second.model_dump_json() == expected.model_dump_json()


@pytest.mark.parametrize("subject", ["math", "social_studies", "natural_sciences"])
def test_omitting_per_question_params_preserves_sampled_params_bytes(
    subject: str,
) -> None:
    params = GenerateParams(
        subject=subject,
        count=2,
        seed=184,
        coverage_mode="random",
    )
    spec = SUBJECTS[subject]
    app_state = _app_state()
    overrides = spec.coerce_overrides(params, app_state)
    legacy = spec.do_sample_params(
        params,
        overrides,
        seed=185,
        subquestion_configs_decoded=None,
    )

    through_fan_out = _sample_worker_params(
        1,
        params,
        spec,
        overrides,
        None,
    )

    assert through_fan_out.model_dump_json() == legacy.model_dump_json()


def test_every_generate_param_field_is_classified_request_level_or_per_question() -> None:
    """Guard that every GenerateParams field is explicitly classified.

    If this test fails, a new field was added to GenerateParams without being
    deliberately placed into REQUEST_LEVEL_FIELDS or PER_QUESTION_FIELDS.
    Add the new field to exactly one of those two frozensets in
    server/generate/models.py to resolve the failure.
    """
    all_fields = frozenset(GenerateParams.model_fields)

    request_level_fields = REQUEST_LEVEL_FIELDS | SERVER_ONLY_GENERATE_FIELDS
    unclassified = all_fields - request_level_fields - PER_QUESTION_FIELDS
    assert unclassified == frozenset(), (
        f"New GenerateParams field(s) are not classified: {sorted(unclassified)}. "
        "Explicitly add each field to either REQUEST_LEVEL_FIELDS (request-level, "
        "not overridable per question) or PER_QUESTION_FIELDS (per-question override "
        "allowlist) in server/generate/models.py."
    )

    assert request_level_fields | PER_QUESTION_FIELDS == all_fields, (
        "REQUEST_LEVEL_FIELDS | PER_QUESTION_FIELDS does not cover all GenerateParams fields."
    )

    assert request_level_fields & PER_QUESTION_FIELDS == frozenset(), (
        f"Fields appear in both sets: {sorted(request_level_fields & PER_QUESTION_FIELDS)}. "
        "Each field must belong to exactly one of the two sets."
    )
