"""Contract tests for the social-studies Channel-1 few-shot clean cut."""

from __future__ import annotations

import csv
import inspect
import json
import random
from pathlib import Path

import pytest

from src.social_studies.data_loader import (
    _parse_few_shot_csv,
    load_few_shot_example_groups,
    load_few_shot_examples,
)
from src.social_studies.context_builder import build_text_user_prompt
from src.social_studies.sampler import sample_params

CONTENT_TYPES = ("純文字", "混合", "graphs/charts/tables")
COGNITIVE_PROCESSES = {
    "Knowing–Defining and Describing",
    "Knowing–Illustrating with examples",
    "Reasoning and Applying–Interpret information",
    "Reasoning and Applying–Relate or Integrate",
}
CONTENT_DOMAINS = {
    "Civic Institutions and Systems",
    "Civic Principles",
    "Civic Participation",
    "Civic Roles and Identities",
}


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    headers = [
        "範例編號",
        "題目內容類型",
        "description",
        "情境",
        "題型種類",
        "題型",
        "認知歷程",
        "內容領域",
        "核心問題",
        "文本",
        "取材來源",
        "題目",
        "正確解題分析",
        "小題序號",
        "小題年級",
        "小題科目",
        "核心素養",
        "學習內容",
        "學習表現",
        "出題概念",
        "小題題型",
        "答案",
        "答案解析",
        "評分規準",
        "chart_spec",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _new_example(description: str, content_type: str) -> dict:
    process = "Knowing–Defining and Describing"
    return {
        "題目內容類型": content_type,
        "description": description,
        "question": {
            "題目內容類型": content_type,
            "內容領域": "Civic Principles",
            "認知歷程": [process],
            "題目": ["素材", "問題"],
            "正確解題分析": ["答案"],
            "subquestions": [
                {"序號": 1, "題型": "選擇題", "認知歷程": process, "題目": "問題"}
            ],
        },
    }


def test_public_loader_api_is_keyed_by_content_type() -> None:
    for loader in (load_few_shot_example_groups, load_few_shot_examples):
        parameters = inspect.signature(loader).parameters
        assert list(parameters) == ["few_shot_dir", "content_type"]
        assert "question" + "_style" not in parameters
        assert "style" not in parameters


@pytest.mark.parametrize("content_type", CONTENT_TYPES)
def test_checked_in_corpus_is_loaded_from_the_content_type_home(content_type: str) -> None:
    """Smoke test: checked-in ICCS groups load from their content-type home."""
    examples = load_few_shot_examples(Path("data/social_studies/few_shot"), content_type)
    assert examples
    for example in examples:
        question = example["question"]
        assert question["題目內容類型"] == content_type
        assert question["內容領域"] in CONTENT_DOMAINS
        assert question["認知歷程"]
        assert set(question["認知歷程"]) <= COGNITIVE_PROCESSES
        assert "閱讀歷程" not in question
        assert "文本形式" not in question
        for subquestion in question.get("subquestions", []):
            assert subquestion["認知歷程"] in COGNITIVE_PROCESSES


def test_channel1_corpus_is_refilled_for_required_iccs_content_types() -> None:
    """#544 keeps the three required Channel-1 keys populated with ICCS groups."""
    for content_type in CONTENT_TYPES:
        examples = load_few_shot_examples(Path("data/social_studies/few_shot"), content_type)
        assert examples, f"Expected ICCS Channel-1 groups for {content_type!r}"


_EXPECTED_ICCS_MARKERS = {
    "純文字": (
        "ICCS 題組：全球移動與公共生活",
        "ICCS 題組：制度、責任與權力",
        "ICCS 題組：經濟選擇與交易",
        "ICCS 題組：家庭關係與社會變遷",
    ),
    "混合": (
        "ICCS 題組：外籍移工資料與性別分工",
        "ICCS 題組：公共建設與政府權力",
    ),
    "graphs/charts/tables": (
        "ICCS 題組：女性未就業原因資料表",
        "ICCS 題組：媒體報導比例資料表",
        "ICCS 題組：地方選舉資格資料表",
        "ICCS 題組：新生兒姓氏比例資料表",
        "ICCS 題組：已婚女性勞動參與率圖",
        "ICCS 題組：國小校數變化圖",
    ),
}


@pytest.mark.parametrize("content_type", tuple(_EXPECTED_ICCS_MARKERS))
def test_populated_content_type_injects_iccs_example_at_prompt_seam(
    content_type: str,
) -> None:
    """A seeded text-stage prompt carries a real Channel-1 example for each key."""
    seed = 544 + list(_EXPECTED_ICCS_MARKERS).index(content_type)
    params = sample_params(
        seed=seed,
        content_type=content_type,
        target_surface="紙本",
        sub_question_count=3,
    )

    prompt, images = build_text_user_prompt(
        params,
        Path("data/social_studies/few_shot"),
        rng=random.Random(seed),
    )

    assert "## 參考範例" in prompt
    assert any(marker in prompt for marker in _EXPECTED_ICCS_MARKERS[content_type])
    assert all(path.exists() for path in images)


@pytest.mark.parametrize("content_type", ("含圖片", "customized", "數位閱讀"))
def test_unpopulated_content_type_keeps_instruction_only_fallback(content_type: str) -> None:
    """An unpopulated live key still builds cleanly with the designed fallback."""
    seed = 554 + ("含圖片", "customized", "數位閱讀").index(content_type)
    params = sample_params(seed=seed, content_type=content_type, sub_question_count=3)

    prompt, images = build_text_user_prompt(
        params,
        Path("data/social_studies/few_shot"),
        rng=random.Random(seed),
    )

    assert f"題目內容類型（{content_type}）" in prompt
    assert "（目前暫無範例，請根據指定條件自行設計。）" in prompt
    assert images == []


def test_empty_or_unpopulated_content_type_returns_no_examples(tmp_path: Path) -> None:
    assert load_few_shot_example_groups(tmp_path, "") == []
    assert load_few_shot_examples(tmp_path, "數位閱讀") == []


def test_new_content_type_file_is_discovered_without_loader_changes(tmp_path: Path) -> None:
    digital_dir = tmp_path / "數位閱讀"
    digital_dir.mkdir()
    (digital_dir / "synthetic.json").write_text(
        json.dumps(
            [_new_example("synthetic digital", "數位閱讀"), _new_example("second", "數位閱讀")],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    groups = load_few_shot_example_groups(tmp_path, "數位閱讀")

    assert len(groups) == 1
    assert [example["description"] for example in groups[0]] == [
        "synthetic digital",
        "second",
    ]


def test_csv_parser_reads_new_axes_and_drops_material_from_subquestions() -> None:
    process = "Reasoning and Applying–Interpret information"
    rows = [
        {
            "範例編號": "csv-1",
            "題目內容類型": "純文字",
            "description": "csv example",
            "情境": "公共",
            "題型種類": "題組題",
            "題型": "選擇題",
            "認知歷程": "",
            "內容領域": "Civic Institutions and Systems",
            "核心問題": "核心問題",
            "文本": "素材",
            "題目": "素材",
            "正確解題分析": "",
        },
        {
            "範例編號": "csv-1",
            "題目內容類型": "純文字",
            "認知歷程": process,
            "題目": "小題",
            "正確解題分析": "解析",
            "小題序號": "1",
            "小題年級": "8",
            "小題題型": "選擇題",
            "答案": "A",
        },
    ]

    parsed = _parse_few_shot_csv(rows, "純文字")

    assert len(parsed) == 1
    question = parsed[0]["question"]
    assert question["題目內容類型"] == "純文字"
    assert question["內容領域"] == "Civic Institutions and Systems"
    assert question["認知歷程"] == [process]
    assert question["題目"] == ["素材", "小題"]
    assert question["subquestions"] == [
        {
            "序號": 1,
            "年級": 8,
            "科目": [],
            "核心素養": [],
            "學習內容": [],
            "學習表現": [],
            "出題概念": "",
            "認知歷程": process,
            "題型": "選擇題",
            "題目": "小題",
            "答案": "A",
            "答案解析": "",
            "評分規準": [],
        }
    ]


def test_csv_key_filters_groups_by_content_type(tmp_path: Path) -> None:
    _write_csv(
        tmp_path / "few_shot_examples.csv",
        [
            {
                "範例編號": "text",
                "題目內容類型": "純文字",
                "description": "text",
                "內容領域": "Civic Principles",
                "題目": "text material",
            },
            {
                "範例編號": "chart",
                "題目內容類型": "graphs/charts/tables",
                "description": "chart",
                "內容領域": "Civic Institutions and Systems",
                "題目": "chart material",
            },
        ],
    )

    results = load_few_shot_examples(tmp_path, "graphs/charts/tables")

    assert [example["description"] for example in results] == ["chart"]


def test_csv_group_key_on_first_row_keeps_blank_metadata_rows(tmp_path: Path) -> None:
    _write_csv(
        tmp_path / "few_shot_examples.csv",
        [
            {
                "範例編號": "first-row-key",
                "題目內容類型": "純文字",
                "description": "first-row key",
                "內容領域": "Civic Principles",
                "認知歷程": "Knowing–Defining and Describing",
                "小題序號": "1",
                "小題題型": "選擇題",
                "題目": "第一小題",
            },
            {
                "範例編號": "first-row-key",
                "認知歷程": "Reasoning and Applying–Interpret information",
                "小題序號": "2",
                "小題題型": "選擇題",
                "題目": "第二小題",
            },
        ],
    )

    results = load_few_shot_examples(tmp_path, "純文字")

    assert len(results[0]["question"]["subquestions"]) == 2


def test_channel_two_and_unsafe_content_type_paths_are_not_loaded(tmp_path: Path) -> None:
    channel_two_dir = tmp_path / "process_exemplars"
    channel_two_dir.mkdir()
    (channel_two_dir / "synthetic.json").write_text(
        json.dumps([_new_example("channel two", "process_exemplars")], ensure_ascii=False),
        encoding="utf-8",
    )

    assert load_few_shot_examples(tmp_path, "process_exemplars") == []
    assert load_few_shot_examples(tmp_path, str(channel_two_dir)) == []


def test_cli_prompt_build_for_unpopulated_content_type_is_instruction_only(tmp_path: Path) -> None:
    from src.config import Config
    from src.social_studies.cli import build_generation_prompts
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=495, content_type="數位閱讀", sub_question_count=3)

    _system, user_prompt, images = build_generation_prompts(
        Config(data_dir=tmp_path, output_dir=tmp_path / "out"),
        params,
        disable_reference_fewshot=False,
    )

    assert images == []
    assert "題目內容類型（數位閱讀）" in user_prompt
    assert "（目前暫無範例，請根據指定條件自行設計。）" in user_prompt


def test_cli_prompt_build_uses_sampled_content_type_for_channel1_injection(tmp_path: Path) -> None:
    from src.config import Config
    from src.social_studies.cli import build_generation_prompts
    from src.social_studies.sampler import sample_params

    few_shot_dir = tmp_path / "social_studies" / "few_shot" / "純文字"
    few_shot_dir.mkdir(parents=True)
    (few_shot_dir / "synthetic.json").write_text(
        json.dumps([_new_example("sampled pure exemplar", "純文字")], ensure_ascii=False),
        encoding="utf-8",
    )
    params = sample_params(seed=496, content_type="純文字", sub_question_count=3)

    _system, user_prompt, _images = build_generation_prompts(
        Config(data_dir=tmp_path, output_dir=tmp_path / "out"),
        params,
        disable_reference_fewshot=False,
    )

    assert "sampled pure exemplar" in user_prompt


def test_subquestion_prompt_uses_pinned_content_type_for_channel1_injection(tmp_path: Path) -> None:
    import random

    from src.social_studies.context_builder import build_subquestion_user_prompt
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import SubQuestionConfig

    few_shot_dir = tmp_path / "數位閱讀"
    few_shot_dir.mkdir()
    (few_shot_dir / "synthetic.json").write_text(
        json.dumps([_new_example("pinned digital exemplar", "數位閱讀")], ensure_ascii=False),
        encoding="utf-8",
    )
    params = sample_params(seed=497, content_type="純文字", sub_question_count=3)

    prompt, _images = build_subquestion_user_prompt(
        核心問題="核心問題",
        文本="文本",
        取材來源=["來源"],
        sq_plan={"序號": 1, "題型": "選擇題", "出題概念": "測試"},
        params=params,
        few_shot_dir=tmp_path,
        cfg=SubQuestionConfig(content_type="數位閱讀"),
        rng=random.Random(497),
    )

    assert "pinned digital exemplar" in prompt
