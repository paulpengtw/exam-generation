"""NS text + subquestion prompts must inject `## 難度要求`."""

from __future__ import annotations

import random
from pathlib import Path

from src.common.difficulty import Difficulty
from src.natural_sciences.context_builder import (
    DIFFICULTY_INSTRUCTIONS,
    build_subquestion_user_prompt,
    build_text_user_prompt,
)
from src.natural_sciences.sampler import sample_params


def test_ns_difficulty_instructions_cover_all_three():
    assert set(DIFFICULTY_INSTRUCTIONS) == {"easy", "medium", "hard"}
    for level in ("easy", "medium", "hard"):
        assert DIFFICULTY_INSTRUCTIONS[level].strip()


def test_ns_text_prompt_default_medium(tmp_path: Path):
    params = sample_params(seed=1)
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "medium" in prompt


def test_ns_text_prompt_hard(tmp_path: Path):
    params = sample_params(seed=1, difficulty="hard")
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "hard" in prompt
    assert DIFFICULTY_INSTRUCTIONS["hard"][:20] in prompt


def test_ns_subquestion_prompt_echoes_difficulty(tmp_path: Path):
    params = sample_params(seed=1, difficulty=Difficulty.easy)
    sq_plan = {"序號": 1, "題型": "Simple-multiple-choice", "出題概念": "回憶科學知識"}
    prompt, _ = build_subquestion_user_prompt(
        核心問題="核心",
        文本="文本內容",
        取材來源=["來源"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "## 難度要求" in prompt
    assert "easy" in prompt
