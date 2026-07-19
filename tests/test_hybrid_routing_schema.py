"""ImageSpec.render_mode must accept "gpt_image" across all three subjects (issue #110 HYBRID).

Source of truth: docs/figure-rendering-policy.md — Renderer selection matrix.
"""

from __future__ import annotations

import pytest

from src.natural_sciences.schemas import ImageSpec as NsImageSpec
from src.schemas import ImageSpec as MathImageSpec
from src.social_studies.schemas import ImageSpec as SsImageSpec


@pytest.mark.parametrize(
    "cls",
    [MathImageSpec, SsImageSpec, NsImageSpec],
    ids=["math", "social_studies", "natural_sciences"],
)
def test_imagespec_accepts_gpt_image_render_mode(cls) -> None:
    spec = cls(render_mode="gpt_image", description="示意圖")
    assert spec.render_mode == "gpt_image"


@pytest.mark.parametrize(
    "cls",
    [MathImageSpec, SsImageSpec, NsImageSpec],
    ids=["math", "social_studies", "natural_sciences"],
)
def test_imagespec_still_accepts_chart_and_html(cls) -> None:
    for mode in ("chart", "html"):
        spec = cls(render_mode=mode, description="示意圖")
        assert spec.render_mode == mode
