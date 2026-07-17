"""Natural-sciences verifier must not fail a question purely because the figure is 示意圖."""

from __future__ import annotations

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.natural_sciences.verifier import VERIFICATION_SYSTEM_PROMPT


def test_natural_sciences_verifier_prompt_contains_illustrative_figure_leniency_line() -> None:
    assert "示意圖" in VERIFICATION_SYSTEM_PROMPT
    assert IMAGE_DISCLAIMER in VERIFICATION_SYSTEM_PROMPT
    assert "不得僅因" in VERIFICATION_SYSTEM_PROMPT
    assert "數值" in VERIFICATION_SYSTEM_PROMPT
    assert "標籤" in VERIFICATION_SYSTEM_PROMPT
