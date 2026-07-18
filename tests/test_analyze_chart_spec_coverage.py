"""Tests for the chart_spec coverage classifier."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_chart_spec_coverage import (
    classify_spec,
    iter_item_specs,
    iter_specs,
    summarize,
)


def test_classify_chart_by_render_mode_and_chart_type() -> None:
    spec = {"render_mode": "chart", "chart_type": "histogram", "data": {}}
    assert classify_spec(spec) == "chart"


def test_classify_table_by_html_data_rows_columns() -> None:
    spec = {
        "render_mode": "html",
        "description": "課程表",
        "data": {"columns": ["時段", "課程"], "rows": [["9:00", "數學"]]},
    }
    assert classify_spec(spec) == "table"


def test_classify_geometry_by_data_shapes() -> None:
    spec = {
        "render_mode": "html",
        "description": "三角形示意圖",
        "data": {"shapes": [{"type": "triangle", "vertices": [[0, 0], [3, 0], [0, 4]]}]},
    }
    assert classify_spec(spec) == "geometry"


def test_classify_scenario_card_by_description_keyword() -> None:
    spec = {
        "render_mode": "html",
        "description": "情境卡：博物館入場資訊",
        "data": {"title": "入場資訊", "items": ["票價", "時段"]},
    }
    assert classify_spec(spec) == "scenario_card"


def test_classify_other_when_shape_unknown() -> None:
    spec = {"render_mode": "html", "description": "自訂 SVG", "data": {"svg": "<svg/>"}}
    assert classify_spec(spec) == "other"


def test_iter_specs_reads_top_level_and_subquestion_chart_specs(tmp_path: Path) -> None:
    payload = {
        "chart_spec": {"render_mode": "chart", "chart_type": "boxplot", "data": {}},
        "subquestions": [
            {"chart_spec": {"render_mode": "html", "description": "表格", "data": {"rows": []}}},
            {"chart_spec": None},
        ],
    }
    (tmp_path / "q.json").write_text(json.dumps(payload), encoding="utf-8")
    specs = list(iter_specs(tmp_path))
    assert len(specs) == 2
    assert {classify_spec(s) for s in specs} == {"chart", "table"}


def test_summarize_returns_markdown_with_counts_and_percentages() -> None:
    specs = [
        {"render_mode": "chart", "chart_type": "histogram", "data": {}},
        {"render_mode": "html", "description": "表格", "data": {"rows": []}},
        {"render_mode": "html", "description": "菜單", "data": {}},
    ]
    md = summarize(specs)
    assert "| category |" in md
    assert "| chart | 1 | 33.3% |" in md
    assert "| table | 1 | 33.3% |" in md
    assert "| other | 1 | 33.3% |" in md


def test_iter_item_specs_yields_top_level_and_subquestion_specs() -> None:
    item = {
        "chart_spec": {"render_mode": "chart", "chart_type": "boxplot", "data": {}},
        "subquestions": [
            {"chart_spec": {"render_mode": "html", "description": "表格", "data": {"rows": []}}},
            {"chart_spec": None},
            "not-a-dict",
        ],
    }
    specs = list(iter_item_specs(item))
    assert len(specs) == 2
    assert {classify_spec(s) for s in specs} == {"chart", "table"}
