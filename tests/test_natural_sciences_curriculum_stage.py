"""NS grade → 學習階段 mapping (issue #91)."""

from __future__ import annotations

import pytest

from src.natural_sciences.curriculum_loader import (
    grade_to_learning_stage,
    load_learning_content,
)


def test_grade_to_learning_stage_maps_ns_stages():
    assert grade_to_learning_stage(3) == "第二學習階段"
    assert grade_to_learning_stage(4) == "第二學習階段"
    assert grade_to_learning_stage(5) == "第三學習階段"
    assert grade_to_learning_stage(6) == "第三學習階段"
    assert grade_to_learning_stage(7) == "第四學習階段"
    assert grade_to_learning_stage(9) == "第四學習階段"
    assert grade_to_learning_stage(10) == "第五學習階段"
    assert grade_to_learning_stage(12) == "第五學習階段"


def test_grade_to_learning_stage_rejects_grades_without_ns_curriculum():
    for grade in (0, 1, 2, 13):
        with pytest.raises(ValueError):
            grade_to_learning_stage(grade)


def test_grade_to_learning_stage_matches_curriculum_stage_map():
    """Pin the hardcoded mapping against 學習階段_to_grades in the JSON."""
    stage_map = load_learning_content()["學習階段_to_grades"]
    assert stage_map  # data must be present
    for stage, grades in stage_map.items():
        for grade in grades:
            assert grade_to_learning_stage(grade) == stage
