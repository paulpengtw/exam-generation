from __future__ import annotations

import random
from pathlib import Path

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.natural_sciences.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as NS_CONTENT_TYPE_INSTRUCTIONS,
)
from src.natural_sciences.context_builder import build_text_user_prompt, build_user_prompt
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schema_loader import load_schemas

# Literal copy of PISA level descriptors — if the data file drifts these tests fail.
_LEVEL_6_DESCRIPTOR = (
    "At level 6, working in unfamiliar contexts, students can draw on a range of scientific"
    " ideas of high demand from different disciplines to build models, consider their"
    " limitations, and use those models to construct or evaluate scientific explanations of"
    " complex phenomena. They can apply those explanations to make predictions not only about"
    " the phenomena but also about potential future developments or implications for society."
    " Students can identify and explain the purposes of particular enquiries of different"
    " types, and which question they are answering. They can apply epistemic and procedural"
    " knowledge to evaluate competing designs of complex enquiries such as experiments, field"
    " studies or simulations and justify their choices of design. They can transform data"
    " from one representation to another and correctly interpret more complex data sets."
    " Students can evaluate the interpretation of data sets drawing on procedural and"
    " epistemic knowledge to make reasoned judgements about their accuracy and precision."
    " Drawing on multiple sources of information of high cognitive demand, containing both"
    " textual and graphical information, students can identify those sources which are most"
    " trustworthy based on one or more scientific criteria or more sophisticated"
    " fact-checking procedures. They can provide a justification for their choice drawing on"
    " content, procedural or epistemic knowledge of science, and/or social, ethical or"
    " economic considerations. In addition, they are able to identify flaws in sources of"
    " scientific information – either in their trustworthiness, their use of data, or in"
    " the arguments from the evidence. Based on their evaluation, they can provide"
    " justifications considering multiple issues for possible decisions and actions."
)

_LEVEL_2_DESCRIPTOR = (
    "At level 2, students can identify an appropriate scientific explanation from a"
    " non-scientific explanation for everyday/common scientific phenomena in familiar"
    " personal, local or global contexts, by drawing on appropriate content knowledge of low"
    " to medium cognitive demand. They can offer a simple explanation of an everyday or"
    " familiar scientific phenomenon such as why you might need a balanced diet that draws on"
    " basic school science concepts. They are able to evaluate designs for simple enquiries"
    " drawing on elements of procedural knowledge and identify appropriate interpretations of"
    " data sets with simple relationships and identify outliers and possible reasons for their"
    " occurrence. Using their epistemic knowledge, they can identify appropriate explanations"
    " for variations in measurement. Given a need for information for decision-making or"
    " action, students can identify relevant sources of information from several of low to"
    " medium cognitive demand, that is needed to inform action on a given scientific problem"
    " and summarise its main argument. Using a single criterion e.g. relevant expertise,"
    " scientific consensus, they can identify whether the source is trustworthy."
)


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


def test_ns_visual_prompts_declare_figure_kind_and_accept_free_text(tmp_path: Path) -> None:
    from src.natural_sciences.context_builder import build_subquestion_user_prompt

    params = sample_params(
        seed=1,
        content_type="含圖片",
        sub_question_count=3,
        subquestion_configs=[{"content_type": "含圖片", "figure_kind": "電路圖"}, {}, {}],
    )
    top_prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    sub_prompt, _ = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["來源A"],
        sq_plan={"序號": 1, "題型": "Simple multiple-choice", "出題概念": "測試"},
        params=params,
        few_shot_dir=Path("data/natural_sciences/few_shot"),
        cfg=params.subquestion_configs[0],
    )

    assert "`figure_kind`" in top_prompt
    assert "電路圖" in top_prompt
    assert "`figure_kind`" in sub_prompt
    assert "圖像種類=電路圖（強制值）" in sub_prompt


# --- Issue #280: 文本生成器 sees target Reporting Scale ---


def test_text_prompt_includes_level6_descriptor_verbatim(tmp_path: Path) -> None:
    """When 題組 targets level 6, the full PISA descriptor must appear verbatim."""
    params = sample_params(seed=1, reporting_scale="6", content_type="純文字")
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert _LEVEL_6_DESCRIPTOR in prompt


def test_text_prompt_level6_excludes_level2_descriptor(tmp_path: Path) -> None:
    """Targeting level 6 must NOT emit all eight descriptors — level-2 text absent."""
    params = sample_params(seed=1, reporting_scale="6", content_type="純文字")
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert _LEVEL_2_DESCRIPTOR not in prompt


def test_text_prompt_per_subquestion_target_level_in_config(tmp_path: Path) -> None:
    """Each 小題's target reporting level appears in the ## 各小題配置 section."""
    params = sample_params(
        seed=1, reporting_scale="6", sub_question_count=3, content_type="純文字"
    )
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 各小題配置" in prompt
    # All three 小題 should show their target level (sampler inherits 題組-level → "6")
    assert prompt.count("目標報告等級=6") >= 3


def test_text_prompt_no_reporting_scale_block_when_none(tmp_path: Path) -> None:
    """When no 題組-level reporting_scale is set, no Reporting Scale block appears."""
    params = sample_params(seed=1, content_type="純文字")
    # Ensure params has no reporting_scale
    assert params.reporting_scale is None  # type: ignore[attr-defined]
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "Reporting Scale" not in prompt
