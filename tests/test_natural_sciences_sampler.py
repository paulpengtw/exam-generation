"""NS sampler regression tests: grade-aware stage, determinism, validity (issue #91)."""

from __future__ import annotations

import pytest

from src.natural_sciences.curriculum_loader import (
    load_learning_content,
    load_learning_performance,
)
from src.natural_sciences.sampler import sample_params


def test_sample_params_grade_derives_stage_pools():
    """Grades 7-9 draw 第四學習階段 codes; grades 10-12 draw 第五學習階段 codes."""
    lc_stage = {
        e["value"]: e["學習階段"] for e in load_learning_content()["學習內容"]
    }
    lp_stage = {
        e["value"]: e["學習階段"] for e in load_learning_performance()["學習表現"]
    }
    cases = (
        (7, "第四學習階段"),
        (9, "第四學習階段"),
        (10, "第五學習階段"),
        (12, "第五學習階段"),
    )
    for grade, expected_stage in cases:
        p = sample_params(grade=grade, seed=42)
        assert p.學習內容_pool, f"grade={grade}: empty 學習內容_pool"
        assert p.學習表現_pool, f"grade={grade}: empty 學習表現_pool"
        for code in p.學習內容_pool:
            assert lc_stage[code] == expected_stage, (
                f"grade={grade}: 學習內容 {code} is {lc_stage[code]}, "
                f"expected {expected_stage}"
            )
        for code in p.學習表現_pool:
            assert lp_stage[code] == expected_stage, (
                f"grade={grade}: 學習表現 {code} is {lp_stage[code]}, "
                f"expected {expected_stage}"
            )


def test_sample_params_seeded_deterministic():
    """Mirror of tests/test_math_sampler.py::test_sample_params_seeded_deterministic."""
    p1 = sample_params(seed=42)
    p2 = sample_params(seed=42)
    assert p1.grade == p2.grade
    assert [c.value for c in p1.情境] == [c.value for c in p2.情境]
    assert p1.情境子類別.value == p2.情境子類別.value
    assert p1.題型.value == p2.題型.value
    assert [c.value for c in p1.科學能力] == [c.value for c in p2.科學能力]
    assert p1.題目內容類型 == p2.題目內容類型
    assert p1.學習內容_pool == p2.學習內容_pool
    assert p1.學習表現_pool == p2.學習表現_pool


def test_sample_params_identical_across_repeats_many_seeds():
    for seed in range(20):
        assert sample_params(seed=seed).model_dump() == sample_params(seed=seed).model_dump()


def test_sampled_learning_performance_codes_exist_in_curriculum():
    """Issue #91: every sampled 學習表現 code exists in learning_performance.json."""
    lp_values = {e["value"] for e in load_learning_performance()["學習表現"]}
    for seed in range(30):
        p = sample_params(seed=seed)
        assert p.學習表現_pool, f"seed={seed}: empty 學習表現_pool"
        for code in p.學習表現_pool:
            assert code in lp_values, (
                f"seed={seed}: 學習表現 {code} not in learning_performance.json"
            )


def test_sampled_learning_content_codes_exist_in_curriculum():
    """Issue #91: every sampled 學習內容 code exists in learning_content.json."""
    lc_values = {e["value"] for e in load_learning_content()["學習內容"]}
    for seed in range(30):
        p = sample_params(seed=seed)
        assert p.學習內容_pool, f"seed={seed}: empty 學習內容_pool"
        for code in p.學習內容_pool:
            assert code in lc_values, (
                f"seed={seed}: 學習內容 {code} not in learning_content.json"
            )


def test_sample_params_unknown_grade_raises():
    """Mirror of tests/test_math_sampler.py::test_sample_params_unknown_grade_raises."""
    with pytest.raises(ValueError):
        sample_params(grade=99, seed=0)
