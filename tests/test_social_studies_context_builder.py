from __future__ import annotations

import random

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.social_studies.cli import _figure_kind_repair_instruction
from src.social_studies.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as SS_CONTENT_TYPE_INSTRUCTIONS,
)
from src.social_studies.context_builder import (
    build_subquestion_system_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
    build_user_prompt,
)
from src.social_studies.context_builder import (
    build_system_prompt as ss_build_system_prompt,
)
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import CoreCompetency


def test_topic_replaces_context_in_social_studies_prompt(tmp_path) -> None:
    params = sample_params(seed=1)

    prompt, images = build_user_prompt(
        params,
        tmp_path,
        rng=random.Random(1),
        user_topic="氣候變遷與都市規劃",
    )

    assert images == []
    assert "- **情境**：氣候變遷與都市規劃" in prompt
    assert "## 指定情境" in prompt
    assert "主題 / 議題：氣候變遷與都市規劃" in prompt


def test_social_text_prompt_offers_only_pinned_core_competencies(tmp_path) -> None:
    params = sample_params(
        seed=7,
        core_competency=[CoreCompetency("社-J-A2")],
        content_type="純文字",
    )

    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "- **核心素養（限定使用）**：社-J-A2" in prompt
    assert "社-J-C2" not in prompt


def test_plain_text_content_type_forbids_chart_spec(tmp_path) -> None:
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


def test_global_image_content_type_requires_top_level_visual_spec(tmp_path) -> None:
    params = sample_params(seed=1, content_type="含圖片")

    prompt, _images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "- **文本素材類型**：含圖片" in prompt
    assert "全域 `文本素材類型` 是 `含圖片` 或 `graphs/charts/tables`" in prompt
    assert "必須在題組 JSON 頂層輸出非 null 的 `chart_spec`" in prompt
    assert "不能取代全域 `文本素材類型` 要求的題組頂層 `chart_spec`" in prompt


