"""AC3 regression: schema_loader must skip rows with empty/missing 'value' AND warn.

Today:
  - SS ``load_schemas`` uses ``row["value"]`` — includes an empty-value entry in
    the returned categories dict (KeyError if column is missing from header).
  - NS ``load_schemas`` uses ``row.get("value", "")`` — also includes the entry
    (filtering only happens later in ``_extract_values``), and never logs.

After the fix both loaders must:
  1. Skip the row (not include it in the returned dict's category list).
  2. Emit a ``logging.WARNING`` naming the file and the offending row.

This test is written BEFORE the fix so it fails for both subjects; it turns
green once AC3 is implemented.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

def _write_minimal_curriculum(tmp_path: Path) -> Path:
    """Create a minimal but valid curriculum dir with one malformed parameter row."""
    (tmp_path / "schema_meta.csv").write_text(
        "欄位,值\n學習階段,第四學習階段\ngrades,7;8;9\n",
        encoding="utf-8-sig",
    )
    # One row has an empty 'value' cell — this is the malformed row.
    (tmp_path / "schema_parameters.csv").write_text(
        "類別,value,instruction\n"
        "情境,,缺少value的列\n"          # malformed — empty value
        "情境,Personal,個人情境\n",       # valid row
        encoding="utf-8-sig",
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# Social studies schema_loader
# --------------------------------------------------------------------------- #

class TestSSSchemaLoaderMalformedRow:
    def test_no_exception_on_malformed_row(self, tmp_path: Path) -> None:
        _write_minimal_curriculum(tmp_path)
        from src.social_studies.schema_loader import load_schemas
        # Must not raise KeyError or any other exception
        result = load_schemas(tmp_path)
        assert result is not None

    def test_malformed_row_absent_from_result(self, tmp_path: Path) -> None:
        _write_minimal_curriculum(tmp_path)
        from src.social_studies.schema_loader import load_schemas
        result = load_schemas(tmp_path)
        情境_values = [entry["value"] for entry in result.get("情境", [])]
        assert "" not in 情境_values, (
            "Empty-value row must be absent from the loaded schema; "
            "SS currently includes it (AC3)"
        )
        assert "Personal" in 情境_values, "Valid row must still be present"

    def test_warning_logged_for_malformed_row(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write_minimal_curriculum(tmp_path)
        from src.social_studies.schema_loader import load_schemas
        with caplog.at_level(logging.WARNING):
            load_schemas(tmp_path)
        assert any(
            "value" in record.message.lower() or "malformed" in record.message.lower()
            for record in caplog.records
            if record.levelno >= logging.WARNING
        ), (
            "A WARNING must be emitted naming the offending row; "
            "SS currently emits none (AC3)"
        )


# --------------------------------------------------------------------------- #
# Natural sciences schema_loader
# --------------------------------------------------------------------------- #

class TestNSSchemaLoaderMalformedRow:
    def test_no_exception_on_malformed_row(self, tmp_path: Path) -> None:
        _write_minimal_curriculum(tmp_path)
        from src.natural_sciences.schema_loader import load_schemas
        result = load_schemas(tmp_path)
        assert result is not None

    def test_malformed_row_absent_from_result(self, tmp_path: Path) -> None:
        _write_minimal_curriculum(tmp_path)
        from src.natural_sciences.schema_loader import load_schemas
        result = load_schemas(tmp_path)
        情境_values = [entry["value"] for entry in result.get("情境", [])]
        assert "" not in 情境_values, (
            "Empty-value row must be absent from the loaded schema; "
            "NS currently includes it in load_schemas output (AC3)"
        )
        assert "Personal" in 情境_values, "Valid row must still be present"

    def test_warning_logged_for_malformed_row(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write_minimal_curriculum(tmp_path)
        from src.natural_sciences.schema_loader import load_schemas
        with caplog.at_level(logging.WARNING):
            load_schemas(tmp_path)
        assert any(
            "value" in record.message.lower() or "malformed" in record.message.lower()
            for record in caplog.records
            if record.levelno >= logging.WARNING
        ), (
            "A WARNING must be emitted naming the offending row; "
            "NS currently emits none (AC3)"
        )
