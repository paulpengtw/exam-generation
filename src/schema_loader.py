"""Load question parameter schemas from JSON config and build dynamic enums."""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent.parent / "question_schemas.json"

# All categories that use the {value, instruction?} object format.
_CATEGORIES = ("情境", "題型種類", "題型", "數學思考", "question_style")


def _resolve_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    env_path = os.environ.get("QUESTION_SCHEMAS_PATH")
    return Path(env_path) if env_path else _DEFAULT_PATH


def load_schemas(path: Path | None = None) -> dict:
    """Load and return the raw question_schemas.json dict."""
    resolved = _resolve_path(path)
    with open(resolved) as f:
        return json.load(f)


def _extract_values(entries: list[dict]) -> list[str]:
    """Extract the 'value' field from a list of {value, instruction?} objects."""
    return [entry["value"] for entry in entries]


def _build_str_enum(name: str, values: list[str]) -> type:
    """Create a str-mixin enum from a list of string values."""
    members = {f"ITEM_{i}": v for i, v in enumerate(values)}
    return Enum(name, members, type=str)  # type: ignore[return-value]


def build_enums(schemas: dict) -> tuple:
    """Build (QuestionContext, QuestionSetType, QuestionType, MathThinking, QuestionStyle)."""
    QuestionContext = _build_str_enum("QuestionContext", _extract_values(schemas["情境"]))
    QuestionSetType = _build_str_enum("QuestionSetType", _extract_values(schemas["題型種類"]))
    QuestionType = _build_str_enum("QuestionType", _extract_values(schemas["題型"]))
    MathThinking = _build_str_enum("MathThinking", _extract_values(schemas["數學思考"]))
    QuestionStyle = _build_str_enum("QuestionStyle", _extract_values(schemas["question_style"]))
    return QuestionContext, QuestionSetType, QuestionType, MathThinking, QuestionStyle


def load_grades(schemas: dict) -> list[int]:
    """Return the list of target grades from question_schemas.json."""
    return schemas["grades"]


def load_learning_stage(schemas: dict) -> str:
    """Return the 學習階段 name from question_schemas.json."""
    return schemas["學習階段"]


def build_instructions(schemas: dict) -> dict[str, dict[str, str]]:
    """Return {category: {value: instruction}} for all categories.

    Only entries with a non-empty instruction are included in each inner dict.
    """
    result: dict[str, dict[str, str]] = {}
    for category in _CATEGORIES:
        mapping = {}
        for entry in schemas[category]:
            if entry.get("instruction"):
                mapping[entry["value"]] = entry["instruction"]
        result[category] = mapping
    return result
