"""Math prompt must inject a `## 難度要求` section per SampledParams.difficulty."""

from __future__ import annotations

import random
from pathlib import Path

from src.common.difficulty import Difficulty
from src.context_builder import DIFFICULTY_INSTRUCTIONS, build_user_prompt
from src.sampler import sample_params


def test_difficulty_instructions_cover_all_three_levels():
    assert set(DIFFICULTY_INSTRUCTIONS) == {"easy", "medium", "hard"}
    for level in ("easy", "medium", "hard"):
        assert DIFFICULTY_INSTRUCTIONS[level].strip(), f"missing math instruction for {level}"


def test_prompt_contains_difficulty_section_default_medium(tmp_path: Path):
    params = sample_params(grade=8, seed=1)
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "medium" in prompt
    assert DIFFICULTY_INSTRUCTIONS["medium"][:20] in prompt


def test_prompt_contains_difficulty_section_hard(tmp_path: Path):
    params = sample_params(grade=8, seed=1, difficulty="hard")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "hard" in prompt
    assert DIFFICULTY_INSTRUCTIONS["hard"][:20] in prompt


def test_prompt_contains_difficulty_section_easy(tmp_path: Path):
    params = sample_params(grade=8, seed=1, difficulty=Difficulty.easy)
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "easy" in prompt
    assert DIFFICULTY_INSTRUCTIONS["easy"][:20] in prompt
