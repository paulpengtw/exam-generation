"""Prompt rendering tests for CreativeBrief threading into 文本生成器 (issue #114)."""

from __future__ import annotations

import random

from src.social_studies.context_builder import (
    build_text_system_prompt,
    build_text_user_prompt,
)
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import CreativeBrief


def _brief() -> CreativeBrief:
    return CreativeBrief(
        selected_context="個人",
        題材_angle="以居家防疫日記串起個人與公共衛生決策",
        framing_hooks=["病患日記", "家庭記事本"],
    )


def test_without_brief_prompt_matches_current_template(tmp_path) -> None:
    params = sample_params(seed=7)
    text_before, _, _draws = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "創意取材角度" not in text_before
    assert "## 創意指引" not in text_before


def test_with_brief_rewrites_context_line_in_user_prompt(tmp_path) -> None:
    params = sample_params(seed=7).model_copy(update={"creative_brief": _brief()})
    text, _, _draws = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert (
        "- **情境**：個人（創意取材角度：以居家防疫日記串起個人與公共衛生決策；"
        "參考取材點：病患日記、家庭記事本）"
    ) in text
    assert "## 創意指引" in text
    assert "避免直接複製參考範例的題材" in text
    assert "題材角度：以居家防疫日記串起個人與公共衛生決策" in text


def test_with_brief_but_empty_hooks_omits_參考取材點(tmp_path) -> None:
    brief = CreativeBrief(selected_context="公共", 題材_angle="市議會辯論觀點", framing_hooks=[])
    params = sample_params(seed=7).model_copy(update={"creative_brief": brief})
    text, _, _draws = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "- **情境**：公共（創意取材角度：市議會辯論觀點）" in text
    assert "參考取材點" not in text


def test_system_prompt_appends_創意指引_block_only_with_brief() -> None:
    sys_none = build_text_system_prompt()
    assert "### 創意指引" not in sys_none

    sys_with = build_text_system_prompt(creative_brief=_brief())
    assert "### 創意指引" in sys_with
    assert "情境-題材角度" in sys_with
    assert "不得直接沿用範例題材" in sys_with


def test_user_topic_override_still_wins_over_brief(tmp_path) -> None:
    """A user-typed topic replaces the 情境 line entirely; brief text is not injected."""
    params = sample_params(seed=7).model_copy(update={"creative_brief": _brief()})
    text, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(1),
        user_topic="使用者自訂主題",
    )
    assert "- **情境**：使用者自訂主題" in text
    assert "創意取材角度" not in text
    # 創意指引 section is still appended so the LLM diversifies within the topic.
    assert "## 創意指引" in text
