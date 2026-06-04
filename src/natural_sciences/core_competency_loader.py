"""Subject-specific shim over src.common.core_competency_loader for 自然科學領域."""

from __future__ import annotations

import os
from pathlib import Path

from src.common import core_competency_loader as _base

_DATA_PATH = (
    Path(__file__).parent.parent.parent
    / "data" / "natural_sciences" / "curriculum" / "core_competencies.json"
)
_SUBJECT_PREFIX = "自"


def load_core_competencies(path: Path | None = None) -> dict:
    if path is None:
        env = os.environ.get("NATURAL_SCIENCES_CORE_COMPETENCIES_PATH")
        path = Path(env) if env else _DATA_PATH
    return _base.load_core_competencies(path)


def build_core_competency_enum(data: dict) -> type:
    return _base.build_core_competency_enum(
        data, subject_prefix=_SUBJECT_PREFIX, enum_name="NaturalCoreCompetency"
    )


allowed_competencies = _base.allowed_competencies
competency_instructions = _base.competency_instructions
competency_meta = _base.competency_meta
stage_code_for = _base.stage_code_for
