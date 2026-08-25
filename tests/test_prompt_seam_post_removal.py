"""Red-first prompt-seam test for #542: PISA-reading corpus removal.

After removal every 題目內容類型 key must yield the instruction-only fallback
（目前暫無範例，請根據指定條件自行設計。）from BOTH prompt builders, and
Channel-2 process-exemplar injection must still fire for a matched 小題.

This test is written BEFORE the corpus is removed; it will fail (red) against
the current populated corpus because Channel-1 examples exist and the fallback
text will NOT appear. After removal it turns green.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from src.social_studies.context_builder import (
    build_subquestion_user_prompt,
    build_text_user_prompt,
)
from src.social_studies.sampler import sample_params

FALLBACK_TEXT = "（目前暫無範例，請根據指定條件自行設計。）"

# All six 題目內容類型 keys defined by the loader convention
CONTENT_TYPES = [
    "純文字",
    "含圖片",
    "graphs/charts/tables",
    "customized",
    "混合",
    "數位閱讀",
]

FEW_SHOT_DIR = Path("data/social_studies/few_shot")


@pytest.mark.parametrize("content_type", CONTENT_TYPES)
def test_text_prompt_builder_emits_fallback_for_every_content_type(
    content_type: str,
) -> None:
    """build_text_user_prompt must emit the instruction-only fallback when
    Channel-1 corpus is empty for every 題目內容類型 key."""
    params = sample_params(seed=42, content_type=content_type)
    prompt, image_paths = build_text_user_prompt(
        params=params,
        few_shot_dir=FEW_SHOT_DIR,
        rng=random.Random(42),
    )
    assert FALLBACK_TEXT in prompt, (
        f"Expected instruction-only fallback for content_type={content_type!r}, "
        f"but got prompt excerpt: {prompt[prompt.find('範例') - 50: prompt.find('範例') + 200]!r}"
    )
    assert image_paths == [], (
        f"Expected no image paths after corpus removal, got {image_paths}"
    )


@pytest.mark.parametrize("content_type", CONTENT_TYPES)
def test_subquestion_prompt_builder_emits_fallback_for_every_content_type(
    content_type: str,
) -> None:
    """build_subquestion_user_prompt must emit the instruction-only fallback
    when Channel-1 corpus is empty for every 題目內容類型 key."""
    params = sample_params(seed=42, content_type=content_type)
    sq_plan = {"序號": 1, "題型": "選擇題", "認知歷程": "Knowing–Defining and Describing"}
    prompt, image_paths = build_subquestion_user_prompt(
        核心問題="什麼是公民責任？",
        文本="公民參與社區事務是民主社會的基礎。",
        取材來源=["測試素材"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=FEW_SHOT_DIR,
        rng=random.Random(42),
    )
    assert FALLBACK_TEXT in prompt, (
        f"Expected instruction-only fallback for content_type={content_type!r}, "
        f"but got prompt snippet containing: "
        f"{prompt[max(0, prompt.find('範例') - 50): prompt.find('範例') + 200]!r}"
    )
    assert image_paths == [], (
        f"Expected no image paths after corpus removal, got {image_paths}"
    )


def test_channel2_process_exemplar_injection_still_works() -> None:
    """Channel-2 process-exemplar injection must still fire for a
    (內容領域, 認知歷程)-matched 小題 after Channel-1 is cleared.
    Verify a known cognitive_process bucket produces the ICCS exemplar section
    in the subquestion prompt (it reads from process_exemplars/, not Channel-1).
    """
    params = sample_params(seed=1, content_type="純文字")
    sq_plan = {
        "序號": 1,
        "題型": "選擇題",
        "認知歷程": "Knowing–Defining and Describing",
        "出題概念": "公民責任的定義",
    }
    prompt, _images = build_subquestion_user_prompt(
        核心問題="公民責任的核心是什麼？",
        文本="民主社會中公民享有權利也負有責任。",
        取材來源=["ICCS測試"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=FEW_SHOT_DIR,
        rng=random.Random(1),
    )
    # Channel-2 section header appears in the prompt when an exemplar is found
    # The process exemplar loader injects a "認知歷程參考範例（Channel 2：…）" section
    assert "Channel 2" in prompt, (
        "Channel-2 process-exemplar injection should still produce a "
        "'認知歷程參考範例（Channel 2：…）' section in the subquestion prompt; "
        f"prompt snippet: {prompt[-500:]!r}"
    )
