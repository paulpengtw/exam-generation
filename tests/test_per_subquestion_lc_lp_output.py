"""Tests that per-子題 explicit LC/LP overrides the LLM output in _parse_subquestion."""


def _make_ss_params_with_cfg(lc_codes, lp_codes):
    import random

    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import SubQuestionConfig
    rng = random.Random(42)
    params = sample_params(seed=rng.randrange(2**32))
    cfg = SubQuestionConfig(learning_content=lc_codes, learning_performance=lp_codes)
    params = params.model_copy(update={"subquestion_configs": [cfg]})
    return params


def test_ss_explicit_lc_lp_overrides_sq_raw():
    """When cfg has LC/LP, parsed SubQuestion uses cfg codes, not sq_raw codes."""
    from src.social_studies.cli import _parse_subquestion
    params = _make_ss_params_with_cfg(["歷Ka-Ⅳ-1"], ["社1b-Ⅳ-1"])

    sq_raw = {
        "序號": 1, "題型": "選擇題", "題目": "測試題目", "答案": "A",
        "答案解析": "解析", "出題概念": "概念",
        "科目": ["歷史"], "核心素養": [], "評分規準": [],
        "學習內容": [{"編碼": "地理-wrong-code", "說明": "錯誤說明"}],
        "學習表現": [{"編碼": "公民-wrong-code", "說明": "錯誤說明"}],
    }
    result = _parse_subquestion(sq_raw, "test-q", params, 1)
    assert result is not None
    lc_codes_out = [r.編碼 for r in result.學習內容]
    lp_codes_out = [r.編碼 for r in result.學習表現]
    assert "歷Ka-Ⅳ-1" in lc_codes_out, f"Expected explicit LC in output, got {lc_codes_out}"
    assert "社1b-Ⅳ-1" in lp_codes_out, f"Expected explicit LP in output, got {lp_codes_out}"
    assert "地理-wrong-code" not in lc_codes_out
    assert "公民-wrong-code" not in lp_codes_out


def test_ss_empty_cfg_preserves_sq_raw():
    """When cfg has empty LC/LP, output mirrors sq_raw."""
    from src.social_studies.cli import _parse_subquestion
    params = _make_ss_params_with_cfg([], [])

    sq_raw = {
        "序號": 1, "題型": "選擇題", "題目": "測試題目", "答案": "A",
        "答案解析": "解析", "出題概念": "概念",
        "科目": ["歷史"], "核心素養": [], "評分規準": [],
        "學習內容": [{"編碼": "歷Ka-Ⅳ-1", "說明": "說明文字"}],
        "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "表現說明"}],
    }
    result = _parse_subquestion(sq_raw, "test-q", params, 1)
    assert result is not None
    assert result.學習內容[0].編碼 == "歷Ka-Ⅳ-1"
    assert result.學習表現[0].編碼 == "社1b-Ⅳ-1"
