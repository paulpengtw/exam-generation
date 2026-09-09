from __future__ import annotations


def test_parse_text_shell_survives_sentry_payload_with_string_data() -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": "地圖",
            "title": "人口移動示意圖",
            "data": "圖例：灰色區塊=都市地區；箭頭=主要移動方向。",
            "description": "示意圖",
        },
    }
    question = _parse_text_shell(raw, "sentry-630", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.data == {}
    assert question.chart_spec.title == "人口移動示意圖"


def test_parse_text_shell_coerces_list_data_to_empty_dict() -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": "地圖",
            "title": "人口移動示意圖",
            "data": ["人口", "移動"],
            "description": "示意圖",
        },
    }
    question = _parse_text_shell(raw, "list-data-630", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.data == {}
    assert question.chart_spec.figure_kind == "地圖"
    assert question.chart_spec.title == "人口移動示意圖"
    assert question.chart_spec.description == "示意圖"


def test_parse_text_shell_coerces_str_labels_to_empty_dict() -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "chart",
            "chart_type": "histogram",
            "figure_kind": "統計圖",
            "title": "人口統計",
            "data": {"甲": 10, "乙": 20},
            "labels": "橫軸：地區；縱軸：人數",
            "description": "示意圖",
        },
    }
    question = _parse_text_shell(raw, "string-labels-630", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.labels == {}
    assert question.chart_spec.data == {"甲": 10, "乙": 20}
    assert question.chart_spec.chart_type == "histogram"
    assert question.chart_spec.figure_kind == "統計圖"
    assert question.chart_spec.title == "人口統計"


def test_parse_text_shell_coerces_dict_title_to_empty_str() -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": "地圖",
            "title": {"text": "人口移動示意圖"},
            "data": {"甲": 10},
            "description": "示意圖",
        },
    }
    question = _parse_text_shell(raw, "dict-title-630", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.title == ""
    assert question.chart_spec.figure_kind == "地圖"
    assert question.chart_spec.data == {"甲": 10}
    assert question.chart_spec.description == "示意圖"


def test_parse_text_shell_coerces_list_title_to_empty_str() -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": "地圖",
            "title": ["人口移動示意圖"],
            "data": {"甲": 10},
            "description": "示意圖",
        },
    }
    question = _parse_text_shell(raw, "list-title-630", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.title == ""
    assert question.chart_spec.figure_kind == "地圖"
    assert question.chart_spec.data == {"甲": 10}
    assert question.chart_spec.description == "示意圖"


def test_parse_text_shell_coerces_dict_description_to_empty_str() -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": "地圖",
            "title": "人口移動示意圖",
            "data": {"甲": 10},
            "description": {"text": "示意圖"},
        },
    }
    question = _parse_text_shell(raw, "dict-description-630", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.description == ""
    assert question.chart_spec.figure_kind == "地圖"
    assert question.chart_spec.title == "人口移動示意圖"
    assert question.chart_spec.data == {"甲": 10}


def test_parse_text_shell_coerces_dict_figure_kind_to_empty_str() -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "html",
            "figure_kind": {"name": "地圖"},
            "title": "人口移動示意圖",
            "data": {"甲": 10},
            "description": "示意圖",
        },
    }
    question = _parse_text_shell(raw, "dict-figure-kind-630", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.figure_kind == ""
    assert question.chart_spec.title == "人口移動示意圖"
    assert question.chart_spec.data == {"甲": 10}
    assert question.chart_spec.description == "示意圖"


def test_parse_text_shell_keeps_valid_dict_data_unchanged() -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "image_spec": {
            "render_mode": "chart",
            "chart_type": "histogram",
            "data": {"甲": 10, "乙": 20},
            "labels": {"x": "類別", "y": "人數"},
            "title": "測試",
        },
    }
    question = _parse_text_shell(raw, "valid-dict-data-630", params, "test-model")

    assert question.chart_spec is not None
    assert question.chart_spec.data == {"甲": 10, "乙": 20}
    assert question.chart_spec.labels == {"x": "類別", "y": "人數"}
    assert question.chart_spec.title == "測試"
    assert question.chart_spec.chart_type == "histogram"


def test_image_spec_coerces_mistyped_fields_at_model_level() -> None:
    from src.social_studies.schemas import ImageSpec

    spec = ImageSpec(data="x", labels="y", title={})

    assert spec.data == {}
    assert spec.labels == {}
    assert spec.title == ""

    other_spec = ImageSpec(description={"a": 1}, figure_kind=["地圖"])

    assert other_spec.description == ""
    assert other_spec.figure_kind == ""
