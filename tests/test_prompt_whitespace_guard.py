"""Whitespace-corruption guard for 社會領域 and 自然科學 prompt builders.

Background (issue #212 / #269): a multi-line `.replace()` whose replacement
literal's closing triple-quote drifted one indent level appended
"\\n        " (newline + 8 spaces) to every 社會領域 text user prompt.
自然科學 uses the identical splice pattern with no prior guard.

This file asserts:
  - No line of any assembled prompt ends in trailing whitespace
  - At least one expected-content anchor is present per prompt shape
    (so a gross assembly regression also fails — not just whitespace)

Coverage:
  社會領域 文本生成器:  build_text_system_prompt, build_text_user_prompt
                        × 2 出題模式 (balanced_batch=False/True)
                        × 2 representative seeds
  社會領域 子題產生器:  build_subquestion_system_prompt, build_subquestion_user_prompt
                        × 2 representative seeds
  自然科學 文本生成器:  build_text_system_prompt, build_text_user_prompt
                        × 2 representative seeds
  自然科學 子題產生器:  build_subquestion_system_prompt, build_subquestion_user_prompt
                        × 2 representative seeds
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

# --- 社會領域 imports ---
from src.social_studies.context_builder import (
    build_subquestion_system_prompt as ss_build_subquestion_system_prompt,
    build_subquestion_user_prompt as ss_build_subquestion_user_prompt,
    build_text_system_prompt as ss_build_text_system_prompt,
    build_text_user_prompt as ss_build_text_user_prompt,
)
from src.social_studies.sampler import sample_params as ss_sample_params

# --- 自然科學 imports ---
from src.natural_sciences.context_builder import (
    build_subquestion_system_prompt as ns_build_subquestion_system_prompt,
    build_subquestion_user_prompt as ns_build_subquestion_user_prompt,
    build_text_system_prompt as ns_build_text_system_prompt,
    build_text_user_prompt as ns_build_text_user_prompt,
)
from src.natural_sciences.sampler import sample_params as ns_sample_params


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _assert_no_trailing_whitespace(prompt: str, label: str) -> None:
    """Fail with a clear message identifying every bad line."""
    bad = [
        (i + 1, repr(line))
        for i, line in enumerate(prompt.splitlines())
        if line != line.rstrip()
    ]
    assert not bad, (
        f"{label}: trailing whitespace found on {len(bad)} line(s): {bad}"
    )


# ===========================================================================
# 社會領域 文本生成器
# ===========================================================================

def test_ss_text_system_prompt_no_trailing_whitespace() -> None:
    """社會領域 文本生成器 system prompt has no trailing-whitespace lines."""
    prompt = ss_build_text_system_prompt()

    _assert_no_trailing_whitespace(prompt, "SS text system prompt")

    # Content anchor: the output-format section must be present verbatim.
    assert "## 輸出格式" in prompt, "SS text system prompt missing '## 輸出格式'"


@pytest.mark.parametrize(
    "seed,balanced_batch",
    [
        (5, False),   # 隨機模式, seed 5
        (5, True),    # 均衡模式, seed 5
        (42, False),  # 隨機模式, seed 42 (different param draw)
        (42, True),   # 均衡模式, seed 42
    ],
)
def test_ss_text_user_prompt_no_trailing_whitespace(
    tmp_path: Path,
    seed: int,
    balanced_batch: bool,
) -> None:
    """社會領域 文本生成器 user prompt has no trailing-whitespace lines.

    Covers both 出題模式 (balanced_batch axis) and two representative seeds.
    The splice-prone replacement literal is inside build_text_user_prompt; any
    closing-quote drift appends "\\n        " which this test would catch.
    """
    params = ss_sample_params(seed=seed)
    mode = "均衡" if balanced_batch else "隨機"

    prompt, _, _draws = ss_build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(seed),
        balanced_batch=balanced_batch,
    )

    label = f"SS text user prompt (seed={seed}, mode={mode})"
    _assert_no_trailing_whitespace(prompt, label)

    # Content anchor: the last numbered rule of the replacement must appear as
    # a clean line — not followed by a space-prefix on the next line.
    # If the closing triple-quote of the replacement literal drifts one indent
    # level, the replacement string ends with "\n        " and the prompt
    # contains "7. 只輸出 JSON 格式的結果。\n        10." — the "\n " check
    # catches that exact defect class (the original #212 defect shape).
    assert "7. 只輸出 JSON 格式的結果。" in prompt, (
        f"{label}: missing expected content anchor '7. 只輸出 JSON 格式的結果。'"
    )
    assert "7. 只輸出 JSON 格式的結果。\n " not in prompt, (
        f"{label}: trailing indentation artifact after '7. 只輸出 JSON 格式的結果。'"
        " — closing triple-quote of replacement literal may have drifted"
    )


# ===========================================================================
# 社會領域 子題產生器
# ===========================================================================

def test_ss_subquestion_system_prompt_no_trailing_whitespace() -> None:
    """社會領域 子題產生器 system prompt has no trailing-whitespace lines."""
    prompt = ss_build_subquestion_system_prompt(learning_stage="第四學習階段")

    _assert_no_trailing_whitespace(prompt, "SS subquestion system prompt")

    # Content anchor: the curriculum reference section must be present.
    assert "## 課程綱要參考" in prompt, (
        "SS subquestion system prompt missing '## 課程綱要參考'"
    )


@pytest.mark.parametrize("seed", [5, 42])
def test_ss_subquestion_user_prompt_no_trailing_whitespace(
    tmp_path: Path,
    seed: int,
) -> None:
    """社會領域 子題產生器 user prompt has no trailing-whitespace lines."""
    params = ss_sample_params(seed=seed)
    sq_plan = {
        "序號": 1,
        "題型": "選擇題",
        "出題概念": "評量學生能否理解工業革命對社會的影響",
    }

    prompt, _, _draws = ss_build_subquestion_user_prompt(
        核心問題="工業革命如何改變勞動條件？",
        文本="工業革命始於十八世紀英國，改變了生產方式與勞動關係。",
        取材來源=["教科書示範素材"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(seed),
    )

    label = f"SS subquestion user prompt (seed={seed})"
    _assert_no_trailing_whitespace(prompt, label)

    # Content anchor: the 重要提醒 block must be present.
    assert "## 重要提醒" in prompt, f"{label}: missing '## 重要提醒'"


# ===========================================================================
# 自然科學 文本生成器
# ===========================================================================

def test_ns_text_system_prompt_no_trailing_whitespace() -> None:
    """自然科學 文本生成器 system prompt has no trailing-whitespace lines."""
    prompt = ns_build_text_system_prompt()

    _assert_no_trailing_whitespace(prompt, "NS text system prompt")

    # Content anchor: the output-format section must be present.
    assert "## 輸出格式" in prompt, "NS text system prompt missing '## 輸出格式'"


@pytest.mark.parametrize("seed", [5, 42])
def test_ns_text_user_prompt_no_trailing_whitespace(
    tmp_path: Path,
    seed: int,
) -> None:
    """自然科學 文本生成器 user prompt has no trailing-whitespace lines.

    The splice-prone replacement literal is inside build_text_user_prompt; any
    closing-quote drift appends "\\n        " which this test would catch.
    Two seeds provide two different param draws (analogous to two 出題模式
    representative counts).
    """
    params = ns_sample_params(seed=seed)

    prompt, _, _draws = ns_build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(seed),
    )

    label = f"NS text user prompt (seed={seed})"
    _assert_no_trailing_whitespace(prompt, label)

    # Content anchor: the last numbered rule of the replacement must appear as
    # a clean line — not followed by a space-prefix on the next line.
    # If the closing triple-quote of the replacement literal drifts one indent
    # level, the replacement string ends with "\n        " and the prompt
    # contains "7. 只輸出 JSON 格式的結果。\n        9." — the "\n " check
    # catches that exact defect class (parallel to the #212 defect for NS).
    assert "7. 只輸出 JSON 格式的結果。" in prompt, (
        f"{label}: missing expected content anchor '7. 只輸出 JSON 格式的結果。'"
    )
    assert "7. 只輸出 JSON 格式的結果。\n " not in prompt, (
        f"{label}: trailing indentation artifact after '7. 只輸出 JSON 格式的結果。'"
        " — closing triple-quote of replacement literal may have drifted"
    )


# ===========================================================================
# 自然科學 子題產生器
# ===========================================================================

def test_ns_subquestion_system_prompt_no_trailing_whitespace() -> None:
    """自然科學 子題產生器 system prompt has no trailing-whitespace lines."""
    prompt = ns_build_subquestion_system_prompt(learning_stage="第四學習階段")

    _assert_no_trailing_whitespace(prompt, "NS subquestion system prompt")

    # Content anchor: the curriculum reference section must be present.
    assert "## 課程綱要參考" in prompt, (
        "NS subquestion system prompt missing '## 課程綱要參考'"
    )


@pytest.mark.parametrize("seed", [5, 42])
def test_ns_subquestion_user_prompt_no_trailing_whitespace(
    tmp_path: Path,
    seed: int,
) -> None:
    """自然科學 子題產生器 user prompt has no trailing-whitespace lines."""
    params = ns_sample_params(seed=seed)
    sq_plan = {
        "序號": 1,
        "題型": "Simple multiple-choice",
        "出題概念": "評量學生能否以科學角度解釋能量守恆現象",
    }

    prompt, _, _draws = ns_build_subquestion_user_prompt(
        核心問題="能量守恆如何在日常生活中體現？",
        文本="能量守恆定律指出能量不會憑空產生或消失，只會從一種形式轉換為另一種形式。",
        取材來源=["PISA科學素養範例"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(seed),
    )

    label = f"NS subquestion user prompt (seed={seed})"
    _assert_no_trailing_whitespace(prompt, label)

    # Content anchor: the 重要提醒 block must be present.
    assert "## 重要提醒" in prompt, f"{label}: missing '## 重要提醒'"
