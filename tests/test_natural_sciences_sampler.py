"""NS sampler regression tests: grade-aware stage, determinism, validity (issue #91)."""

from __future__ import annotations

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
