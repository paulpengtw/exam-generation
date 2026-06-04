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
    assert params.文本形式.value in {"非連續文本—圖表與圖形", "非連續文本—表格"}


def test_custom_content_type_is_used_as_effective_type(tmp_path) -> None:
    params = sample_params(seed=1, content_type="timeline with source excerpts")

    prompt, _images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert "- **文本素材類型**：timeline with source excerpts" in prompt
    assert "請將題目內容類型視為「timeline with source excerpts」" in prompt
