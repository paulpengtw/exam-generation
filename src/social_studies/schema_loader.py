"""Load social-studies question parameter schemas from CSV files.

Thin shim over ``src.common.schema_loader``.  All file-reading, malformed-row
handling, and enum-building utilities live in the common module.  This file
owns only the SS-specific category-to-enum names and re-exports the public
helpers with their original call signatures unchanged.

Directory, env-var, and category data are sourced exclusively from
``src.common.subject_spec.SOCIAL_STUDIES`` — no per-subject constants here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from src.common import schema_loader as _base
from src.common.subject_spec import SOCIAL_STUDIES as _SPEC

_ENUM_NAMES = {
    "情境": "QuestionContext",
    "題型種類": "QuestionSetType",
    "題型": "QuestionType",
    "閱讀歷程": "ReadingProcess",
    "文本形式": "TextForm",
    "科目": "QuestionSubject",
}
_SCHEMA_METADATA_KEYS = {"學習階段", "grades"}


def load_schemas(curriculum_dir: Path | None = None) -> dict:
    return _base.load_schemas(
        _SPEC.schema_categories,
        _SPEC.curriculum_dir_env,
        _SPEC.data_dir,
        curriculum_dir,
    )


def build_enums_by_category(schemas: Mapping[str, list[dict]]) -> Mapping[str, type]:
    """Build one string enum for every schema category keyed by its CSV name."""
    categories = list(_SPEC.schema_categories)
    categories.extend(
        category
        for category in schemas
        if category not in _SCHEMA_METADATA_KEYS and category not in categories
    )
    return {
        category: _base.build_str_enum(
            _ENUM_NAMES.get(category, category),
            _base.extract_values(schemas.get(category, [])),
        )
        for category in categories
    }


def load_grades(schemas: dict) -> list[int]:
    return _base.load_grades(schemas)


def load_learning_stage(schemas: dict) -> str:
    return _base.load_learning_stage(schemas)


def build_instructions(schemas: dict) -> dict[str, dict[str, str]]:
    """Return ``{category: {value: instruction}}`` for all non-empty instructions."""
    return _base.build_instructions(schemas, _SPEC.schema_categories)
