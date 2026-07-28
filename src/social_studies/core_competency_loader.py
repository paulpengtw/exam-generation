"""Subject-specific shim over src.common.core_competency_loader for 社會領域."""

from __future__ import annotations

import os
from pathlib import Path

from src.common import core_competency_loader as _base
from src.common.subject_spec import SOCIAL_STUDIES as _SPEC

_DATA_PATH = _SPEC.core_competency_data_path
_SUBJECT_PREFIX = _SPEC.core_competency_subject_prefix


def load_core_competencies(path: Path | None = None) -> dict:
    if path is None:
        env = os.environ.get(_SPEC.core_competency_path_env)
        path = Path(env) if env else _DATA_PATH
    return _base.load_core_competencies(path)


def build_core_competency_enum(data: dict) -> type:
    return _base.build_core_competency_enum(
        data, subject_prefix=_SUBJECT_PREFIX, enum_name=_SPEC.core_competency_enum_name
    )


allowed_competencies = _base.allowed_competencies
competency_instructions = _base.competency_instructions
competency_meta = _base.competency_meta
stage_code_for = _base.stage_code_for
