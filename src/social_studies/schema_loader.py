"""Load social studies question parameter schemas from CSV files."""

from __future__ import annotations

import csv
import os
from enum import Enum
from pathlib import Path

_DEFAULT_DIR = Path(__file__).parent.parent.parent / "data" / "social_studies" / "curriculum"

# Categories for social studies — includes 科目 for 108課綱 subject targeting.
_CATEGORIES = ("情境", "題型種類", "題型", "閱讀歷程", "文本形式", "科目", "題目內容類型")


def _resolve_dir(path: Path | None = None) -> Path:
    if path is not None:
        return path
    env_path = os.environ.get("SOCIAL_STUDIES_CURRICULUM_DIR")
    return Path(env_path) if env_path else _DEFAULT_DIR


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_schemas(curriculum_dir: Path | None = None) -> dict:
    d = _resolve_dir(curriculum_dir)

    meta_rows = _read_csv(d / "schema_meta.csv")
    meta = {row["欄位"]: row["值"] for row in meta_rows}
    grades_raw = meta.get("grades", "")
    grades = [int(g.strip()) for g in grades_raw.split(";") if g.strip()]

    param_rows = _read_csv(d / "schema_parameters.csv")
    categories: dict[str, list[dict[str, str]]] = {c: [] for c in _CATEGORIES}
    for row in param_rows:
        cat = row.get("類別", "")
        if cat in categories:
            categories[cat].append({"value": row["value"], "instruction": row.get("instruction", "")})

    return {
        "學習階段": meta.get("學習階段", ""),
        "grades": grades,
        **categories,
    }


def _extract_values(entries: list[dict]) -> list[str]:
    return [entry["value"] for entry in entries]


def _build_str_enum(name: str, values: list[str]) -> type:
    members = {f"ITEM_{i}": v for i, v in enumerate(values)}
    return Enum(name, members, type=str)  # type: ignore[return-value]


def build_enums(schemas: dict) -> tuple:
    """Build (QuestionContext, QuestionSetType, QuestionType, ReadingProcess, TextForm, QuestionSubject)."""
    QuestionContext = _build_str_enum("QuestionContext", _extract_values(schemas["情境"]))
    QuestionSetType = _build_str_enum("QuestionSetType", _extract_values(schemas["題型種類"]))
    QuestionType = _build_str_enum("QuestionType", _extract_values(schemas["題型"]))
    ReadingProcess = _build_str_enum("ReadingProcess", _extract_values(schemas["閱讀歷程"]))
    TextForm = _build_str_enum("TextForm", _extract_values(schemas["文本形式"]))
    QuestionSubject = _build_str_enum("QuestionSubject", _extract_values(schemas.get("科目", [])))
    return QuestionContext, QuestionSetType, QuestionType, ReadingProcess, TextForm, QuestionSubject


def load_grades(schemas: dict) -> list[int]:
    return schemas["grades"]


def load_learning_stage(schemas: dict) -> str:
    return schemas["學習階段"]


def build_instructions(schemas: dict) -> dict[str, dict[str, str]]:
    """Return {category: {value: instruction}} for all non-empty instructions."""
    result: dict[str, dict[str, str]] = {}
    for category in _CATEGORIES:
        mapping = {}
        for entry in schemas.get(category, []):
            if entry.get("instruction"):
                mapping[entry["value"]] = entry["instruction"]
        result[category] = mapping
    return result
