"""Tests for the shared admission lookup module (src/common/admission.py).

See docs/adr/0020-dependent-parameter-rules-ship-as-data-in-the-schema-payload.md.
"""

from __future__ import annotations

from src.common.admission import (
    admits,
    admitted_parents,
    admitted_parents_by_code,
    entries_admitted_by,
)

# --- admitted_parents ---------------------------------------------------


def test_admitted_parents_returns_tagged_list():
    entry = {"admitted_by": {"科目": ["歷史", "跨科"]}}
    assert admitted_parents(entry, "科目") == ["歷史", "跨科"]


def test_admitted_parents_missing_key_returns_none():
    entry = {"admitted_by": {"科目": ["歷史"]}}
    assert admitted_parents(entry, "內容領域") is None


def test_admitted_parents_non_list_tag_returns_empty_list():
    entry = {"admitted_by": {"科目": "歷史"}}
    assert admitted_parents(entry, "科目") == []


def test_admitted_parents_missing_admitted_by_returns_none():
    entry = {"value": "歷Ka-Ⅳ-1"}
    assert admitted_parents(entry, "科目") is None


# --- admits ---------------------------------------------------------------


def test_admits_true_for_member():
    entry = {"admitted_by": {"科目": ["歷史", "跨科"]}}
    assert admits(entry, "科目", "歷史") is True


def test_admits_false_for_non_member():
    entry = {"admitted_by": {"科目": ["歷史", "跨科"]}}
    assert admits(entry, "科目", "地理") is False


def test_admits_true_when_unscoped():
    entry = {"admitted_by": {"科目": ["歷史"]}}
    assert admits(entry, "內容領域", "Civic Roles and Identities") is True


def test_admits_false_for_non_list_tag():
    entry = {"admitted_by": {"科目": "歷史"}}
    assert admits(entry, "科目", "歷史") is False


# --- entries_admitted_by ---------------------------------------------------


def test_entries_admitted_by_keeps_order_and_identity():
    tagged = {"value": "A", "admitted_by": {"科目": ["歷史"]}}
    untagged = {"value": "B"}
    other_tagged = {"value": "C", "admitted_by": {"科目": ["地理"]}}
    entries = [tagged, untagged, other_tagged]

    result = entries_admitted_by(entries, "科目", "歷史")

    assert result == [tagged, untagged]
    assert result[0] is tagged
    assert result[1] is untagged


def test_entries_admitted_by_excludes_non_admitting():
    tagged = {"value": "A", "admitted_by": {"科目": ["歷史"]}}
    non_admitting = {"value": "B", "admitted_by": {"科目": ["地理"]}}

    result = entries_admitted_by([tagged, non_admitting], "科目", "歷史")

    assert result == [tagged]


# --- admitted_parents_by_code ----------------------------------------------


def test_admitted_parents_by_code_unions_across_duplicate_codes():
    data = {
        "學習內容": [
            {"value": "公Aa-Ⅳ-1", "admitted_by": {"科目": ["公民與社會"]}},
            {"value": "公Aa-Ⅳ-1", "admitted_by": {"科目": ["跨科"]}},
        ]
    }
    result = admitted_parents_by_code(data, "學習內容", "科目")
    assert result == {"公Aa-Ⅳ-1": ["公民與社會", "跨科"]}


def test_admitted_parents_by_code_preserves_first_seen_order_no_duplicates():
    data = {
        "學習內容": [
            {"value": "X", "admitted_by": {"科目": ["跨科", "歷史"]}},
            {"value": "X", "admitted_by": {"科目": ["歷史", "地理"]}},
        ]
    }
    result = admitted_parents_by_code(data, "學習內容", "科目")
    assert result == {"X": ["跨科", "歷史", "地理"]}


def test_admitted_parents_by_code_skips_non_dict_rows():
    data = {"學習內容": ["not-a-dict", {"value": "X", "admitted_by": {"科目": ["歷史"]}}]}
    result = admitted_parents_by_code(data, "學習內容", "科目")
    assert result == {"X": ["歷史"]}


def test_admitted_parents_by_code_skips_rows_without_str_value():
    data = {
        "學習內容": [
            {"value": 123, "admitted_by": {"科目": ["歷史"]}},
            {"admitted_by": {"科目": ["地理"]}},
        ]
    }
    result = admitted_parents_by_code(data, "學習內容", "科目")
    assert result == {}


def test_admitted_parents_by_code_skips_rows_whose_tag_is_not_a_list():
    data = {
        "學習內容": [
            {"value": "X", "admitted_by": {"科目": "歷史"}},
            {"value": "X", "admitted_by": {}},
        ]
    }
    result = admitted_parents_by_code(data, "學習內容", "科目")
    assert result == {}


def test_admitted_parents_by_code_drops_non_str_members():
    data = {
        "學習內容": [
            {"value": "X", "admitted_by": {"科目": ["歷史", 1, None, "地理"]}},
        ]
    }
    result = admitted_parents_by_code(data, "學習內容", "科目")
    assert result == {"X": ["歷史", "地理"]}


def test_admitted_parents_by_code_missing_key_returns_empty_dict():
    data = {"學習內容": []}
    result = admitted_parents_by_code(data, "學習表現", "科目")
    assert result == {}


# --- real-data check --------------------------------------------------------


def test_real_data_social_studies_admission():
    from src.social_studies.curriculum_loader import load_learning_content

    data = load_learning_content()
    rows = {
        row["value"]: row
        for row in data.get("學習內容", [])
        if isinstance(row, dict) and row.get("value") in ("公Aa-Ⅳ-1", "歷Ka-Ⅳ-1")
    }

    gong = rows["公Aa-Ⅳ-1"]
    assert admits(gong, "內容領域", "Civic Roles and Identities") is True
    assert admits(gong, "科目", "地理") is False

    li = rows["歷Ka-Ⅳ-1"]
    assert admits(li, "內容領域", "Civic Roles and Identities") is True
    assert admitted_parents(li, "科目") == ["歷史", "跨科"]
