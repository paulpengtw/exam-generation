from __future__ import annotations

import random
from pathlib import Path

from src.natural_sciences.context_builder import build_user_prompt
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schema_loader import load_schemas


def test_natural_sciences_schema_contains_pisa_science_dimensions() -> None:
    schemas = load_schemas()

    assert schemas["grades"] == [7, 8, 9]
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
