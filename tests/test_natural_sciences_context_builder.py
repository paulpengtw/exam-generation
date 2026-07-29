from __future__ import annotations

import random
from pathlib import Path

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.natural_sciences.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as NS_CONTENT_TYPE_INSTRUCTIONS,
)
from src.natural_sciences.context_builder import build_user_prompt
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schema_loader import load_schemas


def test_natural_sciences_schema_contains_pisa_science_dimensions() -> None:
    schemas = load_schemas()

    assert schemas["grades"] == [7, 8, 9, 10, 11, 12]
    assert [entry["value"] for entry in schemas["情境"]] == [
        "Personal",
        "Local and national",
        "Global",
    ]
    assert [entry["value"] for entry in schemas["題型種類"]] == ["題組題"]
    assert [entry["value"] for entry in schemas["題型"]] == [
        "Simple multiple-choice",
        "Complex multiple-choice",
        "Constructed response",
    ]
    assert len(schemas["科學能力"]) == 6
    assert any(entry.get("parent") == "Personal" for entry in schemas["情境子類別"])


def test_natural_sciences_sampler_keeps_subcontext_under_context() -> None:
    params = sample_params(seed=1)
    schemas = load_schemas()
    parent_by_subcontext = {
        entry["value"]: entry.get("parent")
        for entry in schemas["情境子類別"]
    }

    assert parent_by_subcontext[params.情境子類別.value] in {c.value for c in params.情境}
    assert params.題型種類.value == "題組題"
    assert params.科學能力
    assert params.學習表現_pool


def test_natural_sciences_prompt_includes_pisa_and_curriculum(tmp_path: Path) -> None:
    params = sample_params(seed=1, content_type="純文字")

    prompt, images = build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert images == []
    assert "PISA Science" in prompt
    assert "- **情境子類別**：" in prompt
    assert "- **科學能力**：" in prompt
    assert "- **指定學習內容**：" in prompt
    assert "- **指定學習表現**：" in prompt
    assert "不得輸出 `chart_spec`" in prompt


def test_subquestion_prompt_replays_few_shot_selection_from_sampled_seed() -> None:
    from src.natural_sciences.context_builder import build_subquestion_user_prompt

    params = sample_params(seed=185, q_type=["Simple multiple-choice"])
    kwargs = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": ["來源A"],
        "sq_plan": {
            "序號": 1,
            "題型": "Simple multiple-choice",
            "出題概念": "測試",
        },
        "params": params,
        "few_shot_dir": Path("data/natural_sciences/few_shot"),
    }

    prompts = [build_subquestion_user_prompt(**kwargs)[0] for _ in range(5)]

    assert len(set(prompts)) == 1


def test_ns_content_type_instructions_include_disclaimer_for_image_types() -> None:
    assert IMAGE_DISCLAIMER in NS_CONTENT_TYPE_INSTRUCTIONS["含圖片"]
    assert IMAGE_DISCLAIMER in NS_CONTENT_TYPE_INSTRUCTIONS["graphs/charts/tables"]


def test_ns_content_type_instructions_omit_disclaimer_for_text_only() -> None:
    assert IMAGE_DISCLAIMER not in NS_CONTENT_TYPE_INSTRUCTIONS["純文字"]


def test_ns_user_prompt_carries_disclaimer_for_image_content_type(tmp_path) -> None:
    params = sample_params(seed=1, content_type="含圖片")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER in prompt


def test_ns_user_prompt_carries_disclaimer_for_graphs_charts_tables(tmp_path) -> None:
    params = sample_params(seed=1, content_type="graphs/charts/tables")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER in prompt


def test_ns_user_prompt_omits_disclaimer_for_text_only(tmp_path) -> None:
    params = sample_params(seed=1, content_type="純文字")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER not in prompt
