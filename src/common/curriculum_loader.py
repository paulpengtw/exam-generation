"""Subject-agnostic loader for 108課綱 學習內容 / 學習表現 curriculum JSON files."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

ExtraAdmissionTags = Callable[[str], dict[str, list[str]]]


def load_learning_content(
    data_dir: Path,
    *,
    subject_to_prefixes: dict[str, set[str]] | None = None,
    extra_admitted_by: ExtraAdmissionTags | None = None,
) -> dict:
    with open(data_dir / "learning_content.json", encoding="utf-8") as f:
        data = json.load(f)
    return (
        tag_entries_with_admitted_subjects(
            data,
            "學習內容",
            subject_to_prefixes=subject_to_prefixes,
            extra_admitted_by=extra_admitted_by,
        )
        if subject_to_prefixes is not None
        else data
    )


def load_learning_performance(
    data_dir: Path,
    *,
    subject_to_prefixes: dict[str, set[str]] | None = None,
    extra_admitted_by: ExtraAdmissionTags | None = None,
) -> dict:
    with open(data_dir / "learning_performance.json", encoding="utf-8") as f:
        data = json.load(f)
    return (
        tag_entries_with_admitted_subjects(
            data,
            "學習表現",
            subject_to_prefixes=subject_to_prefixes,
            extra_admitted_by=extra_admitted_by,
        )
        if subject_to_prefixes is not None
        else data
    )


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


def entries_with_admitted_subjects(
    data: dict,
    key: Literal["學習內容", "學習表現"],
    learning_stage: str,
    *,
    subject_to_prefixes: dict[str, set[str]],
    extra_admitted_by: ExtraAdmissionTags | None = None,
) -> list[dict]:
    """Return a stage pool whose rows declare every admitting subject.

    The admission tag is derived by asking the same ``allowed_*`` pool helper
    used by the samplers for each subject.  Keeping that calculation here
    means schema payloads and generation cannot acquire separate prefix rules.
    """
    allowed = (
        allowed_learning_content
        if key == "學習內容"
        else allowed_learning_performance
    )
    all_entries = allowed(
        data,
        learning_stage,
        subject_to_prefixes=subject_to_prefixes,
    )
    admitted_values = {
        subject: {
            entry["value"]
            for entry in allowed(
                data,
                learning_stage,
                subject=subject,
                subject_to_prefixes=subject_to_prefixes,
            )
        }
        for subject in subject_to_prefixes
    }
    return [
        {
            **entry,
            "admitted_by": _admitted_by(
                entry["value"],
                [
                    subject
                    for subject, values in admitted_values.items()
                    if entry["value"] in values
                ],
                extra_admitted_by,
            ),
        }
        for entry in all_entries
    ]


def _admitted_by(
    code: str,
    subjects: list[str],
    extra_admitted_by: ExtraAdmissionTags | None,
) -> dict[str, list[str]]:
    admitted_by = {"科目": subjects}
    if extra_admitted_by is not None:
        for parent, values in extra_admitted_by(code).items():
            if values:
                admitted_by[parent] = list(values)
    return admitted_by


def tag_entries_with_admitted_subjects(
    data: dict,
    key: Literal["學習內容", "學習表現"],
    *,
    subject_to_prefixes: dict[str, set[str]],
    extra_admitted_by: ExtraAdmissionTags | None = None,
) -> dict:
    """Attach source-of-truth 科目 admission tags to every curriculum row."""
    by_stage = {
        stage: {
            entry["value"]: entry
            for entry in entries_with_admitted_subjects(
                data,
                key,
                stage,
                subject_to_prefixes=subject_to_prefixes,
                extra_admitted_by=extra_admitted_by,
            )
        }
        for stage in dict.fromkeys(
            entry.get("學習階段")
            for entry in data.get(key, [])
            if isinstance(entry, dict) and isinstance(entry.get("學習階段"), str)
        )
    }
    tagged_data = dict(data)
    tagged_data[key] = [
        by_stage.get(entry.get("學習階段"), {}).get(
            entry.get("value"),
            {**entry, "admitted_by": {"科目": []}},
        )
        for entry in data.get(key, [])
    ]
    return tagged_data


def content_instructions(data: dict) -> dict[str, str]:
    """Return {value: 條目說明} for every 學習內容 entry."""
    return {e["value"]: e["條目說明"] for e in data["學習內容"]}


def performance_instructions(data: dict) -> dict[str, str]:
    """Return {value: 說明} for every 學習表現 entry."""
    return {e["value"]: e["說明"] for e in data["學習表現"]}
