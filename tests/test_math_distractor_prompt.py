"""Math prompts and parser wiring for 誘答分析 (issue #115)."""

from __future__ import annotations

import random
from pathlib import Path

from src.context_builder import build_system_prompt, build_user_prompt
from src.sampler import sample_params


def test_math_system_prompt_contains_distractor_guidance() -> None:
    system = build_system_prompt()
    assert "誘答分析的設計" in system
    assert "誘讀題意" in system or "誤讀題意" in system
    assert "概念混淆" in system
    assert "\"誘答分析\"" in system or "誘答分析" in system


def test_math_user_prompt_mc_type_hard_requires_distractor_analysis(tmp_path: Path) -> None:
    params = sample_params(seed=1, q_type=["選擇題"])
    text, _, _draws = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "誘答分析" in text
    assert "必須" in text  # hard requirement phrasing


def test_math_user_prompt_true_false_hard_requires_distractor_analysis(tmp_path: Path) -> None:
    params = sample_params(seed=1, q_type=["是非題"])
    text, _, _draws = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "誘答分析" in text
    assert "「是」" in text or "是/非" in text  # keys hint


def test_math_user_prompt_open_response_marks_distractor_optional(tmp_path: Path) -> None:
    params = sample_params(seed=1, q_type=["開放式建構反應題"])
    text, _, _draws = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "常見錯誤" in text  # optional key hint


def test_parse_question_populates_distractor_analysis() -> None:
    from src.cli import _parse_question
    from src.schemas import SampledParams
    from src.sampler import sample_params

    params: SampledParams = sample_params(seed=42, q_type=["選擇題"])
    raw = {
        "情境": [c.value for c in params.情境],
        "題型種類": params.題型種類.value,
        "題型": params.題型.value,
        "數學思考": [t.value for t in params.數學思考],
        "學習內容": [],
        "題目": ["Q?", "(A) 3", "(B) 4", "(C) 5", "(D) 6"],
        "正確解題分析": ["B"],
        "誘答分析": {"A": "誤讀題意", "B": "正確答案：4。", "C": "概念混淆", "D": "過度推論"},
    }
    q = _parse_question(raw, "q-test", params, "test-model")
    assert q.誘答分析["A"] == "誤讀題意"
    assert q.誘答分析["B"].startswith("正確答案")


def test_parse_question_defaults_to_empty_dict_when_missing() -> None:
    from src.cli import _parse_question
    from src.sampler import sample_params

    params = sample_params(seed=42, q_type=["選擇題"])
    raw = {
        "情境": [c.value for c in params.情境],
        "題型種類": params.題型種類.value,
        "題型": params.題型.value,
        "數學思考": [t.value for t in params.數學思考],
        "學習內容": [],
        "題目": ["Q?"],
        "正確解題分析": ["A"],
    }
    q = _parse_question(raw, "q-test", params, "test-model")
    assert q.誘答分析 == {}
