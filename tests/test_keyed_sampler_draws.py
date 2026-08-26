"""Cross-subject invariants for keyed sampler streams."""

from __future__ import annotations

from src.natural_sciences.sampler import sample_params as sample_natural_sciences
from src.sampler import sample_params as sample_math
from src.social_studies.sampler import sample_params as sample_social_studies


def test_seed_pins_and_counters_replay_byte_identical_payloads_for_all_subjects() -> None:
    cases = (
        (
            sample_math,
            {
                "grade": 8,
                "content_type": "純文字",
                "seed": 31,
                "redraws": {"題型": 2},
            },
        ),
        (
            sample_social_studies,
            {
                "seed": 31,
                "sub_question_count": 3,
                "target_surface": "數位",
                "redraws": {"subquestion_configs[2].question_type": 2},
            },
        ),
        (
            sample_natural_sciences,
            {
                "seed": 31,
                "sub_question_count": 3,
                "subquestion_configs": [{}, {}, {}],
                "redraws": {"subquestion_configs[2].reporting_scale": 2},
            },
        ),
    )

    for sampler, kwargs in cases:
        first = sampler(**kwargs)
        second = sampler(**kwargs)
        assert first.model_dump_json() == second.model_dump_json()
