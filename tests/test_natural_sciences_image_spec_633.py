"""Issue #633: Slice 2 tests for natural-sciences _parse_text_shell.

Slice 2: Strict parse fails AND fallback construction also fails
         (bad render_mode + bad chart_type).  After fix: no raise,
         chart_spec is None.
"""

from __future__ import annotations


def test_parse_text_shell_returns_none_chart_spec_when_all_fallbacks_fail_ns() -> None:
    """When strict parse AND fallback both fail, chart_spec is None — no raise (#633)."""
    from src.natural_sciences.cli import _parse_text_shell
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=1, content_type="純文字")
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

    question = _parse_text_shell(raw, "ns-633-slice2", params, "test-model")

    assert question.chart_spec is None
