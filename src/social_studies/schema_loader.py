"""Load social studies question parameter schemas and build dynamic enums."""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "social_studies_schemas.json"

# Categories for social studies — replaces 數學思考 with 閱讀歷程 + 文本形式.
_CATEGORIES = ("情境", "題型種類", "題型", "閱讀歷程", "文本形式", "question_style")


def _resolve_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    env_path = os.environ.get("SOCIAL_STUDIES_SCHEMAS_PATH")
    return Path(env_path) if env_path else _DEFAULT_PATH


def load_schemas(path: Path | None = None) -> dict:
    resolved = _resolve_path(path)
    with open(resolved) as f:
        return json.load(f)


def _extract_values(entries: list[dict]) -> list[str]:
    return [entry["value"] for entry in entries]


def _build_str_enum(name: str, values: list[str]) -> type:
    members = {f"ITEM_{i}": v for i, v in enumerate(values)}
    return Enum(name, members, type=str)  # type: ignore[return-value]


def build_enums(schemas: dict) -> tuple:
    """Build (QuestionContext, QuestionSetType, QuestionType, ReadingProcess, TextForm, QuestionStyle)."""
    QuestionContext = _build_str_enum("QuestionContext", _extract_values(schemas["情境"]))
    QuestionSetType = _build_str_enum("QuestionSetType", _extract_values(schemas["題型種類"]))
    QuestionType = _build_str_enum("QuestionType", _extract_values(schemas["題型"]))
    ReadingProcess = _build_str_enum("ReadingProcess", _extract_values(schemas["閱讀歷程"]))
    TextForm = _build_str_enum("TextForm", _extract_values(schemas["文本形式"]))
    QuestionStyle = _build_str_enum("QuestionStyle", _extract_values(schemas["question_style"]))
    return QuestionContext, QuestionSetType, QuestionType, ReadingProcess, TextForm, QuestionStyle


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
