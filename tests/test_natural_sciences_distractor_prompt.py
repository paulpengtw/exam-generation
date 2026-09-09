"""Natural-sciences 子題產生器 prompt + parser wiring for 誘答分析."""

from __future__ import annotations

import random
from pathlib import Path

from src.natural_sciences.context_builder import (
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
)
from src.natural_sciences.sampler import sample_params as ns_sample_params


def test_ns_system_prompt_contains_distractor_taxonomy() -> None:
    prompt = build_subquestion_system_prompt("第四學習階段")
    assert "誘答分析的設計" in prompt
    assert "概念混淆" in prompt


def test_ns_user_prompt_simple_mc_hard_requires_analysis(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1, q_type=["Simple multiple-choice"])
    plan = {"序號": 1, "題型": "Simple multiple-choice", "出題概念": "..."}
    text, _, _draws = build_subquestion_user_prompt(
        核心問題="q?",
        文本="passage",
        取材來源=["src"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "誘答分析" in text
    assert "必須" in text


def test_ns_user_prompt_complex_mc_hard_requires_analysis(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1, q_type=["Complex multiple-choice"])
    plan = {"序號": 1, "題型": "Complex multiple-choice", "出題概念": "..."}
    text, _, _draws = build_subquestion_user_prompt(
        核心問題="q?",
        文本="passage",
        取材來源=["src"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "誘答分析" in text


def test_ns_user_prompt_constructed_response_marks_optional(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1, q_type=["Constructed response"])
    plan = {"序號": 1, "題型": "Constructed response", "出題概念": "..."}
    text, _, _draws = build_subquestion_user_prompt(
        核心問題="q?",
        文本="passage",
        取材來源=["src"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "常見錯誤" in text


def test_ns_parse_subquestion_populates_and_defaults_distractor_analysis() -> None:
    from src.natural_sciences.cli import _parse_subquestion

    params = ns_sample_params(seed=1, q_type=["Simple multiple-choice"])
    sq_raw = {
        "序號": 1,
        "題型": "Simple multiple-choice",
        "題目": "Q? (A) x (B) y (C) z (D) w",
        "答案": "B",
        "答案解析": "...",
        "出題概念": "...",
        "科目": ["自然科學"],
        "誘答分析": {
            "A": "概念混淆",
            "B": "正確答案：y。",
            "C": "誤讀題意",
            "D": "過度推論",
        },
    }
    sq = _parse_subquestion(sq_raw, "q1", params, 1)
    assert sq is not None
    assert sq.誘答分析["C"] == "誤讀題意"

    sq_raw_2 = dict(sq_raw)
    sq_raw_2.pop("誘答分析")
    sq2 = _parse_subquestion(sq_raw_2, "q1", params, 1)
    assert sq2 is not None
    assert sq2.誘答分析 == {}
