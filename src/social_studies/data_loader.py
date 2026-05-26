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
        rows = list(csv.DictReader(f, restval=""))
    return [r for r in rows if any((v or "").strip() for v in r.values())]


def _parse_lc_field(raw: str) -> list[dict]:
    """Parse 學習內容/學習表現 field: ';'-separated '編碼:說明' pairs."""
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


def _parse_rubric_field(raw: str) -> list[dict]:
    """Parse 評分規準 field (JSON array or empty)."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return []


def _parse_few_shot_csv(rows: list[dict[str, str]], style: str) -> list[dict]:
    """Convert CSV rows filtered by style into {style, description, question} dicts.

    Supports both legacy columns and new 108課綱 per-subquestion columns:
    核心問題, 文本, 取材來源 (first row), and
    小題序號, 小題年級, 小題科目, 核心素養, 學習內容, 學習表現, 出題概念,
    小題題型, 答案, 答案解析, 評分規準 (per subquestion row).
    """
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

        # 108課綱 extensions
        core_q = first.get("核心問題", "").strip()
        if core_q:
            question["核心問題"] = core_q
        passage = first.get("文本", "").strip()
        if passage:
            question["文本"] = passage
        sources_raw = first.get("取材來源", "").strip()
        if sources_raw:
            question["取材來源"] = [s.strip() for s in sources_raw.split(";") if s.strip()]

        subquestions = []
        for i, row in enumerate(group, start=1):
            sq_text = row.get("題目", "").strip()
            if not sq_text:
                continue
            seq_raw = row.get("小題序號", "").strip()
            grade_raw = row.get("小題年級", "").strip()
            sq: dict = {
                "序號": int(seq_raw) if seq_raw else i,
                "年級": int(grade_raw) if grade_raw else 0,
                "科目": [s.strip() for s in row.get("小題科目", "").split(";") if s.strip()],
                "核心素養": [s.strip() for s in row.get("核心素養", "").split(";") if s.strip()],
                "學習內容": _parse_lc_field(row.get("學習內容", "")),
                "學習表現": _parse_lc_field(row.get("學習表現", "")),
                "出題概念": row.get("出題概念", "").strip(),
                "題型": row.get("小題題型", row.get("題型", "")).strip() or first.get("題型", "").strip(),
                "題目": sq_text,
                "答案": row.get("答案", "").strip(),
                "答案解析": row.get("答案解析", "").strip(),
                "評分規準": _parse_rubric_field(row.get("評分規準", "")),
            }
            subquestions.append(sq)
        if subquestions:
            question["subquestions"] = subquestions

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
