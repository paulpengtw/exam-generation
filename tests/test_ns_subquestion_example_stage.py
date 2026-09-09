"""Issue #288: 子題 prompt example codes must match the request's 學習階段.

Failing tests that pin the bugs before the fix:
- Grade-11 子題 system prompt must not contain 年級 8 or 第四學習階段 codes in example.
- Grade-8 子題 system prompt must not contain 第五學習階段 codes.
- The LC/LP instruction must say 'must not use' codes from other stages, not '應優先使用'.
- The 文本生成器 system prompt example must also follow the request's stage.
"""

from __future__ import annotations

from pathlib import Path

from src.natural_sciences.context_builder import (
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_system_prompt,
    curriculum_texts,
)
from src.natural_sciences.sampler import sample_params

# ---------------------------------------------------------------------------
# 子題產生器 system prompt: example codes must match 學習階段
# ---------------------------------------------------------------------------


def test_subq_sys_prompt_grade11_no_stage4_json_example() -> None:
    """Grade-11 (第五學習階段) 子題 system prompt example must not carry 第四 codes.

    We pass stage-appropriate curriculum text to the function, matching what
    cli.py does in the real pipeline (see test_natural_sciences_cli_stage.py).
    """
    content_text, performance_text = curriculum_texts("第五學習階段")
    prompt = build_subquestion_system_prompt(
        learning_stage="第五學習階段",
        content_text=content_text,
        performance_text=performance_text,
    )
    assert '"年級": 8' not in prompt, (
        "grade-11 prompt must not show 年級 8 in example"
    )
    assert "Ka-Ⅳ-1" not in prompt, (
        "grade-11 prompt must not show Ka-Ⅳ-1 (第四學習階段 LC code)"
    )
    assert "tr-Ⅳ-1" not in prompt, (
        "grade-11 prompt must not show tr-Ⅳ-1 (第四學習階段 LP code)"
    )


def test_subq_sys_prompt_grade8_no_stage5_leakage() -> None:
    """Grade-8 (第四學習階段) 子題 system prompt example must not carry 第五 codes."""
    content_text, performance_text = curriculum_texts("第四學習階段")
    prompt = build_subquestion_system_prompt(
        learning_stage="第四學習階段",
        content_text=content_text,
        performance_text=performance_text,
    )
    assert "BDa-Ⅴa-1" not in prompt, (
        "grade-8 prompt must not show BDa-Ⅴa-1 (第五學習階段 LC code)"
    )
    assert "pa-Ⅴa-1" not in prompt, (
        "grade-8 prompt must not show pa-Ⅴa-1 (第五學習階段 LP code)"
    )


def test_subq_sys_prompt_grade11_example_uses_stage5_codes() -> None:
    """Grade-11 子題 system prompt example must use 第五學習階段 codes."""
    content_text, performance_text = curriculum_texts("第五學習階段")
    prompt = build_subquestion_system_prompt(
        learning_stage="第五學習階段",
        content_text=content_text,
        performance_text=performance_text,
    )
    # Codes from 第五學習階段 pool appear in the example JSON block
    assert "BDa-Ⅴa-1" in prompt, (
        "grade-11 prompt example must contain a 第五學習階段 LC code"
    )
    assert "pa-Ⅴa-1" in prompt, (
        "grade-11 prompt example must contain a 第五學習階段 LP code"
    )


# ---------------------------------------------------------------------------
# 子題產生器 user prompt: LC/LP instruction wording must be hardened
# ---------------------------------------------------------------------------


def test_subq_user_prompt_must_not_wording_grade11() -> None:
    """子題 user prompt must use 'must not' wording, not soft '應優先使用' wording."""
    params = sample_params(grade=11, seed=7)
    prompt, _, _draws = build_subquestion_user_prompt(
        核心問題="test",
        文本="test",
        取材來源=["test"],
        sq_plan={"序號": 1, "題型": "Simple multiple-choice", "出題概念": "test"},
        params=params,
        few_shot_dir=Path("data/natural_sciences/few_shot"),
        disable_reference_fewshot=True,
    )
    assert "應優先使用" not in prompt, (
        "soft '應優先使用' wording must be replaced by hard 'must not' instruction"
    )
    assert "不得" in prompt, (
        "hard '不得' (must not) wording must appear in instruction"
    )


def test_subq_user_prompt_must_not_wording_grade8() -> None:
    """Grade-8 子題 user prompt must also use hardened 'must not' wording."""
    params = sample_params(grade=8, seed=3)
    prompt, _, _draws = build_subquestion_user_prompt(
        核心問題="test",
        文本="test",
        取材來源=["test"],
        sq_plan={"序號": 1, "題型": "Simple multiple-choice", "出題概念": "test"},
        params=params,
        few_shot_dir=Path("data/natural_sciences/few_shot"),
        disable_reference_fewshot=True,
    )
    assert "應優先使用" not in prompt, (
        "soft '應優先使用' wording must be replaced by hard 'must not' instruction"
    )


# ---------------------------------------------------------------------------
# 文本生成器 system prompt: example codes must match 學習階段
# ---------------------------------------------------------------------------


def test_text_sys_prompt_grade11_no_stage4_example() -> None:
    """文本生成器 system prompt for grade-11 must not show 年級 8 or 第四 codes."""
    content_text, performance_text = curriculum_texts("第五學習階段")
    prompt = build_system_prompt(
        grades=[10, 11, 12],
        learning_stage="第五學習階段",
        content_text=content_text,
        performance_text=performance_text,
    )
    assert '"年級": 8' not in prompt, (
        "grade-11 文本生成器 prompt must not show 年級 8 in example"
    )
    assert "Ka-Ⅳ-1" not in prompt, (
        "grade-11 文本生成器 prompt must not show Ka-Ⅳ-1 (第四 LC code)"
    )
    assert "tr-Ⅳ-1" not in prompt, (
        "grade-11 文本生成器 prompt must not show tr-Ⅳ-1 (第四 LP code)"
    )


def test_text_sys_prompt_grade8_no_stage5_leakage() -> None:
    """文本生成器 system prompt for grade-8 must not show 第五學習階段 codes."""
    content_text, performance_text = curriculum_texts("第四學習階段")
    prompt = build_system_prompt(
        grades=[7, 8, 9],
        learning_stage="第四學習階段",
        content_text=content_text,
        performance_text=performance_text,
    )
    assert "BDa-Ⅴa-1" not in prompt, (
        "grade-8 文本生成器 prompt must not show BDa-Ⅴa-1 (第五 LC code)"
    )
    assert "pa-Ⅴa-1" not in prompt, (
        "grade-8 文本生成器 prompt must not show pa-Ⅴa-1 (第五 LP code)"
    )
