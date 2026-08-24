"""Guard the live social-studies surfaces against retired PISA-axis authoring."""

from __future__ import annotations

import csv
from pathlib import Path

from src.social_studies.context_builder import (
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
)
from src.social_studies.sampler import sample_params

ROOT = Path(__file__).resolve().parents[1]
LEGACY_AXIS_NAMES = {"閱讀歷程", "文本形式", "question_style"}


def _contains_retired_social_axis(text: str) -> bool:
    lowered = text.casefold()
    return "pisa" in lowered or any(axis in text for axis in LEGACY_AXIS_NAMES)


def test_social_parameter_csv_has_only_live_categories_and_six_content_types() -> None:
    path = ROOT / "data/social_studies/curriculum/schema_parameters.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    categories = {row["類別"] for row in rows}
    assert categories.isdisjoint(LEGACY_AXIS_NAMES)
    assert tuple(
        row["value"] for row in rows if row["類別"] == "題目內容類型"
    ) == (
        "純文字",
        "含圖片",
        "graphs/charts/tables",
        "customized",
        "混合",
        "數位閱讀",
    )


def test_new_era_social_prompt_builders_emit_no_pisa_axis_strings() -> None:
    params = sample_params(
        seed=499,
        content_type="純文字",
        target_surface="紙本",
        sub_question_count=3,
    )
    few_shot_dir = ROOT / "data/social_studies/few_shot"
    text_user_prompt, _ = build_text_user_prompt(
        params,
        few_shot_dir,
        disable_reference_fewshot=True,
    )
    subquestion_user_prompt, _ = build_subquestion_user_prompt(
        核心問題="社會制度如何影響公共生活？",
        文本="這是一段測試用共用文本。",
        取材來源=["測試資料"],
        sq_plan={"序號": 1, "題型": "選擇題", "出題概念": "辨識制度作用"},
        params=params,
        few_shot_dir=few_shot_dir,
        disable_reference_fewshot=True,
    )
    prompts = (
        build_text_system_prompt(params=params),
        text_user_prompt,
        build_subquestion_system_prompt("第四學習階段"),
        subquestion_user_prompt,
    )

    for prompt in prompts:
        assert not _contains_retired_social_axis(prompt)


def test_social_contributor_guides_do_not_author_retired_axes() -> None:
    guide_paths = (
        ROOT / "data/social_studies/csv_填寫指南.md",
        ROOT / "docs/ADDING_SAMPLES.md",
    )

    for path in guide_paths:
        text = path.read_text(encoding="utf-8")
        if path.name == "ADDING_SAMPLES.md":
            text = text.split("## 二、社會", 1)[1].split("## 三、自然", 1)[0]
        assert not _contains_retired_social_axis(text)


def test_live_social_few_shot_header_has_no_retired_axis_columns() -> None:
    path = ROOT / "data/social_studies/few_shot/few_shot_examples.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle))

    assert LEGACY_AXIS_NAMES.isdisjoint(header)
    assert {"認知歷程", "內容領域", "題目內容類型"}.issubset(header)
