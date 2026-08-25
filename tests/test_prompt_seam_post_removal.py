"""Prompt-seam regression tests for the ICCS Channel-1 corpus swap.

The three populated Channel-1 keys inject examples through both builders;
unpopulated keys retain the instruction-only fallback. Channel-2 process
exemplar injection remains independent of either Channel-1 state.
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
POPULATED_CONTENT_TYPES = ["純文字", "graphs/charts/tables", "混合"]
UNPOPULATED_CONTENT_TYPES = ["含圖片", "customized", "數位閱讀"]
CONTENT_TYPES = POPULATED_CONTENT_TYPES + UNPOPULATED_CONTENT_TYPES

ICCS_MARKER = "ICCS 題組："
FEW_SHOT_DIR = Path("data/social_studies/few_shot")


@pytest.mark.parametrize("content_type", CONTENT_TYPES)
def test_text_prompt_builder_injects_or_falls_back_by_content_type(
    content_type: str,
) -> None:
    """The text-stage seam reflects whether a live key is populated."""
    params = sample_params(seed=42, content_type=content_type)
    prompt, image_paths = build_text_user_prompt(
        params=params,
        few_shot_dir=FEW_SHOT_DIR,
        rng=random.Random(42),
    )
    if content_type in POPULATED_CONTENT_TYPES:
        assert ICCS_MARKER in prompt
        assert FALLBACK_TEXT not in prompt
        assert all(path.exists() for path in image_paths)
    else:
        assert FALLBACK_TEXT in prompt
        assert image_paths == []


@pytest.mark.parametrize("content_type", CONTENT_TYPES)
def test_subquestion_prompt_builder_injects_or_falls_back_by_content_type(
    content_type: str,
) -> None:
    """The subquestion-stage seam reflects whether a live key is populated."""
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
    if content_type in POPULATED_CONTENT_TYPES:
        assert ICCS_MARKER in prompt
        assert FALLBACK_TEXT not in prompt
        assert all(path.exists() for path in image_paths)
    else:
        assert FALLBACK_TEXT in prompt
        assert image_paths == []


def test_channel2_process_exemplar_injection_still_works() -> None:
    """Channel-2 process-exemplar injection must still fire for a
    (內容領域, 認知歷程)-matched 小題 alongside Channel-1 examples.
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
