"""Behavior tests for social-studies Channel-1 few-shot loading."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.social_studies.data_loader import (
    _parse_few_shot_csv,
    load_few_shot_example_groups,
    load_few_shot_examples,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    headers = [
        "範例編號",
        "題目內容類型",
        "description",
        "情境",
        "題型種類",
        "題型",
        "認知歷程",
        "內容領域",
        "題目",
        "正確解題分析",
        "chart_spec",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _json_example(description: str, content_type: str = "純文字") -> dict:
    process = "Knowing–Defining and Describing"
    return {
        "題目內容類型": content_type,
        "description": description,
        "question": {
            "題目內容類型": content_type,
            "內容領域": "Civic Principles",
            "認知歷程": [process],
            "題目": ["素材", "小題"],
            "subquestions": [{"題型": "選擇題", "認知歷程": process, "題目": "小題"}],
        },
    }


def test_empty_csv_returns_only_json_examples(tmp_path: Path) -> None:
    key_dir = tmp_path / "純文字"
    key_dir.mkdir()
    expected = _json_example("json ex")
    (key_dir / "ex.json").write_text(json.dumps([expected], ensure_ascii=False), encoding="utf-8")
    _write_csv(tmp_path / "few_shot_examples.csv", [])

    assert load_few_shot_examples(tmp_path, "純文字") == [expected]


def test_csv_examples_combine_with_json(tmp_path: Path) -> None:
    key_dir = tmp_path / "純文字"
    key_dir.mkdir()
    (key_dir / "ex.json").write_text(
        json.dumps([_json_example("json")], ensure_ascii=False),
        encoding="utf-8",
    )
    _write_csv(
        tmp_path / "few_shot_examples.csv",
        [
            {
                "範例編號": "1",
                "題目內容類型": "純文字",
                "description": "csv ex",
                "情境": "公共",
                "題型種類": "題組題",
                "題型": "選擇題",
                "內容領域": "Civic Institutions and Systems",
                "題目": "素材文本",
                "正確解題分析": "",
            },
            {
                "範例編號": "1",
                "題目內容類型": "純文字",
                "認知歷程": "Reasoning and Applying–Interpret information",
                "題目": "小題一",
                "正確解題分析": "答案一",
                "小題序號": "1",
                "小題題型": "選擇題",
            },
        ],
    )

    results = load_few_shot_examples(tmp_path, "純文字")

    assert [example["description"] for example in results] == ["json", "csv ex"]
    assert results[1]["question"]["題目"] == ["素材文本", "小題一"]
    assert results[1]["question"]["正確解題分析"] == ["答案一"]


def test_csv_content_type_filtering(tmp_path: Path) -> None:
    _write_csv(
        tmp_path / "few_shot_examples.csv",
        [
            {
                "範例編號": "A",
                "題目內容類型": "純文字",
                "description": "A",
                "情境": "個人",
                "內容領域": "Civic Principles",
                "題目": "文本A",
            },
            {
                "範例編號": "B",
                "題目內容類型": "混合",
                "description": "B",
                "情境": "公共",
                "內容領域": "Civic Participation",
                "題目": "文本B",
            },
        ],
    )

    assert [ex["description"] for ex in load_few_shot_examples(tmp_path, "純文字")] == ["A"]
    assert [ex["description"] for ex in load_few_shot_examples(tmp_path, "混合")] == ["B"]


def test_multi_value_fields_and_chart_spec_are_parsed() -> None:
    process = "Reasoning and Applying–Interpret information"
    spec = {"render_mode": "chart", "chart_type": "pie_chart", "title": "T", "data": {}}
    rows = [
        {
            "範例編號": "1",
            "題目內容類型": "graphs/charts/tables",
            "description": "chart",
            "情境": "個人;公共",
            "內容領域": "Civic Institutions and Systems",
            "認知歷程": process,
            "題目": "素材",
            "正確解題分析": "",
            "chart_spec": json.dumps(spec, ensure_ascii=False),
        }
    ]

    question = _parse_few_shot_csv(rows, "graphs/charts/tables")[0]["question"]

    assert question["情境"] == ["個人", "公共"]
    assert question["認知歷程"] == [process]
    assert question["內容領域"] == "Civic Institutions and Systems"
    assert question["chart_spec"] == spec


def test_missing_csv_returns_json_only(tmp_path: Path) -> None:
    key_dir = tmp_path / "純文字"
    key_dir.mkdir()
    expected = _json_example("json")
    (key_dir / "ex.json").write_text(json.dumps([expected], ensure_ascii=False), encoding="utf-8")

    assert load_few_shot_examples(tmp_path, "純文字") == [expected]


def test_content_type_directory_files_form_groups(tmp_path: Path) -> None:
    key_dir = tmp_path / "純文字"
    key_dir.mkdir()
    (key_dir / "a.json").write_text(
        json.dumps([_json_example("text"), _json_example("text 2")], ensure_ascii=False),
        encoding="utf-8",
    )
    (key_dir / "b.json").write_text(
        json.dumps([_json_example("another")], ensure_ascii=False),
        encoding="utf-8",
    )

    groups = load_few_shot_example_groups(tmp_path, "純文字")

    assert [[ex["description"] for ex in group] for group in groups] == [
        ["text", "text 2"],
        ["another"],
    ]


def test_csv_examples_are_single_item_groups(tmp_path: Path) -> None:
    _write_csv(
        tmp_path / "few_shot_examples.csv",
        [
            {
                "範例編號": "A",
                "題目內容類型": "純文字",
                "description": "A",
                "情境": "個人",
                "內容領域": "Civic Principles",
                "題目": "文本A",
            },
            {
                "範例編號": "B",
                "題目內容類型": "純文字",
                "description": "B",
                "情境": "公共",
                "內容領域": "Civic Participation",
                "題目": "文本B",
            },
        ],
    )

    groups = load_few_shot_example_groups(tmp_path, "純文字")

    assert len(groups) == 2
    assert all(len(group) == 1 for group in groups)
    assert [group[0]["description"] for group in groups] == ["A", "B"]
