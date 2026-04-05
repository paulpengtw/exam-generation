"""Load and index curriculum data from JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from src.schemas import LearningContentItem


def load_curriculum(path: Path) -> list[dict]:
    """Load the full curriculum JSON (all grades 1-12)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_performance_standards(path: Path) -> dict:
    """Load learning performance standards JSON."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_grade_content(curriculum: list[dict], grade: int) -> list[LearningContentItem]:
    """Extract learning content items for a specific grade."""
    grade_key = f"{grade}年級"
    for entry in curriculum:
        if entry.get("年級") == grade_key:
            return [
                LearningContentItem(
                    編碼=item["編碼"],
                    說明=item["學習內容條目及說明"],
                )
                for item in entry.get("學習內容", [])
            ]
    return []


def get_target_grade_content(curriculum: list[dict]) -> list[LearningContentItem]:
    """Get all learning content for grades 7-9 (第四學習階段)."""
    items = []
    for grade in (7, 8, 9):
        items.extend(get_grade_content(curriculum, grade))
    return items


def get_full_curriculum_text(curriculum: list[dict]) -> str:
    """Serialize the full curriculum to a string for LLM context injection."""
    return json.dumps(curriculum, ensure_ascii=False, indent=2)


def get_full_performance_text(standards: dict) -> str:
    """Serialize the full performance standards to a string for LLM context injection."""
    return json.dumps(standards, ensure_ascii=False, indent=2)


def load_intro_text(path: Path) -> str:
    """Load the curriculum introduction markdown file."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def load_few_shot_examples(few_shot_dir: Path, style: str) -> list[dict]:
    """Load few-shot examples matching a given question style."""
    style_dir = few_shot_dir / style
    if not style_dir.exists():
        return []
    examples = []
    for f in sorted(style_dir.glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            examples.append(json.load(fh))
    return examples
