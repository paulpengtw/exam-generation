"""Tests proving natural-sciences few-shot examples are discovered by item family."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.natural_sciences.data_loader import (
    folder_for_question_type,
    load_few_shot_example_groups,
)

_FEW_SHOT_DIR = Path(__file__).parent.parent / "data" / "natural_sciences" / "few_shot"

ITEM_FAMILIES = [
    "Simple multiple-choice",
    "Complex multiple-choice",
    "Constructed response",
]


def test_folder_for_question_type_maps_all_families() -> None:
    assert folder_for_question_type("Simple multiple-choice") == "Simple-multiple-choice"
    assert folder_for_question_type("Complex multiple-choice") == "Complex-multiple-choice"
    assert folder_for_question_type("Constructed response") == "Constructed-response"
    assert folder_for_question_type(None) is None


@pytest.mark.parametrize("q_type", ITEM_FAMILIES)
def test_each_item_family_has_at_least_one_example(q_type: str) -> None:
    groups = load_few_shot_example_groups(_FEW_SHOT_DIR, q_type=q_type)
    assert len(groups) >= 1, f"No few-shot examples found for '{q_type}'"


@pytest.mark.parametrize("q_type", ITEM_FAMILIES)
def test_examples_have_required_fields(q_type: str) -> None:
    groups = load_few_shot_example_groups(_FEW_SHOT_DIR, q_type=q_type)
    for group in groups:
        for ex in group:
            q = ex.get("question", ex)
            assert q.get("文本"), f"Missing 文本 in example: {ex.get('description')}"
            assert q.get("題型種類"), f"Missing 題型種類 in example: {ex.get('description')}"
            assert q.get("題型"), f"Missing 題型 in example: {ex.get('description')}"
            assert q.get("情境"), f"Missing 情境 in example: {ex.get('description')}"


@pytest.mark.parametrize("q_type", ITEM_FAMILIES)
def test_subquestions_have_learning_codes(q_type: str) -> None:
    groups = load_few_shot_example_groups(_FEW_SHOT_DIR, q_type=q_type)
    for group in groups:
        for ex in group:
            q = ex.get("question", ex)
            for sq in q.get("subquestions", []):
                assert sq.get("學習內容") is not None, (
                    f"Missing 學習內容 in subquestion of '{ex.get('description')}'"
                )
                assert sq.get("學習表現") is not None, (
                    f"Missing 學習表現 in subquestion of '{ex.get('description')}'"
                )


def test_all_examples_combined_covers_all_families() -> None:
    all_groups = load_few_shot_example_groups(_FEW_SHOT_DIR)
    assert len(all_groups) >= len(ITEM_FAMILIES), (
        "Combined load returned fewer groups than item families"
    )


def test_dry_run_generation_does_not_crash(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.natural_sciences.cli", "generate",
         "--dry-run", "--seed", "1", "--output", str(tmp_path)],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"dry-run generation failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
