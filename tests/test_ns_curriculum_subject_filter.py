"""AC2 regression: NS curriculum_loader.allowed_learning_content must honour the subject arg.

Today the NS shim does ``del subject`` and discards it entirely.  After the fix
it must route through the common implementation with an empty
subject_to_prefixes map so that an explicit subject filters by exact 科目 match
while subject=None (all current call sites) continues to return the full stage
pool unchanged.

This test is intentionally written BEFORE the fix so it fails on the current
code and turns green once AC2 is implemented.
"""

from __future__ import annotations

import pytest

from src.natural_sciences.curriculum_loader import (
    allowed_learning_content,
    load_learning_content,
)


@pytest.fixture(scope="module")
def ns_lc_data() -> dict:
    return load_learning_content()


def test_ns_allowed_learning_content_no_subject_returns_all_stage_entries(ns_lc_data: dict) -> None:
    """Baseline: subject=None continues to return the full stage pool (byte-identical)."""
    stage = "第四學習階段"
    entries = allowed_learning_content(ns_lc_data, stage)
    assert entries, "should return non-empty pool for 第四學習階段"
    assert all(e["學習階段"] == stage for e in entries)


def test_ns_allowed_learning_content_explicit_subject_returns_subset(ns_lc_data: dict) -> None:
    """Explicit subject must filter to a proper subset (AC2 behaviour).

    Before the fix ``del subject`` makes this equal to the full stage pool —
    the assertion ``len(filtered) < len(all_entries)`` will fail.
    """
    stage = "第四學習階段"
    all_entries = allowed_learning_content(ns_lc_data, stage)
    # 第四 has 100 理化 entries mixed with 生物, 地球科學 and shared("") entries
    filtered = allowed_learning_content(ns_lc_data, stage, subject="理化")
    assert len(filtered) < len(all_entries), (
        "NS allowed_learning_content with an explicit subject should return a proper subset; "
        "current code ignores subject (del subject) — this is AC2"
    )
    assert all(e["科目"] == "理化" for e in filtered), (
        "All returned entries must have 科目=='理化'"
    )
    assert len(filtered) > 0, "should find 理化 entries in 第四學習階段"
