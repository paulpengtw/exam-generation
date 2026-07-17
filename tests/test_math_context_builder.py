"""Math prompt must warn generators/solvers that figures are illustrative."""

from __future__ import annotations

import random
from pathlib import Path

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS,
    build_system_prompt,
    build_user_prompt,
)
from src.sampler import sample_params


def test_math_content_type_instructions_include_disclaimer_for_image_types() -> None:
    assert IMAGE_DISCLAIMER in CONTENT_TYPE_INSTRUCTIONS["含圖片"]
    assert IMAGE_DISCLAIMER in CONTENT_TYPE_INSTRUCTIONS["graphs/charts/tables"]


def test_math_content_type_instructions_omit_disclaimer_for_text_only() -> None:
    assert IMAGE_DISCLAIMER not in CONTENT_TYPE_INSTRUCTIONS["純文字"]


def test_math_html_designer_guidance_carries_disclaimer() -> None:
    prompt = build_system_prompt()
    # Phrase must appear inside the render_mode: "html" guidance block.
    assert 'render_mode: "html"' in prompt
    assert IMAGE_DISCLAIMER in prompt


def test_math_user_prompt_carries_disclaimer_when_content_type_is_image(
    tmp_path: Path,
) -> None:
    params = sample_params(seed=1, content_type="含圖片")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER in prompt


def test_math_user_prompt_omits_disclaimer_when_content_type_is_text(
    tmp_path: Path,
) -> None:
    params = sample_params(seed=1, content_type="純文字")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER not in prompt
