"""Build natural-sciences curriculum JSON files from local source exports.

Run from repo root:

    python3 scripts/build_natural_sciences_curriculum.py

Idempotent: re-running should produce a no-op diff when sources are unchanged.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRICULUM_DIR = ROOT / "data" / "natural_sciences" / "curriculum"
CONTENT_SRC_DIR = CURRICULUM_DIR / "curriculum_content_108"

STAGE_TO_GRADES = {
    "第二學習階段": [3, 4],
    "第三學習階段": [5, 6],
    "第四學習階段": [7, 8, 9],
    "第五學習階段": [10, 11, 12],
}

STAGE_ORDER = {stage: i for i, stage in enumerate(STAGE_TO_GRADES)}

PERFORMANCE_SOURCES = [
    (
        CURRICULUM_DIR / "國小教育階段學習表現.xlsx - 學習表現.csv",
        [
            ("第二學習階段", "第二學習階段學習表現", "第二學習階段學習表現代碼"),
            ("第三學習階段", "第三學習階段學習表現", "第三學習階段學習表現代碼"),
        ],
    ),
    (
        CURRICULUM_DIR / "國中教育階段學習表現.xlsx - 工作表1.csv",
        [
            ("第四學習階段", "第四學習階段學習表現", "第四學習階段學習表現代碼"),
        ],
    ),
    (
        CURRICULUM_DIR / "普通型高中教育階段學習表現.xlsx - 工作表1.csv",
        [
            ("第五學習階段", "第五學習階段學習表現(必修)", "第五學習階段學習表現代碼(必修)"),
            ("第五學習階段", "第五學習階段學習表現（加深加廣選修）", "第五學習階段學習表現代碼（加深加廣選修）"),
        ],
    ),
]


def clean_text(value: str | None) -> str:
    """Trim and collapse CSV/markdown formatting whitespace."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def parse_metadata(text: str, path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^- ([^：]+)：(.*)$", line)
        if not match:
            continue
        key = clean_text(match.group(1))
        value = clean_text(match.group(2))
        if key:
            metadata[key] = value

    required = ["代碼", "學習階段", "領域", "主題", "次主題"]
    missing = [key for key in required if not metadata.get(key)]
    if missing:
        raise ValueError(f"{path} is missing metadata fields: {', '.join(missing)}")
    return metadata


def parse_original_text(text: str, path: Path) -> str:
    match = re.search(r"^## 原文\s*\n(?P<body>.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(f"{path} is missing ## 原文 block")
    body = clean_text(match.group("body"))
    if not body:
        raise ValueError(f"{path} has an empty ## 原文 block")
    return body


def stage_sort_key(stage: str) -> int:
    try:
        return STAGE_ORDER[stage]
    except KeyError as exc:
        raise ValueError(f"Unknown learning stage: {stage}") from exc


def code_sort_key(code: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Za-z]+)-[^-]+-(\d+)$", code)
    if not match:
        return (code, -1, code)
    prefix, number = match.groups()
    return (prefix.lower(), int(number), code)


def build_learning_content() -> dict:
    rows: list[dict] = []
    for path in sorted(CONTENT_SRC_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        metadata = parse_metadata(text, path)
        note_parts = [
            f"領域：{metadata['領域']}",
            f"主題：{metadata['主題']}",
            f"次主題：{metadata['次主題']}",
        ]
        if metadata.get("備註"):
            note_parts.append(f"來源備註：{metadata['備註']}")
        rows.append(
            {
                "value": metadata["代碼"],
                "學習階段": metadata["學習階段"],
                "科目": "",
                "條目說明": parse_original_text(text, path),
                "備註": "；".join(note_parts),
                "對應學習表現": [],
            }
        )

    rows.sort(key=lambda row: (stage_sort_key(row["學習階段"]), code_sort_key(row["value"])))
    assert_unique_values(rows, "學習內容")
    return {"學習階段_to_grades": STAGE_TO_GRADES, "學習內容": rows}


def normalized_row(row: dict[str, str]) -> dict[str, str]:
    return {key.strip(): value for key, value in row.items()}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [normalized_row(row) for row in csv.DictReader(handle)]


def build_learning_performance() -> dict:
    rows: list[dict] = []
    for path, pairs in PERFORMANCE_SOURCES:
        for source_row in read_csv_rows(path):
            dimension = clean_text(source_row.get("項目"))
            item = clean_text(source_row.get("子項"))
            if not dimension or not item:
                raise ValueError(f"{path} has a row without 項目/子項: {source_row}")
            for stage, description_column, code_column in pairs:
                description = clean_text(source_row.get(description_column))
                code = (source_row.get(code_column) or "").strip()
                if not description and not code:
                    continue
                if not description or not code:
                    raise ValueError(f"{path} has an incomplete {stage} entry: {source_row}")
                rows.append(
                    {
                        "value": code,
                        "學習階段": stage,
                        "科目": "",
                        "構面": dimension,
                        "項目": item,
                        "說明": description,
                        "對應學習內容": [],
                    }
                )

    rows.sort(key=lambda row: (stage_sort_key(row["學習階段"]), code_sort_key(row["value"])))
    assert_unique_values(rows, "學習表現")
    return {"學習階段_to_grades": STAGE_TO_GRADES, "學習表現": rows}


def assert_unique_values(rows: list[dict], label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        value = row["value"]
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"Duplicate {label} values: {', '.join(sorted(duplicates))}")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    write_json(CURRICULUM_DIR / "learning_content.json", build_learning_content())
    write_json(CURRICULUM_DIR / "learning_performance.json", build_learning_performance())
    print(f"Wrote {CURRICULUM_DIR}/learning_content.json")
    print(f"Wrote {CURRICULUM_DIR}/learning_performance.json")


if __name__ == "__main__":
    main()
