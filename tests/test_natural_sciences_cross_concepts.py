"""跨科概念 relevance filter with full-taxonomy fallback (issue #91)."""

from __future__ import annotations

import re

from src.natural_sciences.curriculum_loader import (
    load_learning_content,
    relevant_cross_concepts,
)

_ROWS = load_learning_content()["跨科概念"]


def _concept_codes(rows):
    return {
        m.group(1)
        for row in rows
        if (m := re.search(r"（\s*([A-Za-z]+)\s*）", row["跨科概念"]))
    }


def test_stage4_prefix_narrows_to_parent_concept_group():
    """次主題 Ab belongs to 物質與能量（INa）→ keep the whole 6-row INa group."""
    rows = relevant_cross_concepts(_ROWS, ["Ab-Ⅳ-1"])
    assert _concept_codes(rows) == {"INa"}
    assert len(rows) == 6


def test_stage23_in_prefix_matches_concept_directly():
    rows = relevant_cross_concepts(_ROWS, ["INf-III-1"])
    assert _concept_codes(rows) == {"INf"}
    assert len(rows) == 5


def test_in_prefix_does_not_leak_into_subtheme_na():
    """'INa'[1:] == 'Na' is a real 次主題 code — INa must match the concept only."""
    rows = relevant_cross_concepts(_ROWS, ["INa-II-1"])
    assert _concept_codes(rows) == {"INa"}


def test_stage5_prefix_strips_subject_letter():
    """BDa = B(生物) + 次主題 Da; Da belongs to 構造與功能（INb）→ 5 rows."""
    rows = relevant_cross_concepts(_ROWS, ["BDa-Ⅴa-1"])
    assert _concept_codes(rows) == {"INb"}
    assert len(rows) == 5


def test_multiple_codes_union_their_concept_groups():
    rows = relevant_cross_concepts(_ROWS, ["Ab-Ⅳ-1", "Ka-Ⅳ-1"])
    assert _concept_codes(rows) == {"INa", "INe"}
    assert len(rows) == 19  # 6 INa rows + 13 INe rows


def test_unknown_prefix_falls_back_to_full_taxonomy():
    assert relevant_cross_concepts(_ROWS, ["ZZZ-IV-1"]) == _ROWS


def test_empty_codes_fall_back_to_full_taxonomy():
    assert relevant_cross_concepts(_ROWS, []) == _ROWS
