"""Tests for the shared parse_image_spec function in src/common/image_spec_parsing.py.

Issue #633: verify the public signature and all three rung behaviours for both
subject ImageSpec models.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helper to parametrize over both subjects
# ---------------------------------------------------------------------------


def _subject_model(subject: str):
    if subject == "ss":
        from src.social_studies.schemas import ImageSpec
        return ImageSpec
    from src.natural_sciences.schemas import ImageSpec
    return ImageSpec


# ---------------------------------------------------------------------------
# Basic: non-dict returns None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_parse_image_spec_returns_none_for_non_dict(subject: str) -> None:
    from src.common.image_spec_parsing import parse_image_spec
    model_cls = _subject_model(subject)
    assert parse_image_spec(None, model_cls) is None
    assert parse_image_spec("html", model_cls) is None
    assert parse_image_spec(["a", "b"], model_cls) is None
    assert parse_image_spec(42, model_cls) is None


# ---------------------------------------------------------------------------
# Rung 1: valid spec passes through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_parse_image_spec_rung1_valid_spec(subject: str) -> None:
    from src.common.image_spec_parsing import parse_image_spec
    model_cls = _subject_model(subject)
    spec = parse_image_spec(
        {"render_mode": "chart", "chart_type": "histogram", "data": {"甲": 10}},
        model_cls,
    )
    assert spec is not None
    assert spec.render_mode == "chart"
    assert spec.chart_type == "histogram"
    assert spec.data == {"甲": 10}


# ---------------------------------------------------------------------------
# Rung 3 (no chart_type): bad render_mode → html fallback preserves html
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_parse_image_spec_rung3_html_fallback_preserves_html_field(subject: str) -> None:
    from src.common.image_spec_parsing import parse_image_spec
    model_cls = _subject_model(subject)
    spec = parse_image_spec(
        {
            "render_mode": "pdf",   # invalid
            "figure_kind": "地圖",
            "title": "示意圖",
            "data": {"甲": 10},
            "html": "<table>test</table>",
        },
        model_cls,
    )
    assert spec is not None
    assert spec.render_mode == "html"
    assert spec.html == "<table>test</table>"
    assert spec.figure_kind == "地圖"


# ---------------------------------------------------------------------------
# Rung 2 fails → None (does NOT fall through to HTML rung)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_parse_image_spec_returns_none_when_chart_type_rung_fails(subject: str) -> None:
    from src.common.image_spec_parsing import parse_image_spec
    model_cls = _subject_model(subject)
    spec = parse_image_spec(
        {
            "render_mode": "pdf",       # invalid → rung 1 fails
            "chart_type": "bar_chart",  # invalid → rung 2 fails → stop
            "figure_kind": "統計圖",
            "data": {"甲": 10},
        },
        model_cls,
    )
    assert spec is None
