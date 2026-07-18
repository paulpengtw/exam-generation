"""Subject-specific shim over src.common.curriculum_loader for 自然科學領域."""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.common import curriculum_loader as _base

_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "natural_sciences" / "curriculum"


def grade_to_learning_stage(grade: int) -> str:
    """Map a grade (3-12) to its 自然科學 學習階段.

    Mirrors ``src.sampler.grade_to_learning_stage`` (math), but 自然科學 has
    no 第一學習階段 — the subject starts at grade 3 (學習階段_to_grades in the
    curriculum JSON covers stages 二/三/四/五 only).
    """
    if 3 <= grade <= 4:
        return "第二學習階段"
    if 5 <= grade <= 6:
        return "第三學習階段"
    if 7 <= grade <= 9:
        return "第四學習階段"
    if 10 <= grade <= 12:
        return "第五學習階段"
    raise ValueError(f"grade {grade} has no 自然科學 學習階段 (must be 3-12)")


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_learning_content(path: Path | None = None) -> dict:
    if path is not None:
        return _load_json(path)
    env = os.environ.get("NATURAL_SCIENCES_LEARNING_CONTENT_PATH")
    if env:
        return _load_json(Path(env))
    return _base.load_learning_content(_DATA_DIR)


def load_learning_performance(path: Path | None = None) -> dict:
    if path is not None:
        return _load_json(path)
    env = os.environ.get("NATURAL_SCIENCES_LEARNING_PERFORMANCE_PATH")
    if env:
        return _load_json(Path(env))
    return _base.load_learning_performance(_DATA_DIR)


def load_performance_intro(path: Path | None = None) -> str:
    if path is not None:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
    env = os.environ.get("NATURAL_SCIENCES_LEARNING_PERFORMANCE_INTRO_PATH")
    if env:
        p = Path(env)
        return p.read_text(encoding="utf-8") if p.exists() else ""
    return _base.load_performance_intro(_DATA_DIR)


def allowed_learning_content(
    data: dict,
    learning_stage: str,
    subject: str | None = None,
) -> list[dict]:
    del subject
    return [e for e in data["學習內容"] if e["學習階段"] == learning_stage]


def allowed_learning_performance(
    data: dict,
    learning_stage: str,
    subject: str | None = None,
) -> list[dict]:
    del subject
    return [e for e in data["學習表現"] if e["學習階段"] == learning_stage]


content_instructions = _base.content_instructions
performance_instructions = _base.performance_instructions
