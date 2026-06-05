from __future__ import annotations

import random

from src.social_studies.context_builder import build_user_prompt
from src.social_studies.sampler import sample_params


def test_topic_replaces_context_in_social_studies_prompt(tmp_path) -> None:
    params = sample_params(seed=1)

    prompt, images = build_user_prompt(
        params,
        tmp_path,
        rng=random.Random(1),
        user_topic="氣候變遷與都市規劃",
    )

    assert images == []
    assert "- **情境**：氣候變遷與都市規劃（PISA閱讀情境）" in prompt
    assert "## 指定情境（請直接取代原本的 PISA 情境）" in prompt
    assert "主題 / 議題：氣候變遷與都市規劃" in prompt


def test_text_only_content_type_forbids_chart_spec(tmp_path) -> None:
    params = sample_params(seed=1, content_type="純文字")

    prompt, images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert images == []
    assert "- **文本素材類型**：純文字" in prompt
    assert "不得輸出 `chart_spec`" in prompt


def test_graph_chart_table_content_type_requires_visual_spec(tmp_path) -> None:
    params = sample_params(seed=1, content_type="graphs/charts/tables")

    prompt, _images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "- **文本素材類型**：graphs/charts/tables" in prompt
    assert "本題組必須包含圖表或表格素材" in prompt
    assert "題組頂層輸出非 null 的 `chart_spec`" in prompt
    assert params.文本形式.value in {"非連續文本—圖表與圖形", "非連續文本—表格"}


def test_global_image_content_type_requires_top_level_visual_spec(tmp_path) -> None:
    params = sample_params(seed=1, content_type="含圖片")

    prompt, _images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "- **文本素材類型**：含圖片" in prompt
    assert "全域 `文本素材類型` 是 `含圖片` 或 `graphs/charts/tables`" in prompt
    assert "必須在題組 JSON 頂層輸出非 null 的 `chart_spec`" in prompt
    assert "不能取代全域 `文本素材類型` 要求的題組頂層 `chart_spec`" in prompt


def test_custom_content_type_is_used_as_effective_type(tmp_path) -> None:
    params = sample_params(seed=1, content_type="timeline with source excerpts")

    prompt, _images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "- **文本素材類型**：timeline with source excerpts" in prompt
    assert "請將題目內容類型視為「timeline with source excerpts」" in prompt


def test_per_subquestion_config_is_rendered_in_prompt(tmp_path) -> None:
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {
                "question_type": "選擇題",
                "content_type": "含圖片",
                "image_generation_mode": "gpt_image",
                "question_word_limit": 80,
                "option_word_limit": 30,
            },
            {
                "question_type": "封閉式建構反應題",
                "content_type": "純文字",
                "question_word_limit": 120,
            },
            {"content_type": "graphs/charts/tables", "image_generation_mode": "html"},
        ],
    )

    prompt, _images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "- **題型**：由各小題配置指定" in prompt
    assert "- **小題數量**：3" in prompt
    assert "## 各小題配置" in prompt
    assert (
        "第1小題：題型=選擇題，文本素材類型=含圖片，圖片生成模式=gpt_image，"
        "題目字數上限=80，選項字數上限=30"
    ) in prompt
    assert (
        "第2小題：題型=封閉式建構反應題，文本素材類型=純文字，"
        "圖片生成模式=html，題目字數上限=120"
    ) in prompt
    assert "第3小題：題型=" in prompt
    assert (
        "第3小題：題型=開放式建構反應題，"
        "文本素材類型=graphs/charts/tables，圖片生成模式=html"
    ) in prompt
    assert (
        "文本素材類型為 `含圖片` 或 `graphs/charts/tables` 的小題必須輸出"
        "該小題自己的 `chart_spec`"
    ) in prompt
    assert "`image_generation_mode` 只指定渲染方式，不能單獨視為需要圖片" in prompt


def test_per_subquestion_config_renders_inherited_image_mode(tmp_path) -> None:
    params = sample_params(
        seed=1,
        content_type="含圖片",
        sub_question_count=3,
        subquestion_configs=[
            {"image_generation_mode": "html"},
            {"content_type": "graphs/charts/tables"},
            {"question_word_limit": 120},
        ],
    )

    prompt, _images = build_user_prompt(
        params,
        tmp_path,
        rng=random.Random(1),
        image_generation_mode="gpt_image",
    )

    assert "- **圖片生成模式**：gpt_image" in prompt
    assert "第1小題：題型=" in prompt
    assert "文本素材類型=含圖片，圖片生成模式=html" in prompt
    assert "第2小題：題型=" in prompt
    assert "文本素材類型=graphs/charts/tables，圖片生成模式=gpt_image" in prompt
    assert "第3小題：題型=" in prompt
    assert "文本素材類型=含圖片，圖片生成模式=gpt_image，題目字數上限=120" in prompt


def test_legacy_global_word_limits_render_when_no_row_config(tmp_path) -> None:
    params = sample_params(seed=1, question_word_limit=90, option_word_limit=20)

    prompt, _images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "## 各小題配置" in prompt
    assert "每道小題題目字數上限：90 字" in prompt
    assert "每個選項字數上限：20 字（限選擇題）" in prompt


def test_missing_subquestion_question_types_are_sampled(tmp_path) -> None:
    params = sample_params(
        seed=2,
        sub_question_count=3,
        subquestion_configs=[
            {"question_type": "選擇題"},
            {},
            {"question_word_limit": 60},
        ],
    )

    assert len(params.subquestion_configs) == 3
    sampled_types = [
        cfg.question_type.value for cfg in params.subquestion_configs if cfg.question_type
    ]
    assert sampled_types[0] == "選擇題"
    assert all(cfg.question_type is not None for cfg in params.subquestion_configs)

    prompt, _images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "第1小題：題型=選擇題" in prompt
    assert "第2小題：題型=" in prompt
    assert "第3小題：題型=" in prompt
