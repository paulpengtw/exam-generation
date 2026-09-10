"""Issue #633: Slice 1 & 2 tests for social-studies _parse_text_shell.

Slice 1: Strict parse fails (bad render_mode), model supplies html;
         current code drops html in fallback. After fix: html is kept.

Slice 2: Strict parse fails AND fallback construction also fails
         (bad render_mode + bad chart_type).  After fix: no raise,
         chart_spec is None.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Slice 1 — fallback keeps html
# ---------------------------------------------------------------------------


def test_parse_text_shell_fallback_keeps_html_field() -> None:
    """html supplied by LLM must survive the render_mode-repair fallback (#633 slice 1)."""
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "pdf",   # invalid — triggers fallback
            "figure_kind": "地圖",
            "title": "人口移動示意圖",
            "data": {"甲": 10},
            "description": "示意圖",
            "html": "<table><tr><td>甲</td><td>10</td></tr></table>",
        },
    }

    question = _parse_text_shell(raw, "ss-633-slice1", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.html == "<table><tr><td>甲</td><td>10</td></tr></table>"
    assert question.chart_spec.render_mode == "html"
    assert question.chart_spec.figure_kind == "地圖"


# ---------------------------------------------------------------------------
# Slice 2 — total fallback failure → None, no raise
# ---------------------------------------------------------------------------


def test_parse_text_shell_returns_none_chart_spec_when_all_fallbacks_fail_ss() -> None:
    """When strict parse AND fallback both fail, chart_spec is None — no raise (#633)."""
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "pdf",       # invalid → first parse fails
            "chart_type": "bar_chart",  # invalid → chart-mode fallback also fails
            "figure_kind": "統計圖",
            "title": "統計圖表",
            "data": {"甲": 10},
            "description": "說明",
        },
    }

    question = _parse_text_shell(raw, "ss-633-slice2", params, "test-model")

    assert question.chart_spec is None
