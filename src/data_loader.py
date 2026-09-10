"""Load and index curriculum data from JSON files.

Few-shot examples for math live under ``data/few_shot/{style}/`` and are
loaded by :func:`load_few_shot_examples`. To add a new sample, see the
onboarding guide at ``docs/ADDING_SAMPLES.md`` (zh-TW), which documents
the directory layout, required fields per 題型, validation rules
(e.g. malformed ``chart_spec`` is silently dropped), and the one-liner
verification command for all three subject pipelines.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
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


def get_target_grade_content(
    curriculum: list[dict], grades: list[int] | None = None
) -> list[LearningContentItem]:
    """Get all learning content for the configured target grades."""
    if grades is None:
        from src.schema_loader import load_grades, load_schemas
        grades = load_grades(load_schemas())
    items = []
    for grade in grades:
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
    """Load few-shot examples matching a given question style.

    Phase 3: also consults `few_shot_examples.csv` (CSV-driven) if present.
    """
    examples: list[dict] = []
    style_dir = few_shot_dir / style
    if style_dir.exists():
        for f in sorted(style_dir.glob("*.json")):
            with open(f, encoding="utf-8") as fh:
                examples.append(json.load(fh))

    csv_path = few_shot_dir / "few_shot_examples.csv"
    images_dir = few_shot_dir / "images"
    if csv_path.exists():
        csv_examples, _imgs = load_few_shot_examples_csv(
            csv_path,
            images_dir=images_dir if images_dir.exists() else None,
            style=style,
        )
        examples.extend(csv_examples)
    return examples


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, restval=""))
    return [r for r in rows if any((v or "").strip() for v in r.values())]


def _parse_lc_field(raw: str) -> list[dict]:
    refs = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            code, _, desc = part.partition(":")
            refs.append({"編碼": code.strip(), "說明": desc.strip()})
        else:
            refs.append({"編碼": part, "說明": ""})
    return refs


def _clean_caption(raw: str) -> str:
    cleaned = re.sub(
        r"^[A-Za-z]:\\[^\n]*?(?:\\|\.(?:jpg|jpeg|png|gif))\s*",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.strip()
    return cleaned or raw.strip()


def _load_example_images(images_dir: Path, example_id: str) -> list[dict]:
    """Return [{path, caption}] for images referenced in images/<id>/manifest.json."""
    manifest_path = images_dir / example_id / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    result = []
    example_dir = images_dir / example_id
    for entry in entries:
        fname = entry.get("file", "")
        path = example_dir / fname
        if path.exists():
            result.append({"path": path, "caption": _clean_caption(entry.get("caption", ""))})
    return result


def load_few_shot_examples_csv(
    csv_path: Path | None = None,
    images_dir: Path | None = None,
    style: str | None = None,
) -> tuple[list[dict], list[Path]]:
    """Load math few-shot examples from a CSV file.

    Math interprets each CSV row as one flat question (no rubric, no subquestions).
    Returns ([example_dicts], [image_paths_from_all_examples]).
    """
    if csv_path is None or not csv_path.exists():
        return [], []
    rows = _read_csv_rows(csv_path)
    filtered = [
        r for r in rows
        if style is None or r.get("style", "").strip() == style
    ]
    if not filtered:
        return [], []

    # Group by 範例編號 so multi-line questions stay together.
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    order: list[str] = []
    for row in filtered:
        key = row.get("範例編號", "").strip()
        if key not in groups:
            order.append(key)
        groups[key].append(row)

    examples: list[dict] = []
    all_images: list[Path] = []
    for key in order:
        group = groups[key]
        first = group[0]
        情境_raw = first.get("情境", "").strip()
        question: dict = {
            "情境": [c.strip() for c in 情境_raw.split(";") if c.strip()],
            "題型種類": first.get("題型種類", "").strip(),
            "題型": first.get("題型", "").strip(),
            "學習內容": _parse_lc_field(first.get("學習內容", "")),
            "學習表現": _parse_lc_field(first.get("學習表現", "")),
            "核心素養": [
                c.strip() for c in first.get("核心素養", "").split(";") if c.strip()
            ],
            "出題概念": first.get("出題概念", "").strip(),
            "題目": [r["題目"].strip() for r in group if r.get("題目", "").strip()],
            "正確解題分析": [
                r["正確解題分析"].strip() for r in group if r.get("正確解題分析", "").strip()
            ],
        }
        chart_raw = first.get("chart_spec", "").strip()
        if chart_raw:
            try:
                question["chart_spec"] = json.loads(chart_raw)
            except json.JSONDecodeError:
                pass

        example: dict = {
            "style": first.get("style", "").strip(),
            "description": first.get("description", "").strip(),
            "question": question,
        }
        if images_dir is not None:
            imgs = _load_example_images(images_dir, key)
            if imgs:
                example["images"] = imgs
                all_images.extend(img["path"] for img in imgs)
        examples.append(example)

    return examples, all_images
