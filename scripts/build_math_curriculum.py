"""Build data/math/curriculum/* from existing math sources + social_studies CC.

Run from repo root:

    python scripts/build_math_curriculum.py

Idempotent: re-running produces a no-op diff.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "data" / "curriculum"
SOCIAL_CC_PATH = ROOT / "data" / "social_studies" / "curriculum" / "core_competencies.json"
OUT_DIR = ROOT / "data" / "math" / "curriculum"

# Single-letter code prefix preserved in each row's 科目 field (matches the
# social_studies pattern of storing a short prefix character). The shared loader
# does prefix-set membership checks, so callers supply a subject→prefix-set map
# such as {"數與量": {"N", "n", ""}, ...}.
# Source confirmed to use only N, S, R, D, G, A, F (uppercase in 學習內容,
# lowercase in 學習表現). P is reserved for forward-compat (probability) per
# issue spec; no rows produced for it from current sources.
_VALID_PREFIXES = {"N", "n", "R", "r", "A", "a", "F", "f", "S", "s", "G", "g", "D", "d", "P", "p"}


def grade_to_stage(grade: int) -> str:
    if grade <= 2:
        return "第一學習階段"
    if grade <= 4:
        return "第二學習階段"
    if grade <= 6:
        return "第三學習階段"
    if grade <= 9:
        return "第四學習階段"
    return "第五學習階段"


def extract_grade(label: str) -> int:
    m = re.match(r"^(\d+)年級", label)
    if not m:
        raise ValueError(f"Unrecognized grade label: {label!r}")
    return int(m.group(1))


def subject_for(code: str) -> str:
    """Return the single-letter strand prefix used in 編碼 (e.g. 'N', 'n')."""
    m = re.match(r"^([A-Za-z])", code)
    if not m:
        return ""
    letter = m.group(1)
    return letter if letter in _VALID_PREFIXES else ""


def build_learning_content() -> dict:
    src = json.loads((SRC_DIR / "學習內容.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    for grade_row in src:
        stage = grade_to_stage(extract_grade(grade_row["年級"]))
        for item in grade_row["學習內容"]:
            code = item["編碼"]
            rows.append({
                "value": code,
                "學習階段": stage,
                "科目": subject_for(code),
                "條目說明": item.get("學習內容條目及說明", ""),
                "備註": item.get("備註") or "",
                "對應學習表現": item.get("對應學習表現", []) or [],
            })
    rows.sort(key=lambda r: r["value"])
    return {"學習內容": rows}


def build_learning_performance() -> dict:
    src = json.loads((SRC_DIR / "學習表現.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    for stage, items in src.items():
        for code, desc in items.items():
            rows.append({
                "value": code,
                "學習階段": stage,
                "科目": subject_for(code),
                "說明": desc,
            })
    rows.sort(key=lambda r: r["value"])
    return {"學習表現": rows}


def build_core_competencies() -> dict:
    src = json.loads(SOCIAL_CC_PATH.read_text(encoding="utf-8"))
    new_entries = []
    for entry in src["核心素養"]:
        rewritten = dict(entry)
        rewritten["value"] = entry["value"].replace("社-", "數-", 1)
        new_entries.append(rewritten)
    return {
        "學習階段_to_stage": src["學習階段_to_stage"],
        "面向": src["面向"],
        "項目": src["項目"],
        "核心素養": new_entries,
    }


INTRO_MD = """\
# 108課綱 數學領域 學習表現簡介

學習表現以「認知歷程／能力／態度」為主，描述學生在各學習階段應能展現的數學素養。
代碼以小寫字母標示主題（n/s/r/d/g/a/f），中間以羅馬數字標示學習階段，末位為流水號。
例如 `n-IV-1` 表示「數與量」主題、第四學習階段、第 1 條學習表現。
"""


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    write_json(OUT_DIR / "learning_content.json", build_learning_content())
    write_json(OUT_DIR / "learning_performance.json", build_learning_performance())
    write_json(OUT_DIR / "core_competencies.json", build_core_competencies())
    intro_path = OUT_DIR / "learning_performance_intro.md"
    if not intro_path.exists():
        intro_path.write_text(INTRO_MD, encoding="utf-8")
    print(f"Wrote {OUT_DIR}/")


if __name__ == "__main__":
    main()
