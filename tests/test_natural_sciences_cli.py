"""Parse-time repair of LLM-emitted 學習內容/學習表現 codes in the NS CLI (issue #92).

Pools are pinned via sample_params(learning_content=..., learning_performance=...)
so fallback expectations are deterministic. Real curriculum facts used:
"Ab-Ⅳ-1" / "Aa-IV-3" / "Ka-Ⅳ-1" are LC codes; "tr-Ⅳ-1" / "pa-Ⅳ-1" are LP
codes; "INc-Ⅳ-1" and "xx-Ⅳ-99" do not exist.
"""

from __future__ import annotations

import pytest

from src.natural_sciences.cli import _parse_question, _parse_subquestion
from src.natural_sciences.sampler import sample_params


def _params(q_type: str = "Simple multiple-choice", **kwargs):
    return sample_params(
        seed=1,
        q_type=[q_type],
        learning_content=["Ab-Ⅳ-1"],
        learning_performance=["tr-Ⅳ-1"],
        **kwargs,
    )


_FAMILIES = [
    pytest.param(
        "Simple multiple-choice",
        "Q? (A) 甲 (B) 乙 (C) 丙 (D) 丁",
        "A",
        [],
        id="simple-mc",
    ),
    pytest.param(
        "Complex multiple-choice",
        "請逐項判斷是非：(1)…… (2)……",
        "(1)是 (2)非",
        [],
        id="complex-mc",
    ),
    pytest.param(
        "Constructed response",
        "請解釋光合作用為何需要光。",
        "光反應需要光能供應電子傳遞……",
        [{"code": "2", "規準說明": "完整解釋", "學生作答實例": ["…"]}],
        id="constructed-response",
    ),
]


def _sq_raw(q_type, 題目, 答案, rubric, lc, lp):
    return {
        "序號": 1,
        "題型": q_type,
        "題目": 題目,
        "答案": 答案,
        "答案解析": "解析",
        "出題概念": "概念",
        "科目": ["自然科學"],
        "評分規準": rubric,
        "學習內容": [{"編碼": c, "說明": "LLM 說明"} for c in lc],
        "學習表現": [{"編碼": c, "說明": "LLM 說明"} for c in lp],
    }


@pytest.mark.parametrize("q_type,題目,答案,rubric", _FAMILIES)
def test_parse_subquestion_keeps_valid_codes_per_family(q_type, 題目, 答案, rubric) -> None:
    raw = _sq_raw(q_type, 題目, 答案, rubric, ["Aa-IV-3"], ["pa-Ⅳ-1"])
    sq = _parse_subquestion(raw, "q1", _params(q_type), 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Aa-IV-3"]  # kept, not pool-replaced
    assert [r.編碼 for r in sq.學習表現] == ["pa-Ⅳ-1"]


@pytest.mark.parametrize("q_type,題目,答案,rubric", _FAMILIES)
def test_parse_subquestion_replaces_unknown_codes_from_pool_per_family(
    q_type, 題目, 答案, rubric
) -> None:
    raw = _sq_raw(q_type, 題目, 答案, rubric, ["INc-Ⅳ-1"], ["xx-Ⅳ-99"])
    sq = _parse_subquestion(raw, "q1", _params(q_type), 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Ab-Ⅳ-1"]  # sampled pool fallback
    assert [r.編碼 for r in sq.學習表現] == ["tr-Ⅳ-1"]


def test_parse_subquestion_canonicalizes_spelling_and_fills_說明() -> None:
    raw = _sq_raw(
        "Simple multiple-choice", "Q? (A) x (B) y", "A", [],
        ["Ab-IV-1"], ["tr-IV-1"],  # ASCII spellings of Unicode-canonical codes
    )
    sq = _parse_subquestion(raw, "q1", _params(), 1)
    assert sq is not None
    assert sq.學習內容[0].編碼 == "Ab-Ⅳ-1"
    assert sq.學習內容[0].說明 == "物質的粒子模型與物質三態。"  # curriculum, not "LLM 說明"
    assert sq.學習表現[0].編碼 == "tr-Ⅳ-1"


def test_parse_subquestion_falls_back_to_pool_when_metadata_missing() -> None:
    raw = _sq_raw("Simple multiple-choice", "Q? (A) x (B) y", "A", [], [], [])
    del raw["學習內容"], raw["學習表現"]
    sq = _parse_subquestion(raw, "q1", _params(), 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Ab-Ⅳ-1"]
    assert [r.編碼 for r in sq.學習表現] == ["tr-Ⅳ-1"]


def test_parse_subquestion_drops_only_invalid_codes_when_mixed() -> None:
    raw = _sq_raw(
        "Simple multiple-choice", "Q? (A) x (B) y", "A", [],
        ["Aa-IV-3", "INc-Ⅳ-1"], ["pa-Ⅳ-1", "xx-Ⅳ-99"],
    )
    sq = _parse_subquestion(raw, "q1", _params(), 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Aa-IV-3"]  # invalid dropped, no fallback
    assert [r.編碼 for r in sq.學習表現] == ["pa-Ⅳ-1"]


def test_parse_subquestion_cfg_codes_stay_verbatim() -> None:
    """Explicit per-小題 web/API selections are forced verbatim — never repaired."""
    params = _params(
        subquestion_configs=[
            {"learning_content": ["Ka-Ⅳ-1"], "learning_performance": ["pa-Ⅳ-1"]}
        ],
    )
    raw = _sq_raw(
        "Simple multiple-choice", "Q? (A) x (B) y", "A", [],
        ["INc-Ⅳ-1"], ["xx-Ⅳ-99"],
    )
    sq = _parse_subquestion(raw, "q1", params, 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Ka-Ⅳ-1"]
    assert [r.編碼 for r in sq.學習表現] == ["pa-Ⅳ-1"]


def test_parse_question_repairs_subquestion_codes() -> None:
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "subquestions": [
            {
                "序號": 1,
                "題型": "Simple multiple-choice",
                "題目": "Q? (A) 甲 (B) 乙",
                "答案": "A",
                "答案解析": "解析",
                "學習內容": [{"編碼": "INc-Ⅳ-1", "說明": "幻覺"}],
                "學習表現": [{"編碼": "tr-IV-1", "說明": ""}],
            }
        ],
        "題目": ["文本", "Q?"],
        "正確解題分析": ["A"],
    }
    question = _parse_question(raw, "ns_test_001", _params(), "test-model")
    assert [r.編碼 for r in question.subquestions[0].學習內容] == ["Ab-Ⅳ-1"]  # pool
    assert [r.編碼 for r in question.subquestions[0].學習表現] == ["tr-Ⅳ-1"]  # canonicalized
