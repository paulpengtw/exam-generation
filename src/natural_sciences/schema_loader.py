"""Load natural-sciences question parameter schemas from CSV files.

Thin shim over ``src.common.schema_loader``.  All file-reading, malformed-row
handling, and enum-building utilities live in the common module.  This file
owns only the NS-specific ``build_enums`` tuple signature and the NS-only
``subcontexts_for_context`` helper (no SS counterpart).

Directory, env-var, and category data are sourced exclusively from
``src.common.subject_spec.NATURAL_SCIENCES`` — no per-subject constants here.
"""

from __future__ import annotations

from pathlib import Path

from src.common import schema_loader as _base
from src.common.subject_spec import NATURAL_SCIENCES as _SPEC


def load_schemas(curriculum_dir: Path | None = None) -> dict:
    return _base.load_schemas(
        _SPEC.schema_categories,
        _SPEC.curriculum_dir_env,
        _SPEC.data_dir,
        curriculum_dir,
    )


def build_enums(schemas: dict) -> tuple:
    """Build natural-sciences schema enums."""
    QuestionContext = _base.build_str_enum(
        "QuestionContext", _base.extract_values(schemas["情境"])
    )
    QuestionSubContext = _base.build_str_enum(
        "QuestionSubContext", _base.extract_values(schemas["情境子類別"])
    )
    QuestionSetType = _base.build_str_enum(
        "QuestionSetType", _base.extract_values(schemas["題型種類"])
    )
    QuestionType = _base.build_str_enum(
        "QuestionType", _base.extract_values(schemas["題型"])
    )
    ScienceCompetency = _base.build_str_enum(
        "ScienceCompetency", _base.extract_values(schemas["科學能力"])
    )
    return QuestionContext, QuestionSubContext, QuestionSetType, QuestionType, ScienceCompetency


def load_grades(schemas: dict) -> list[int]:
    return _base.load_grades(schemas)


def load_learning_stage(schemas: dict) -> str:
    return _base.load_learning_stage(schemas)


def build_instructions(schemas: dict) -> dict[str, dict[str, str]]:
    """Return ``{category: {value: instruction}}`` for all non-empty instructions."""
    return _base.build_instructions(schemas, _SPEC.schema_categories)


# NS-only helper — no SS counterpart; kept here rather than pushed into common.
def subcontexts_for_context(schemas: dict, context: str) -> list[dict[str, str]]:
    return [
        entry for entry in schemas.get("情境子類別", [])
        if entry.get("parent") == context
    ]
