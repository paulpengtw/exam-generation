"""Load question parameter schemas from JSON config and build dynamic enums."""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent.parent / "question_schemas.json"


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


def _build_str_enum(name: str, values: list[str]) -> type:
    """Create a str-mixin enum from a list of string values."""
    members = {f"ITEM_{i}": v for i, v in enumerate(values)}
    return Enum(name, members, type=str)  # type: ignore[return-value]


def build_enums(schemas: dict) -> tuple:
    """Build (QuestionContext, QuestionSetType, QuestionType, MathThinking, QuestionStyle)."""
    QuestionContext = _build_str_enum("QuestionContext", schemas["情境"])
    QuestionSetType = _build_str_enum("QuestionSetType", schemas["題型種類"])
    QuestionType = _build_str_enum("QuestionType", schemas["題型"])
    MathThinking = _build_str_enum("MathThinking", schemas["數學思考"])
    QuestionStyle = _build_str_enum(
        "QuestionStyle", [entry["value"] for entry in schemas["question_style"]]
    )
    return QuestionContext, QuestionSetType, QuestionType, MathThinking, QuestionStyle


def build_style_instructions(schemas: dict) -> dict[str, str]:
    """Return {style_value: instruction} mapping from question_style entries."""
    return {entry["value"]: entry["instruction"] for entry in schemas["question_style"]}
