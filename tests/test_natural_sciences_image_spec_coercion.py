"""Issue #631: NS ImageSpec must tolerate mistyped LLM fields.

Tests for the ``_parse_text_shell`` seam in natural_sciences/cli.py and the
``ImageSpec`` model constructor.

Discriminator pattern: pass ``params=None`` to ``_parse_text_shell``.
* Before fix: bad field types raise ``ValidationError`` inside ImageSpec
  construction (falls through the fallback ladder which re-raises) → the
  ``pytest.raises(AttributeError)`` expectation FAILS → test is RED.
* After fix: coercers absorb the bad types; construction succeeds; execution
  then hits ``params.情境`` → ``AttributeError`` on None → test is GREEN.

Mirror the structure of tests/test_social_studies_image_spec_coercion.py.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# _parse_text_shell seam tests (params=None discriminator)
# ---------------------------------------------------------------------------


def test_parse_text_shell_survives_string_data() -> None:
    """data as str should be coerced to {} and not crash _parse_text_shell (#631)."""
    from src.natural_sciences.cli import _parse_text_shell

    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": "示意圖",
            "title": "圖表",
            "data": "圖例：灰色區塊=示意區域；箭頭=方向。",
            "description": "示意圖說明",
        },
    }
    # params=None: AttributeError means execution passed the ImageSpec block.
    # ValidationError would mean the bug is still live.
    with pytest.raises(AttributeError):
        _parse_text_shell(raw, "ns-631-str-data", None, "test-model")


def test_parse_text_shell_survives_list_data() -> None:
    """data as list should be coerced to {} and not crash _parse_text_shell (#631)."""
    from src.natural_sciences.cli import _parse_text_shell

    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": "示意圖",
            "title": "圖表",
            "data": ["項目一", "項目二"],
            "description": "示意圖說明",
        },
    }
    with pytest.raises(AttributeError):
        _parse_text_shell(raw, "ns-631-list-data", None, "test-model")


def test_parse_text_shell_survives_string_labels() -> None:
    """labels as str should be coerced to {} and not crash _parse_text_shell (#631)."""
    from src.natural_sciences.cli import _parse_text_shell

    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "chart",
            "chart_type": "histogram",
            "figure_kind": "統計圖",
            "title": "統計",
            "data": {"甲": 10, "乙": 20},
            "labels": "橫軸：類別；縱軸：數量",
            "description": "直方圖",
        },
    }
    with pytest.raises(AttributeError):
        _parse_text_shell(raw, "ns-631-str-labels", None, "test-model")


def test_parse_text_shell_survives_dict_title() -> None:
    """title as dict should be coerced to '' and not crash _parse_text_shell (#631)."""
    from src.natural_sciences.cli import _parse_text_shell

    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": "示意圖",
            "title": {"text": "示意圖標題"},
            "data": {"甲": 10},
            "description": "示意圖說明",
        },
    }
    with pytest.raises(AttributeError):
        _parse_text_shell(raw, "ns-631-dict-title", None, "test-model")


def test_parse_text_shell_survives_dict_description() -> None:
    """description as dict should be coerced to '' and not crash (#631)."""
    from src.natural_sciences.cli import _parse_text_shell

    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": "示意圖",
            "title": "示意圖標題",
            "data": {"甲": 10},
            "description": {"text": "說明文字"},
        },
    }
    with pytest.raises(AttributeError):
        _parse_text_shell(raw, "ns-631-dict-description", None, "test-model")


def test_parse_text_shell_survives_dict_figure_kind() -> None:
    """figure_kind as dict should be coerced to '' and not crash (#631)."""
    from src.natural_sciences.cli import _parse_text_shell

    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": {"name": "地圖"},
            "title": "示意圖標題",
            "data": {"甲": 10},
            "description": "說明文字",
        },
    }
    with pytest.raises(AttributeError):
        _parse_text_shell(raw, "ns-631-dict-figure-kind", None, "test-model")


def test_parse_text_shell_valid_dict_data_passes_through() -> None:
    """A valid dict data payload still round-trips unchanged through _parse_text_shell (#631)."""
    from src.natural_sciences.cli import _parse_text_shell
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=1, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "chart",
            "chart_type": "histogram",
            "figure_kind": "統計圖",
            "data": {"甲": 10, "乙": 20},
            "labels": {"x": "類別", "y": "數量"},
            "title": "統計圖表",
        },
    }
    question = _parse_text_shell(raw, "ns-631-valid-data", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.data == {"甲": 10, "乙": 20}
    assert question.chart_spec.labels == {"x": "類別", "y": "數量"}
    assert question.chart_spec.title == "統計圖表"
    assert question.chart_spec.chart_type == "histogram"


# ---------------------------------------------------------------------------
# Model-level test
# ---------------------------------------------------------------------------


def test_image_spec_coerces_mistyped_fields_at_model_level() -> None:
    """ImageSpec(data='x', labels='y', title={}) yields {} / {} / '' (#631)."""
    from src.natural_sciences.schemas import ImageSpec

    spec = ImageSpec(data="x", labels="y", title={})

    assert spec.data == {}
    assert spec.labels == {}
    assert spec.title == ""

    other_spec = ImageSpec(description={"a": 1}, figure_kind=["地圖"])

    assert other_spec.description == ""
    assert other_spec.figure_kind == ""
