"""Unit tests for social-studies 圖像種類 diversity policy."""

from __future__ import annotations

import json

from src.common.figure_policy import (
    effective_figure_kind,
    find_figure_kind_collisions,
)
from src.social_studies import figure_kind_loader
from src.social_studies.schemas import ImageSpec


def _spec(
    *,
    render_mode: str = "html",
    figure_kind: str = "",
    chart_type: str | None = None,
) -> ImageSpec:
    return ImageSpec(
        render_mode=render_mode,
        figure_kind=figure_kind,
        chart_type=chart_type,
    )


def test_figure_kind_loader_reads_aliases_from_editable_vocabulary_document(tmp_path) -> None:
    source = tmp_path / "figure_kinds.json"
    source.write_text(
        json.dumps(
            {
                "canonical": ["長條圖"],
                "aliases": {"長條圖": ["直條圖", "bar_chart"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    alias_loader = getattr(figure_kind_loader, "load_figure_kind_aliases", None)
    aliases = alias_loader(source) if alias_loader else {}

    assert aliases == {"直條圖": "長條圖", "bar_chart": "長條圖"}
    assert figure_kind_loader.load_figure_kinds(source) == ("長條圖",)


def test_effective_figure_kind_falls_back_to_chart_type_only_for_chart_specs() -> None:
    chart = _spec(render_mode="chart", chart_type="line_chart")
    html = _spec(render_mode="html", chart_type="line_chart")

    assert effective_figure_kind(chart) == "line_chart"
    assert effective_figure_kind(html) == ""


def test_image_spec_preserves_free_text_figure_kind() -> None:
    spec = _spec(figure_kind="表格")

    assert spec.figure_kind == "表格"


def test_find_collisions_normalizes_strip_and_casefold() -> None:
    specs = [_spec(figure_kind="  Pie Chart "), _spec(figure_kind="pie chart")]

    assert find_figure_kind_collisions(specs, pinned=set(), allow_duplicates=False) == [
        (0, 1, "pie chart")
    ]


def test_find_collisions_folds_two_alias_spellings_to_one_canonical_kind() -> None:
    specs = [_spec(figure_kind="直條圖"), _spec(figure_kind="bar_chart")]

    assert find_figure_kind_collisions(specs, pinned=set(), allow_duplicates=False) == [
        (0, 1, "長條圖")
    ]


def test_find_collisions_folds_canonical_and_alias_spellings() -> None:
    specs = [_spec(figure_kind="長條圖"), _spec(figure_kind="直條圖")]

    assert find_figure_kind_collisions(specs, pinned=set(), allow_duplicates=False) == [
        (0, 1, "長條圖")
    ]


def test_find_collisions_does_not_fold_unknown_kind_into_canonical_kind() -> None:
    specs = [_spec(figure_kind="長條圖風格示意圖"), _spec(figure_kind="長條圖")]

    assert find_figure_kind_collisions(specs, pinned=set(), allow_duplicates=False) == []


def test_empty_figure_kinds_never_collide() -> None:
    specs = [_spec(), _spec(), _spec(render_mode="chart")]

    assert find_figure_kind_collisions(specs, pinned=set(), allow_duplicates=False) == []


def test_pinned_specs_may_share_a_kind_but_unpinned_specs_yield_to_them() -> None:
    specs = [
        _spec(figure_kind="地圖"),
        _spec(figure_kind="地圖"),
        _spec(figure_kind="地圖"),
    ]

    assert find_figure_kind_collisions(specs, pinned={0, 1}, allow_duplicates=False) == [
        (0, 2, "地圖"),
        (1, 2, "地圖"),
    ]


def test_kill_switch_skips_collision_validation() -> None:
    specs = [_spec(figure_kind="表格"), _spec(figure_kind="表格")]

    assert find_figure_kind_collisions(specs, pinned=set(), allow_duplicates=True) == []


def test_chart_type_and_cross_render_mode_figure_kind_collide() -> None:
    specs = [
        _spec(render_mode="chart", chart_type="line_chart"),
        _spec(render_mode="html", figure_kind="折線圖"),
    ]

    assert find_figure_kind_collisions(specs, pinned=set(), allow_duplicates=False) == [
        (0, 1, "折線圖")
    ]
