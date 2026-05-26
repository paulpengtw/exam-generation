"""Data loading for social studies — few-shot examples and CSV-driven curriculum."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if any(v.strip() for v in r.values())]


def _parse_few_shot_csv(rows: list[dict[str, str]], style: str) -> list[dict]:
    """Convert CSV rows filtered by style into {style, description, question} dicts."""
    style_rows = [r for r in rows if r.get("style", "").strip() == style]
    if not style_rows:
        return []

    # Group rows by 範例編號, preserving order.
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    order: list[str] = []
    for row in style_rows:
        key = row.get("範例編號", "").strip()
        if key not in groups:
            order.append(key)
        groups[key].append(row)

    examples = []
    for key in order:
        group = groups[key]
        first = group[0]
        情境_raw = first.get("情境", "").strip()
        閱讀歷程_raw = first.get("閱讀歷程", "").strip()
        question: dict = {
            "情境": [c.strip() for c in 情境_raw.split(";") if c.strip()],
            "題型種類": first.get("題型種類", "").strip(),
            "題型": first.get("題型", "").strip(),
            "閱讀歷程": [p.strip() for p in 閱讀歷程_raw.split(";") if p.strip()],
            "文本形式": first.get("文本形式", "").strip(),
            "題目": [r["題目"].strip() for r in group if r.get("題目", "").strip()],
            "正確解題分析": [r["正確解題分析"].strip() for r in group if r.get("正確解題分析", "").strip()],
        }
        chart_raw = first.get("chart_spec", "").strip()
        if chart_raw:
            try:
                question["chart_spec"] = json.loads(chart_raw)
            except json.JSONDecodeError:
                pass
        examples.append({
            "style": style,
            "description": first.get("description", "").strip(),
            "question": question,
        })
    return examples


def load_few_shot_examples(few_shot_dir: Path, style: str) -> list[dict]:
    """Load few-shot examples matching a given question style.

    Combines JSON files from {few_shot_dir}/{style}/*.json with any matching
    entries in {few_shot_dir}/few_shot_examples.csv.
    """
    style_dir = few_shot_dir / style
    examples: list[dict] = []
    if style_dir.exists():
        for f in sorted(style_dir.glob("*.json")):
            with open(f, encoding="utf-8") as fh:
                examples.append(json.load(fh))

    csv_rows = _read_csv(few_shot_dir / "few_shot_examples.csv")
    csv_examples = _parse_few_shot_csv(csv_rows, style)
    examples.extend(csv_examples)
    return examples


def load_learning_performance(curriculum_dir: Path) -> dict:
    """Parse learning_performance.csv → {學習階段: {編碼: 說明}}.

    Equivalent to math's 學習表現.json shape. Returns {} if file is empty.
    """
    rows = _read_csv(curriculum_dir / "learning_performance.csv")
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        stage = row.get("學習階段", "").strip()
        code = row.get("編碼", "").strip()
        desc = row.get("說明", "").strip()
        if stage and code:
            result[stage][code] = desc
    return dict(result)


def load_learning_content(curriculum_dir: Path) -> list[dict]:
    """Parse learning_content.csv → [{年級, 學習內容:[{編碼,學習內容條目及說明,備註,對應學習表現}]}].

    Equivalent to math's 學習內容.json shape. Returns [] if file is empty.
    多值欄位 對應學習表現 uses ';' as separator.
    """
    rows = _read_csv(curriculum_dir / "learning_content.csv")
    grade_map: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grade = row.get("年級", "").strip()
        code = row.get("編碼", "").strip()
        if not grade or not code:
            continue
        related_raw = row.get("對應學習表現", "").strip()
        related = [c.strip() for c in related_raw.split(";") if c.strip()]
        grade_map[grade].append({
            "編碼": code,
            "學習內容條目及說明": row.get("學習內容條目及說明", "").strip(),
            "備註": row.get("備註", "").strip(),
            "對應學習表現": [{"對應學習表現": c} for c in related],
        })
    return [{"年級": g, "學習內容": items} for g, items in grade_map.items()]
