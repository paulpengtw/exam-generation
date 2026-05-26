"""Tests for social-studies few-shot CSV loading."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.social_studies.data_loader import _parse_few_shot_csv, load_few_shot_examples


def _write_csv(path: Path, rows: list[dict]) -> None:
    headers = ["範例編號", "style", "description", "情境", "題型種類", "題型",
               "閱讀歷程", "文本形式", "題目", "正確解題分析", "chart_spec"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def test_empty_csv_returns_only_json_examples(tmp_path: Path) -> None:
    style_dir = tmp_path / "text_only"
    style_dir.mkdir()
    ex = [{"style": "text_only", "description": "json ex", "question": {"題目": ["material", "q1"]}}]
    (style_dir / "ex.json").write_text(json.dumps(ex), encoding="utf-8")

    csv_path = tmp_path / "few_shot_examples.csv"
    _write_csv(csv_path, [])  # header only

    results = load_few_shot_examples(tmp_path, "text_only")
    assert len(results) == 1
    assert results[0] == ex


def test_csv_examples_combined_with_json(tmp_path: Path) -> None:
    style_dir = tmp_path / "text_only"
    style_dir.mkdir()
    json_ex = [{"style": "text_only", "description": "json", "question": {"題目": ["m"]}}]
    (style_dir / "ex.json").write_text(json.dumps(json_ex), encoding="utf-8")

    csv_path = tmp_path / "few_shot_examples.csv"
    _write_csv(csv_path, [
        {"範例編號": "1", "style": "text_only", "description": "csv ex",
         "情境": "個人", "題型種類": "題組題", "題型": "選擇題",
         "閱讀歷程": "擷取訊息", "文本形式": "連續文本—敘事文",
         "題目": "素材文本", "正確解題分析": "", "chart_spec": ""},
        {"範例編號": "1", "style": "text_only", "description": "",
         "情境": "", "題型種類": "", "題型": "", "閱讀歷程": "", "文本形式": "",
         "題目": "小題一", "正確解題分析": "答案一", "chart_spec": ""},
    ])

    results = load_few_shot_examples(tmp_path, "text_only")
    # JSON list + CSV dict
    assert len(results) == 2
    csv_result = results[1]
    assert csv_result["description"] == "csv ex"
    assert csv_result["question"]["題目"] == ["素材文本", "小題一"]
    assert csv_result["question"]["正確解題分析"] == ["答案一"]


def test_csv_style_filtering(tmp_path: Path) -> None:
    csv_path = tmp_path / "few_shot_examples.csv"
    _write_csv(csv_path, [
        {"範例編號": "A", "style": "text_only", "description": "A", "情境": "個人",
         "題型種類": "題組題", "題型": "選擇題", "閱讀歷程": "擷取訊息",
         "文本形式": "連續文本—敘事文", "題目": "文本A", "正確解題分析": "", "chart_spec": ""},
        {"範例編號": "B", "style": "mixed_text", "description": "B", "情境": "公共",
         "題型種類": "題組題", "題型": "選擇題", "閱讀歷程": "發展解釋",
         "文本形式": "非連續文本—表格", "題目": "文本B", "正確解題分析": "", "chart_spec": ""},
    ])
    (tmp_path / "text_only").mkdir()

    results = load_few_shot_examples(tmp_path, "text_only")
    assert len(results) == 1
    assert results[0]["description"] == "A"

    results_mixed = load_few_shot_examples(tmp_path, "mixed_text")
    assert len(results_mixed) == 1
    assert results_mixed[0]["description"] == "B"


def test_multi_value_fields_split(tmp_path: Path) -> None:
    rows = [{"範例編號": "1", "style": "text_only", "description": "multi",
             "情境": "個人;公共", "題型種類": "題組題", "題型": "開放式建構反應題",
             "閱讀歷程": "擷取訊息;發展解釋", "文本形式": "連續文本—說明文",
             "題目": "素材", "正確解題分析": "", "chart_spec": ""}]
    result = _parse_few_shot_csv(rows, "text_only")[0]["question"]
    assert result["情境"] == ["個人", "公共"]
    assert result["閱讀歷程"] == ["擷取訊息", "發展解釋"]


def test_chart_spec_parsed_from_json_string(tmp_path: Path) -> None:
    spec = {"render_mode": "chart", "chart_type": "pie_chart", "title": "T", "data": {}}
    rows = [{"範例編號": "1", "style": "with_non_continuous_text", "description": "chart",
             "情境": "公共", "題型種類": "題組題", "題型": "選擇題",
             "閱讀歷程": "擷取訊息", "文本形式": "非連續文本—圖表與圖形",
             "題目": "素材", "正確解題分析": "", "chart_spec": json.dumps(spec)}]
    result = _parse_few_shot_csv(rows, "with_non_continuous_text")[0]["question"]
    assert result["chart_spec"] == spec


def test_missing_csv_returns_json_only(tmp_path: Path) -> None:
    style_dir = tmp_path / "text_only"
    style_dir.mkdir()
    # No few_shot_examples.csv at all
    results = load_few_shot_examples(tmp_path, "text_only")
    assert results == []
