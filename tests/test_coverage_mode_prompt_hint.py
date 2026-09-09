from __future__ import annotations

import random

from src.common.batch_dedup import PriorScope
from src.social_studies.context_builder import build_text_user_prompt
from src.social_studies.sampler import sample_params


def test_balanced_batch_injects_the_spread_instruction(tmp_path) -> None:
    params = sample_params(seed=5)

    prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
        balanced_batch=True,
    )

    assert "## 出題模式：均衡" in prompt
    assert "題型" in prompt
    assert "取材角度" in prompt


def test_default_call_is_byte_identical(tmp_path) -> None:
    params = sample_params(seed=5)

    default_prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
    )
    explicit_random_prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
        balanced_batch=False,
    )

    assert default_prompt == explicit_random_prompt
    assert "## 出題模式：均衡" not in default_prompt
    assert "## 出題模式：均衡" not in explicit_random_prompt


def test_reminder_block_terminates_without_trailing_whitespace(tmp_path) -> None:
    params = sample_params(seed=5)

    prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
    )

    assert "7. 只輸出 JSON 格式的結果。\n" in prompt
    assert "7. 只輸出 JSON 格式的結果。\n " not in prompt
    assert all(line == line.rstrip() for line in prompt.splitlines())


def test_balanced_instruction_coexists_with_the_prior_scopes_block(tmp_path) -> None:
    params = sample_params(seed=5)
    scopes = [
        PriorScope(summary="工業革命如何改變勞動條件？", codes=["歷Ka-Ⅳ-1"]),
    ]

    prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
        balanced_batch=True,
        prior_scopes=scopes,
    )

    assert "## 出題模式：均衡" in prompt
    assert "## 已生成題目（請避免相似範圍）" in prompt
