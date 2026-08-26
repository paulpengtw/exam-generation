"""Subject-specific shim over src.common.curriculum_loader for 社會領域.

The subject → 科目-prefix map and per-file env-var overrides are sourced from
``src.common.subject_spec.SOCIAL_STUDIES`` so the spec lives in one place.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from src.common import curriculum_loader as _base
from src.common.subject_spec import SOCIAL_STUDIES as _SPEC

_DATA_DIR = _SPEC.data_dir

# 科目 prefixes that match each QuestionSubject value — read from the spec.
# 社_* codes are cross-subject general 學習表現 and apply to all 社會 subjects.
_SUBJECT_TO_PREFIXES: dict[str, set[str]] = _SPEC.subject_to_prefixes


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_curriculum_json(
    path: Path,
    key: Literal["學習內容", "學習表現"],
) -> dict:
    return _base.tag_entries_with_admitted_subjects(
        _load_json(path),
        key,
        subject_to_prefixes=_SUBJECT_TO_PREFIXES,
    )


def load_learning_content(path: Path | None = None) -> dict:
    if path is not None:
        return _load_curriculum_json(path, "學習內容")
    env = os.environ.get(_SPEC.lc_path_env or "")
    if env:
        return _load_curriculum_json(Path(env), "學習內容")
    data_dir = Path(os.environ.get(_SPEC.curriculum_dir_env, str(_DATA_DIR)))
    return _base.load_learning_content(
        data_dir,
        subject_to_prefixes=_SUBJECT_TO_PREFIXES,
    )


def load_learning_performance(path: Path | None = None) -> dict:
    if path is not None:
        return _load_curriculum_json(path, "學習表現")
    env = os.environ.get(_SPEC.lp_path_env or "")
    if env:
        return _load_curriculum_json(Path(env), "學習表現")
    data_dir = Path(os.environ.get(_SPEC.curriculum_dir_env, str(_DATA_DIR)))
    return _base.load_learning_performance(
        data_dir,
        subject_to_prefixes=_SUBJECT_TO_PREFIXES,
    )


def load_performance_intro(path: Path | None = None) -> str:
    if path is not None:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
    env = os.environ.get(_SPEC.lp_intro_path_env or "")
    if env:
        p = Path(env)
        return p.read_text(encoding="utf-8") if p.exists() else ""
    return _base.load_performance_intro(_DATA_DIR)


def allowed_learning_content(
    data: dict,
    learning_stage: str,
    subject: str | None = None,
) -> list[dict]:
    return _base.allowed_learning_content(
        data, learning_stage,
        subject=subject,
        subject_to_prefixes=_SUBJECT_TO_PREFIXES,
    )


def allowed_learning_performance(
    data: dict,
    learning_stage: str,
    subject: str | None = None,
) -> list[dict]:
    return _base.allowed_learning_performance(
        data, learning_stage,
        subject=subject,
        subject_to_prefixes=_SUBJECT_TO_PREFIXES,
    )


def entries_with_admitted_subjects(
    data: dict,
    key: Literal["學習內容", "學習表現"],
    learning_stage: str,
) -> list[dict]:
    return _base.entries_with_admitted_subjects(
        data,
        key,
        learning_stage,
        subject_to_prefixes=_SUBJECT_TO_PREFIXES,
    )


content_instructions = _base.content_instructions
performance_instructions = _base.performance_instructions
