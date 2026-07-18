"""Tests for the generation-record chart_spec census (issue #110 gate evidence)."""

from __future__ import annotations

from scripts.census_chart_specs import (
    GATE_SUBJECTS,
    render_census_markdown,
    summarize_census,
)


def test_summarize_census_counts_questions_and_specs_per_subject() -> None:
    rows = [
        ("math", {"chart_spec": {"render_mode": "chart", "chart_type": "histogram", "data": {}}}),
        ("math", {"chart_spec": None}),
        (
            "social_studies",
            {
                "subquestions": [
                    {"chart_spec": {"render_mode": "html", "data": {"rows": [], "columns": []}}}
                ]
            },
        ),
    ]
    result = summarize_census(rows, min_per_subject=2)
    assert result.per_subject["math"].questions == 2
    assert result.per_subject["math"].questions_with_spec == 1
    assert result.per_subject["math"].specs_by_category["chart"] == 1
    assert result.per_subject["social_studies"].specs_by_category["table"] == 1
    assert result.per_subject["social_studies"].specs_by_render_mode["html"] == 1


def test_gate_requires_all_three_subjects_at_threshold() -> None:
    assert GATE_SUBJECTS == ("math", "social_studies", "natural_sciences")
    rows = [("math", {})] * 30 + [("social_studies", {})] * 30
    assert summarize_census(rows, min_per_subject=30).gate_met is False
    rows += [("natural_sciences", {})] * 30
    assert summarize_census(rows, min_per_subject=30).gate_met is True


def test_render_census_markdown_lists_subjects_and_gate_status() -> None:
    rows = [
        ("math", {"chart_spec": {"render_mode": "chart", "chart_type": "histogram", "data": {}}}),
    ]
    md = render_census_markdown(summarize_census(rows, min_per_subject=30))
    assert "| math | 1 | 1 |" in md
    # Subjects with zero rows still get a gate row.
    assert "| natural_sciences | 0 | 0 |" in md
    assert "GATE NOT MET" in md
