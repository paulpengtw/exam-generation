"""Per-question request parameters are applied at the generation fan-out."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from server.config import ServerConfig
from server.generate.models import GenerateParams, decode_per_question_params
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
    batch_sampler, user_pinned_lc = spec.setup_batch_sampler(params, overrides)
    return _sample_worker_params(
        index,
        params,
        spec,
        overrides,
        batch_sampler,
        user_pinned_lc,
        None,
        decoded,
        app_state,
    )


def _learning_content_codes(subject: str, sampled: object) -> list[str]:
    if subject == "math":
        return [item.編碼 for item in sampled.學習內容]
    return sampled.學習內容_pool


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


@pytest.mark.parametrize("subject", ["math", "social_studies", "natural_sciences"])
def test_omitting_per_question_params_preserves_sampled_params_bytes(
    subject: str,
) -> None:
    params = GenerateParams(subject=subject, count=1, seed=184)
    spec = SUBJECTS[subject]
    app_state = _app_state()
    overrides = spec.coerce_overrides(params, app_state)
    batch_sampler, user_pinned_lc = spec.setup_batch_sampler(params, overrides)
    legacy = spec.do_sample_params(
        params,
        overrides,
        seed=184,
        assigned_q_type=None,
        assigned_lc=None,
        subquestion_configs_decoded=None,
    )

    through_fan_out = _sample_worker_params(
        0,
        params,
        spec,
        overrides,
        batch_sampler,
        user_pinned_lc,
        None,
    )

    assert through_fan_out.model_dump_json() == legacy.model_dump_json()
