"""Load social-studies question parameter schemas from CSV files.

Thin shim over ``src.common.schema_loader``.  All file-reading, malformed-row
handling, and enum-building utilities live in the common module.  This file
owns only the SS-specific ``build_enums`` tuple signature and re-exports the
four public helpers with their original call signatures unchanged.

Directory, env-var, and category data are sourced exclusively from
``src.common.subject_spec.SOCIAL_STUDIES`` — no per-subject constants here.
"""

from __future__ import annotations

from pathlib import Path

from src.common import schema_loader as _base
from src.common.subject_spec import SOCIAL_STUDIES as _SPEC


def load_schemas(curriculum_dir: Path | None = None) -> dict:
    return _base.load_schemas(
        _SPEC.schema_categories,
        _SPEC.curriculum_dir_env,
        _SPEC.data_dir,
        curriculum_dir,
    )


def build_enums(schemas: dict) -> tuple:
    """Build (QuestionContext, QuestionSetType, QuestionType, ReadingProcess, TextForm, QuestionSubject)."""
    QuestionContext = _base.build_str_enum(
        "QuestionContext", _base.extract_values(schemas["情境"])
    )
    QuestionSetType = _base.build_str_enum(
        "QuestionSetType", _base.extract_values(schemas["題型種類"])
    )
    QuestionType = _base.build_str_enum(
        "QuestionType", _base.extract_values(schemas["題型"])
    )
    ReadingProcess = _base.build_str_enum(
        "ReadingProcess", _base.extract_values(schemas["閱讀歷程"])
    )
    TextForm = _base.build_str_enum(
        "TextForm", _base.extract_values(schemas["文本形式"])
    )
    QuestionSubject = _base.build_str_enum(
        "QuestionSubject", _base.extract_values(schemas.get("科目", []))
    )
    return QuestionContext, QuestionSetType, QuestionType, ReadingProcess, TextForm, QuestionSubject


def load_grades(schemas: dict) -> list[int]:
    return _base.load_grades(schemas)


def load_learning_stage(schemas: dict) -> str:
    return _base.load_learning_stage(schemas)


def build_instructions(schemas: dict) -> dict[str, dict[str, str]]:
    """Return ``{category: {value: instruction}}`` for all non-empty instructions."""
    return _base.build_instructions(schemas, _SPEC.schema_categories)
