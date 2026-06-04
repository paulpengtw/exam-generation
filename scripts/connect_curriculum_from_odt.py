"""
One-shot script: populate 對應學習表現 / 對應學習內容 in both JSON files
from the official 108課綱 社會領域學習重點與核心素養呼應表 (ODT).

Usage:
    uv run python scripts/connect_curriculum_from_odt.py <path-to-odt>
"""

import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

CODE_RE = re.compile(r"^[一-鿿]?[A-Za-z0-9]+-[ⅡⅢⅣⅤ]-\d+$")
REPO_ROOT = Path(__file__).parent.parent
LC_PATH = REPO_ROOT / "data/social_studies/curriculum/learning_content.json"
LP_PATH = REPO_ROOT / "data/social_studies/curriculum/learning_performance.json"


def _cell_codes_and_descs(cell):
    """Return parallel (codes, descs) lists from a table cell.

    Blank paragraphs are visual padding; non-blank paragraphs in c0/c2 are codes,
    and c1/c3 descriptions align sequentially with those non-blank entries.
    """
    paras = ["".join(p.itertext()).strip() for p in cell.findall(".//text:p", NS)]
    codes = [re.sub(r"\s+", "", p) for p in paras if re.sub(r"\s+", "", p)]
    # keep only paragraphs that look like codes
    matched_codes = [c for c in codes if CODE_RE.match(c)]
    return matched_codes


def _cell_descs(cell):
    paras = [" ".join("".join(p.itertext()).split())
             for p in cell.findall(".//text:p", NS)]
    return [p for p in paras if p]


def parse_odt(odt_path: str):
    """Return (content_to_perf, perf_to_content, perf_info) for stage Ⅳ."""
    with zipfile.ZipFile(odt_path) as z:
        xml_bytes = z.read("content.xml")
    root = ET.fromstring(xml_bytes)
    rows = root.findall(".//table:table-row", NS)

    content_to_perf: dict[str, set[str]] = defaultdict(set)
    perf_to_content: dict[str, set[str]] = defaultdict(set)
    perf_info: dict[str, str] = {}  # code -> description

    for row in rows[2:]:  # skip 2 header rows
        cells = row.findall("table:table-cell", NS)
        if len(cells) < 5:
            continue

        perf_codes = _cell_codes_and_descs(cells[0])
        perf_descs = _cell_descs(cells[1])
        cont_codes = _cell_codes_and_descs(cells[2])
        cont_descs = _cell_descs(cells[3])

        # Store descriptions for new perf entries
        for code, desc in zip(perf_codes, perf_descs):
            if "-Ⅳ-" in code:
                perf_info.setdefault(code, desc)

        perf_iv = [c for c in perf_codes if "-Ⅳ-" in c]
        cont_iv = [c for c in cont_codes if "-Ⅳ-" in c]

        for p in perf_iv:
            for c in cont_iv:
                content_to_perf[c].add(p)
                perf_to_content[p].add(c)

    return content_to_perf, perf_to_content, perf_info


# Mapping infix (e.g. "1a", "2c", "3d") → (構面, 項目)
INFIX_MAP = {
    "1a": ("理解及思辨", "覺察說明"),
    "1b": ("理解及思辨", "分析詮釋"),
    "1c": ("理解及思辨", "判斷創新"),
    "2a": ("態度及價值", "敏覺關懷"),
    "2b": ("態度及價值", "同理尊重"),
    "2c": ("態度及價值", "自省珍視"),
    "3a": ("實作及參與", "問題發現與思考"),
    "3b": ("實作及參與", "資料蒐整與應用"),
    "3c": ("實作及參與", "溝通與合作"),
    "3d": ("實作及參與", "規劃執行"),
}

SUBJECT_MAP = {
    "歷": "歷",
    "地": "地",
    "公": "公",
    "社": "社",
}

INFIX_RE = re.compile(r"^([一-鿿]?)(\d[a-z])-Ⅳ-\d+$")


def classify_perf_code(code: str) -> tuple[str, str, str]:
    """Return (科目, 構面, 項目) for a new perf code."""
    # strip subject prefix (Chinese chars or none)
    m = re.match(r"^([一-鿿]*)(\d[a-z])-Ⅳ-\d+$", code)
    if not m:
        return ("", "", "")
    prefix = m.group(1)
    infix = m.group(2)
    subject = SUBJECT_MAP.get(prefix, "")
    if not subject and not prefix:
        subject = "社"  # bare code like 1a-Ⅳ-1 → likely general 社
    kw = INFIX_MAP.get(infix, ("", ""))
    return subject, kw[0], kw[1]


def main(odt_path: str):
    content_to_perf, perf_to_content, perf_info = parse_odt(odt_path)

    print(f"ODT parsed: {len(content_to_perf)} content codes with Ⅳ-perf links")
    print(f"           {len(perf_to_content)} perf codes with Ⅳ-content links")

    # --- Update learning_content.json ---
    lc_data = json.loads(LC_PATH.read_text(encoding="utf-8"))
    for item in lc_data["學習內容"]:
        code = item["value"]
        new_perf = sorted(content_to_perf.get(code, set()))
        item["對應學習表現"] = new_perf

    LC_PATH.write_text(
        json.dumps(lc_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Written {LC_PATH.name}")

    # --- Update learning_performance.json ---
    lp_data = json.loads(LP_PATH.read_text(encoding="utf-8"))
    existing_lp_codes = {e["value"] for e in lp_data["學習表現"]}

    # Add missing perf entries
    added = []
    warnings = []
    for code, desc in sorted(perf_info.items()):
        if code in existing_lp_codes:
            continue
        subject, 構面, 項目 = classify_perf_code(code)
        if not 構面:
            warnings.append(f"  WARN: cannot classify {code} → 構面/項目 left empty")
        entry = {
            "value": code,
            "學習階段": "第四學習階段",
            "科目": subject,
            "構面": 構面,
            "項目": 項目,
            "說明": desc,
        }
        lp_data["學習表現"].append(entry)
        added.append(code)

    # Sort by code for stable ordering
    lp_data["學習表現"].sort(key=lambda x: x["value"])

    # Add 對應學習內容 to every entry
    for item in lp_data["學習表現"]:
        code = item["value"]
        item["對應學習內容"] = sorted(perf_to_content.get(code, set()))

    LP_PATH.write_text(
        json.dumps(lp_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Written {LP_PATH.name}")
    print(f"  Added {len(added)} new perf entries: {added}")
    for w in warnings:
        print(w)

    # Summary
    mapped = sum(1 for it in lc_data["學習內容"] if it["對應學習表現"])
    print(f"\nSummary: {mapped}/{len(lc_data['學習內容'])} 學習內容 entries have ≥1 學習表現 mapping")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/connect_curriculum_from_odt.py <path.odt>")
        sys.exit(1)
    main(sys.argv[1])