def test_social_visual_drafting_and_repair_prompts_require_declared_figure_kind(
    tmp_path,
) -> None:
    params = sample_params(seed=1, content_type="含圖片")

    drafting_user, _images = build_user_prompt(
        params,
        tmp_path,
        rng=random.Random(1),
    )
    drafting_system = build_text_system_prompt(params=params)
    subquestion_system = build_subquestion_system_prompt("第四")
    repair_guidance = _figure_kind_repair_instruction(params)

    for prompt in (drafting_user, drafting_system, subquestion_system, repair_guidance):
        assert "每個視覺素材規格" in prompt
        assert "圖像種類" in prompt
        assert "直方圖" in prompt
        assert "自由文字" in prompt


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
                "instruction": "請聚焦在資料判讀與因果推論",
            },
            {
                "question_type": "開放式建構反應題",
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
    assert "第1小題：題型=選擇題" in prompt
    assert "出題指示=請聚焦在資料判讀與因果推論" in prompt
    assert "文本素材類型=含圖片，圖片生成模式=gpt_image" in prompt
    assert "題目字數上限=80，選項字數上限=30" in prompt
    assert (
        "第2小題：題型=開放式建構反應題，文本素材類型=純文字，"
        "圖片生成模式=html，題目字數上限=120"
    ) in prompt
    assert "第3小題：題型=" in prompt
    assert (
        "第3小題：題型=選擇題，"
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


def test_build_subquestion_user_prompt_explicit_lc_lp_uses_cfg():
    """Explicit per-子題 LC/LP appears in prompt with hard wording."""
    import random

    from src.social_studies.context_builder import build_subquestion_user_prompt
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import SubQuestionConfig

    rng = random.Random(42)
    params = sample_params(seed=rng.randrange(2**32), content_type="純文字")
    cfg = SubQuestionConfig(learning_content=["歷Ka-Ⅳ-1"], learning_performance=["社1b-Ⅳ-1"])
    sq_plan = {"序號": 1, "題型": "選擇題", "出題概念": "測試"}
    import pathlib
    few_shot_dir = pathlib.Path("data/social_studies/few_shot")
    prompt, _ = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["來源A"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=few_shot_dir,
        rng=rng,
        cfg=cfg,
    )
    assert "歷Ka-Ⅳ-1" in prompt
    assert "社1b-Ⅳ-1" in prompt
    assert "不得替換或新增" in prompt


def test_build_subquestion_user_prompt_empty_cfg_uses_global_pool():
    """Empty per-子題 cfg falls back to global pool header (no hard wording)."""
    import pathlib
    import random

    from src.social_studies.context_builder import build_subquestion_user_prompt
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import SubQuestionConfig

    rng = random.Random(42)
    params = sample_params(seed=rng.randrange(2**32), content_type="純文字")
    cfg = SubQuestionConfig()  # empty
    sq_plan = {"序號": 1, "題型": "選擇題", "出題概念": "測試"}
    few_shot_dir = pathlib.Path("data/social_studies/few_shot")
    prompt, _ = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["來源A"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=few_shot_dir,
        rng=rng,
        cfg=cfg,
    )
    assert "不得替換或新增" not in prompt


def test_subquestion_prompt_replays_few_shot_selection_from_sampled_seed() -> None:
    from pathlib import Path

    from src.social_studies.context_builder import build_subquestion_user_prompt

    params = sample_params(seed=185, q_type=["選擇題"], content_type="純文字")
    kwargs = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": ["來源A"],
        "sq_plan": {"序號": 1, "題型": "選擇題", "出題概念": "測試"},
        "params": params,
        "few_shot_dir": Path("data/social_studies/few_shot"),
    }

    prompts = [build_subquestion_user_prompt(**kwargs)[0] for _ in range(5)]

    assert len(set(prompts)) == 1


def test_ss_content_type_instructions_include_disclaimer_for_image_types() -> None:
    assert IMAGE_DISCLAIMER in SS_CONTENT_TYPE_INSTRUCTIONS["含圖片"]
    assert IMAGE_DISCLAIMER in SS_CONTENT_TYPE_INSTRUCTIONS["graphs/charts/tables"]


def test_social_studies_loads_canonical_figure_kind_vocabulary() -> None:
    from src.social_studies.figure_kind_loader import CANONICAL_FIGURE_KINDS

    assert "直方圖" in CANONICAL_FIGURE_KINDS
    assert "地圖" in CANONICAL_FIGURE_KINDS
    assert "實驗裝置" in CANONICAL_FIGURE_KINDS


def test_visual_prompts_steer_distinct_figure_kinds_and_show_known_pins(tmp_path) -> None:
    params = sample_params(
        seed=1,
        content_type="含圖片",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "figure_kind": "地圖"},
            {"content_type": "含圖片", "figure_kind": "表格"},
            {"content_type": "含圖片"},
        ],
    )

    parent_prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    sub_prompt, _ = __import__(
        "src.social_studies.context_builder",
        fromlist=["build_subquestion_user_prompt"],
    ).build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本={"文本": "測試文本", "chart_spec": {"render_mode": "html", "figure_kind": "廣告"}},
        取材來源=["來源A"],
        sq_plan={"序號": 3, "題型": "選擇題", "出題概念": "測試"},
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
        cfg=params.subquestion_configs[2],
    )

    assert "圖像種類" in parent_prompt
    assert "圖像種類不得重複" in parent_prompt
    assert "直方圖、長條圖、盒鬚圖" in parent_prompt
    assert "已使用圖像種類" in sub_prompt
    assert "廣告" in sub_prompt
    assert "地圖" in sub_prompt
    assert "canonical vocabulary 選擇" in build_subquestion_system_prompt("第四")


def test_visual_prompts_drop_hard_diversity_wording_when_kill_switch_is_on(tmp_path) -> None:
    params = sample_params(
        seed=1,
        content_type="含圖片",
        allow_duplicate_figure_kinds=True,
    )

    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "圖像種類不得重複" not in prompt
    assert "圖像種類不得重複" not in build_text_system_prompt(params=params)


def test_ss_content_type_instructions_omit_disclaimer_for_plain_text() -> None:
    assert IMAGE_DISCLAIMER not in SS_CONTENT_TYPE_INSTRUCTIONS["純文字"]


def test_ss_html_designer_guidance_carries_disclaimer() -> None:
    prompt = ss_build_system_prompt()
    assert "HTML排版素材" in prompt
    assert IMAGE_DISCLAIMER in prompt


def test_ss_user_prompt_carries_disclaimer_for_image_content_type(tmp_path) -> None:
    params = sample_params(seed=1, content_type="含圖片")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER in prompt


def test_ss_user_prompt_omits_disclaimer_for_plain_text(tmp_path) -> None:
    params = sample_params(seed=1, content_type="純文字")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER not in prompt
