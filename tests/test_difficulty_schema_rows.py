"""Data-file smoke tests: 難度 rows exist for every subject."""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SS_CSV = REPO_ROOT / "data" / "social_studies" / "curriculum" / "schema_parameters.csv"
NS_CSV = REPO_ROOT / "data" / "natural_sciences" / "curriculum" / "schema_parameters.csv"
MATH_JSON = REPO_ROOT / "question_schemas.json"

_REQUIRED = {"easy", "medium", "hard"}


def _csv_values(path: Path, category: str) -> dict[str, str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {
            row["value"]: row.get("instruction", "")
            for row in csv.DictReader(f)
            if row.get("類別") == category
        }


def test_social_studies_csv_has_difficulty_rows():
    values = _csv_values(SS_CSV, "難度")
    assert set(values) == _REQUIRED
    assert all(v.strip() for v in values.values()), (
        "SS 難度 rows must carry non-empty instructions"
    )


def test_natural_sciences_csv_has_no_difficulty_rows():
    """NS #282: 難度 rows must be absent from NS schema_parameters.csv."""
    values = _csv_values(NS_CSV, "難度")
    assert len(values) == 0, (
        f"NS schema_parameters.csv must have no 難度 rows, found: {list(values)}"
    )


def test_math_schemas_json_has_difficulty_category():
    data = json.loads(MATH_JSON.read_text(encoding="utf-8"))
    assert "難度" in data
    rows = data["難度"]
    assert {row["value"] for row in rows} == _REQUIRED
    assert all(row.get("instruction", "").strip() for row in rows), (
        "math 難度 entries must carry non-empty instructions"
    )
