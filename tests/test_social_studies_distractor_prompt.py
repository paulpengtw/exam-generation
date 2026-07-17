"""Social-studies 子題產生器 prompt + parser wiring for 誘答分析."""

from __future__ import annotations

import random
from pathlib import Path

from src.social_studies.context_builder import (
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
)
from src.social_studies.sampler import sample_params as ss_sample_params


def test_subquestion_system_prompt_contains_distractor_taxonomy() -> None:
    prompt = build_subquestion_system_prompt("第四學習階段")
    assert "誘答分析的設計" in prompt
    assert "誤讀題意" in prompt
    assert "概念混淆" in prompt


def test_subquestion_user_prompt_selection_type_hard_requires_analysis(tmp_path: Path) -> None:
    params = ss_sample_params(seed=1)
    plan = {"序號": 1, "題型": "選擇題", "出題概念": "..."}
    text, _ = build_subquestion_user_prompt(
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


def test_subquestion_user_prompt_constructed_response_marks_optional(tmp_path: Path) -> None:
    params = ss_sample_params(seed=1)
    plan = {"序號": 1, "題型": "開放式建構反應題", "出題概念": "..."}
    text, _ = build_subquestion_user_prompt(
        核心問題="q?",
        文本="passage",
        取材來源=["src"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "常見錯誤" in text


def test_parse_subquestion_populates_distractor_analysis() -> None:
    from src.social_studies.cli import _parse_subquestion

    params = ss_sample_params(seed=1)
    sq_raw = {
        "序號": 1,
        "題型": "選擇題",
        "題目": "問題？(A) x (B) y (C) z (D) w",
        "答案": "B",
        "答案解析": "...",
        "出題概念": "...",
        "科目": ["地理"],
        "誘答分析": {
            "A": "概念混淆",
            "B": "正確答案：y。",
            "C": "誤讀題意",
            "D": "過度推論",
        },
    }
    sq = _parse_subquestion(sq_raw, "q1", params, 1)
    assert sq is not None
    assert sq.誘答分析["A"] == "概念混淆"
    assert sq.誘答分析["B"].startswith("正確答案")


def test_parse_subquestion_defaults_empty_when_missing() -> None:
    from src.social_studies.cli import _parse_subquestion

    params = ss_sample_params(seed=1)
    sq_raw = {
        "序號": 1, "題型": "選擇題", "題目": "Q", "答案": "A",
        "答案解析": "...", "出題概念": "...", "科目": ["地理"],
    }
    sq = _parse_subquestion(sq_raw, "q1", params, 1)
    assert sq is not None
    assert sq.誘答分析 == {}
