"""Data loading for natural-sciences few-shot examples."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

_TYPE_TO_FOLDER = {
    "Simple multiple-choice": "Simple-multiple-choice",
    "Complex multiple-choice": "Complex-multiple-choice",
    "Constructed response": "Constructed-response",
}


def folder_for_question_type(question_type: str | None) -> str | None:
    if not question_type:
        return None
    return _TYPE_TO_FOLDER.get(question_type, question_type.replace(" ", "-"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, restval=""))
    return [r for r in rows if any((v or "").strip() for v in r.values())]


def _parse_refs(raw: str) -> list[dict]:
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


def _parse_rubric(raw: str) -> list[dict]:
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _parse_csv_examples(rows: list[dict[str, str]]) -> list[dict]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    order: list[str] = []
    for row in rows:
        key = row.get("範例編號", "").strip() or f"example-{len(order) + 1}"
        if key not in groups:
            order.append(key)
        groups[key].append(row)

    examples = []
    for key in order:
        group = groups[key]
        first = group[0]
        question: dict = {
            "核心問題": first.get("核心問題", "").strip(),
            "文本": first.get("文本", "").strip(),
            "取材來源": [s.strip() for s in first.get("取材來源", "").split(";") if s.strip()],
            "情境": [s.strip() for s in first.get("情境", "").split(";") if s.strip()],
            "情境子類別": first.get("情境子類別", "").strip(),
            "題型種類": first.get("題型種類", "").strip(),
            "題型": first.get("題型", "").strip(),
            "科學能力": [s.strip() for s in first.get("科學能力", "").split(";") if s.strip()],
            "題目內容類型": first.get("題目內容類型", "").strip(),
            "題目": [r["題目"].strip() for r in group if r.get("題目", "").strip()],
            "正確解題分析": [
                r["正確解題分析"].strip()
                for r in group
                if r.get("正確解題分析", "").strip()
            ],
        }

        subquestions = []
        for i, row in enumerate(group, start=1):
            sq_text = row.get("題目", "").strip()
            if not sq_text:
                continue
            seq_raw = row.get("小題序號", "").strip()
            grade_raw = row.get("小題年級", "").strip()
            subquestions.append(
                {
                    "序號": int(seq_raw) if seq_raw else i,
                    "年級": int(grade_raw) if grade_raw else 0,
                    "科目": [s.strip() for s in row.get("小題科目", "").split(";") if s.strip()],
                    "科學能力": [
                        s.strip() for s in row.get("科學能力", "").split(";") if s.strip()
                    ],
                    "學習內容": _parse_refs(row.get("學習內容", "")),
                    "學習表現": _parse_refs(row.get("學習表現", "")),
                    "出題概念": row.get("出題概念", "").strip(),
                    "題型": row.get("小題題型", row.get("題型", "")).strip(),
                    "題目": sq_text,
                    "答案": row.get("答案", "").strip(),
                    "答案解析": row.get("答案解析", "").strip(),
                    "評分規準": _parse_rubric(row.get("評分規準", "")),
                }
            )
        if subquestions:
            question["subquestions"] = subquestions

        chart_raw = first.get("chart_spec", "").strip()
        if chart_raw:
            try:
                question["chart_spec"] = json.loads(chart_raw)
            except json.JSONDecodeError:
                pass

        examples.append(
            {
                "style": first.get("style", "").strip(),
                "description": first.get("description", "").strip(),
                "question": question,
            }
        )
    return examples


def _load_examples_from_dir(path: Path) -> list[dict]:
    examples: list[dict] = []
    if not path.exists():
        return examples

    for file_path in sorted(path.glob("*.json")):
        with open(file_path, encoding="utf-8") as f:
            loaded = json.load(f)
        loaded_examples = loaded if isinstance(loaded, list) else [loaded]
        examples.extend(ex for ex in loaded_examples if isinstance(ex, dict))

    examples.extend(_parse_csv_examples(_read_csv(path / "few_shot_examples.csv")))
    return examples


def load_few_shot_example_groups(
    few_shot_dir: Path,
    q_type: str | None = None,
) -> list[list[dict]]:
    """Load few-shot examples, grouped for equal-odds sampling.

    Natural-sciences examples live under one folder per PISA Science item family.
    Empty folders are valid for the initial scaffold and simply return no examples.
    """

    folder = folder_for_question_type(q_type)
    if folder:
        examples = _load_examples_from_dir(few_shot_dir / folder)
    else:
        examples = []
        for subdir in sorted(p for p in few_shot_dir.iterdir() if p.is_dir()):
            examples.extend(_load_examples_from_dir(subdir))
        examples.extend(_load_examples_from_dir(few_shot_dir))
    return [[example] for example in examples]
