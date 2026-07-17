"""Single source of truth for the exam-image "figure is illustrative" disclaimer.

Every prompt fragment that can cause an image to be rendered — math /
social-studies / natural-sciences content-type blocks, the `render_mode: "html"`
HTML-designer guidance, and the three verifier system prompts — imports this
constant so the phrase is defined verbatim in exactly one place. Tests import
it too, so a future rewording only needs to happen here.
"""

from __future__ import annotations

IMAGE_DISCLAIMER: str = "圖片僅為示意，非完全等比例繪製"

__all__ = ["IMAGE_DISCLAIMER"]
