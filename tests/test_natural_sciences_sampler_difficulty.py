"""Natural sciences sampler difficulty passthrough."""

from __future__ import annotations

from src.common.difficulty import Difficulty
from src.natural_sciences.sampler import sample_params


def test_ns_sampler_difficulty_defaults_to_medium():
    assert sample_params(seed=1).difficulty is Difficulty.medium


def test_ns_sampler_difficulty_string_passthrough():
    for v in ("easy", "medium", "hard"):
        assert sample_params(seed=1, difficulty=v).difficulty is Difficulty(v)


def test_ns_sampler_difficulty_enum_passthrough():
    assert sample_params(seed=1, difficulty=Difficulty.hard).difficulty is Difficulty.hard


def test_ns_sampler_difficulty_not_randomized():
    for seed in range(50):
        assert sample_params(seed=seed).difficulty is Difficulty.medium
