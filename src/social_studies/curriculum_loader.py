"""Load 108課綱 社會領域 學習內容 and 學習表現 from JSON curriculum files."""

from __future__ import annotations

import json
import os
from pathlib import Path

_CURRICULUM_DIR = (
    Path(__file__).parent.parent.parent / "data" / "social_studies" / "curriculum"
)

_DEFAULT_LC_PATH = _CURRICULUM_DIR / "learning_content.json"
_DEFAULT_LP_PATH = _CURRICULUM_DIR / "learning_performance.json"
_DEFAULT_INTRO_PATH = _CURRICULUM_DIR / "learning_performance_intro.md"

# 科目 prefixes that match each QuestionSubject value.
# 社_* codes are cross-subject general 學習表現 and apply to all 社會 subjects.
_SUBJECT_TO_PREFIXES: dict[str, set[str]] = {
    "歷史": {"歷", "社", ""},
    "地理": {"地", "社", ""},
    "公民與社會": {"公", "社", ""},
    "跨科": {"歷", "地", "公", "社", ""},
}


def load_learning_content(path: Path | None = None) -> dict:
    if path is None:
        env = os.environ.get("SOCIAL_STUDIES_LEARNING_CONTENT_PATH")
        path = Path(env) if env else _DEFAULT_LC_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_learning_performance(path: Path | None = None) -> dict:
    if path is None:
        env = os.environ.get("SOCIAL_STUDIES_LEARNING_PERFORMANCE_PATH")
        path = Path(env) if env else _DEFAULT_LP_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_performance_intro(path: Path | None = None) -> str:
    if path is None:
        env = os.environ.get("SOCIAL_STUDIES_LEARNING_PERFORMANCE_INTRO_PATH")
        path = Path(env) if env else _DEFAULT_INTRO_PATH
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _subject_prefixes(subject: str | None) -> set[str] | None:
    """Return the 科目 prefix chars for a subject value, or None meaning 'all'."""
    if subject is None:
        return None
    return _SUBJECT_TO_PREFIXES.get(subject, {subject})


def allowed_learning_content(
    data: dict,
    learning_stage: str,
    subject: str | None = None,
) -> list[dict]:
    """Return entries matching learning_stage; optionally filtered by 科目 prefix."""
    prefixes = _subject_prefixes(subject)
    return [
        e for e in data["學習內容"]
        if e["學習階段"] == learning_stage
        and (prefixes is None or e["科目"] in prefixes)
    ]


def allowed_learning_performance(
    data: dict,
    learning_stage: str,
    subject: str | None = None,
) -> list[dict]:
    """Return entries matching learning_stage; optionally filtered by 科目 prefix."""
    prefixes = _subject_prefixes(subject)
    return [
        e for e in data["學習表現"]
        if e["學習階段"] == learning_stage
        and (prefixes is None or e["科目"] in prefixes)
    ]


def content_instructions(data: dict) -> dict[str, str]:
    """Return {value: 條目說明} for every 學習內容 entry."""
    return {e["value"]: e["條目說明"] for e in data["學習內容"]}


def performance_instructions(data: dict) -> dict[str, str]:
    """Return {value: 說明} for every 學習表現 entry."""
    return {e["value"]: e["說明"] for e in data["學習表現"]}
