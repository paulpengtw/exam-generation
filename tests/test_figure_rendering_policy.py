"""Classification + dispatch tests for the figure-rendering routing policy.

Source of truth: docs/figure-rendering-policy.md.
"""

from __future__ import annotations

import pytest

from src.context_builder import CONTENT_TYPE_INSTRUCTIONS as MATH_CT
from src.natural_sciences.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as NS_CT,
)
from src.social_studies.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as SS_CT,
)

_SUBJECT_TABLES = [
    pytest.param("math", MATH_CT, id="math"),
    pytest.param("social_studies", SS_CT, id="social_studies"),
    pytest.param("natural_sciences", NS_CT, id="natural_sciences"),
]


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_plain_text_bans_chart_spec(subject: str, table: dict) -> None:
    assert "純文字" in table
    text = table["純文字"]
    assert "chart_spec" in text
    # The policy forbids any chart_spec output for 純文字.
    assert ("不得輸出" in text) or ("不輸出" in text)


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_illustrative_content_routes_to_html(subject: str, table: dict) -> None:
    assert "含圖片" in table
    text = table["含圖片"]
    assert 'render_mode: "html"' in text, (
        f"{subject}: 含圖片 instruction must direct the model to render_mode: \"html\""
    )


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_quantitative_content_routes_to_chart_and_html_for_tables(
    subject: str, table: dict
) -> None:
    assert "graphs/charts/tables" in table
    text = table["graphs/charts/tables"]
    assert 'render_mode: "chart"' in text, (
        f"{subject}: graphs/charts/tables instruction must mention render_mode: \"chart\""
    )
    assert 'render_mode: "html"' in text, (
        f"{subject}: graphs/charts/tables instruction must also mention render_mode: \"html\" for tables"
    )
