"""Contract test for the single-source-of-truth image disclaimer constant."""

from __future__ import annotations

from src.common.image_disclaimer import IMAGE_DISCLAIMER


def test_image_disclaimer_is_verbatim_traditional_chinese() -> None:
    assert IMAGE_DISCLAIMER == "圖片僅為示意，非完全等比例繪製"
    assert isinstance(IMAGE_DISCLAIMER, str)
