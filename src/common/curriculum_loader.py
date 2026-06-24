"""Subject-agnostic loader for 108課綱 學習內容 / 學習表現 curriculum JSON files."""

from __future__ import annotations

import json
from pathlib import Path


def load_learning_content(data_dir: Path) -> dict:
    with open(data_dir / "learning_content.json", encoding="utf-8") as f:
        return json.load(f)


def load_learning_performance(data_dir: Path) -> dict:
    with open(data_dir / "learning_performance.json", encoding="utf-8") as f:
        return json.load(f)


def load_performance_intro(data_dir: Path) -> str:
    path = data_dir / "learning_performance_intro.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _subject_prefixes(
    subject: str | None,
    subject_to_prefixes: dict[str, set[str]],
) -> set[str] | None:
    """Return the 科目 prefix chars for a subject value, or None meaning 'all'."""
    if subject is None:
        return None
    return subject_to_prefixes.get(subject, {subject})


def allowed_learning_content(
    data: dict,
    learning_stage: str,
    *,
    subject: str | None = None,
    subject_to_prefixes: dict[str, set[str]],
) -> list[dict]:
    """Return entries matching learning_stage; optionally filtered by 科目 prefix."""
    prefixes = _subject_prefixes(subject, subject_to_prefixes)
    return [
        e for e in data["學習內容"]
        if e["學習階段"] == learning_stage
        and (prefixes is None or e["科目"] in prefixes)
    ]


def allowed_learning_performance(
    data: dict,
    learning_stage: str,
    *,
    subject: str | None = None,
    subject_to_prefixes: dict[str, set[str]],
) -> list[dict]:
    """Return entries matching learning_stage; optionally filtered by 科目 prefix."""
    prefixes = _subject_prefixes(subject, subject_to_prefixes)
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
