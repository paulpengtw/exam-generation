"""Social studies sampler difficulty passthrough."""

from __future__ import annotations

from src.common.difficulty import Difficulty
from src.social_studies.sampler import sample_params


def test_ss_sampler_difficulty_defaults_to_medium():
    p = sample_params(seed=1)
    assert p.difficulty is Difficulty.medium


def test_ss_sampler_difficulty_string_passthrough():
    for v in ("easy", "medium", "hard"):
        assert sample_params(seed=1, difficulty=v).difficulty is Difficulty(v)


def test_ss_sampler_difficulty_enum_passthrough():
    p = sample_params(seed=1, difficulty=Difficulty.hard)
    assert p.difficulty is Difficulty.hard


def test_ss_sampler_difficulty_not_randomized():
    for seed in range(50):
        assert sample_params(seed=seed).difficulty is Difficulty.medium
