"""Data loading for social-studies Channel-1 few-shot examples.

Examples live in ``data/social_studies/few_shot/<題目內容類型>/``. Each JSON
file is one equal-odds sampling group; rows in the root CSV are grouped by
``範例編號`` after filtering on ``題目內容類型``. The loader intentionally
understands only this ICCS-tagged shape.
"""

from __future__ import annotations

import csv
import json
import re
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


def _clean_caption(raw: str) -> str:
    """Strip Windows/Unix file paths from captions, keeping the human-readable part."""
    # Remove leading path (e.g. "C:\Users\...\foo.jpg" or "D:\繪圖\...\bar.png")
    cleaned = re.sub(
        r"^[A-Za-z]:\\[^\n]*?(?:\\|\.(?:jpg|jpeg|png|gif))\s*",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.strip()
    return cleaned or raw.strip()


def _load_example_images(images_dir: Path, example_id: str) -> list[dict]:
    """Return [{path: Path, caption: str}] for all figures in images_dir/<example_id>/."""
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


def _parse_few_shot_csv(
    rows: list[dict[str, str]],
    content_type: str | None = None,
    images_dir: Path | None = None,
) -> list[dict]:
    """Convert content-type-filtered CSV rows into Channel-1 examples.

    The root CSV carries 核心問題, 文本, 取材來源 (first row), and
    小題序號, 小題年級, 小題科目, 核心素養, 學習內容, 學習表現, 出題概念,
    認知歷程, 小題題型, 答案, 答案解析, 評分規準 (per subquestion row).
    """
    if not content_type:
        return []

    # Group rows by 範例編號 before filtering: later rows may leave first-row
    # metadata blank, as documented by csv_填寫指南.md.
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    order: list[str] = []
    for row in rows:
        key = row.get("範例編號", "").strip()
        if key not in groups:
            order.append(key)
        groups[key].append(row)

    examples = []
    for key in order:
        group = groups[key]
        first = group[0]
        group_content_type = next(
            (
                row.get("題目內容類型", "").strip()
                for row in group
                if row.get("題目內容類型", "").strip()
            ),
            "",
        )
        if group_content_type != content_type:
            continue
        情境_raw = first.get("情境", "").strip()
        認知歷程_values: list[str] = []
        for row in group:
            process = row.get("認知歷程", "").strip()
            if process and process not in 認知歷程_values:
                認知歷程_values.append(process)

        question: dict = {
            "情境": [c.strip() for c in 情境_raw.split(";") if c.strip()],
            "題型種類": first.get("題型種類", "").strip(),
            "題型": first.get("題型", "").strip(),
            "題目內容類型": group_content_type,
            "內容領域": first.get("內容領域", "").strip(),
            "認知歷程": 認知歷程_values,
            "題目": [r["題目"].strip() for r in group if r.get("題目", "").strip()],
            "正確解題分析": [
                r["正確解題分析"].strip()
                for r in group
                if r.get("正確解題分析", "").strip()
            ],
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
            sq_type = row.get("小題題型", "").strip()
            if not seq_raw and not sq_type:
                continue
            sq: dict = {
                "序號": int(seq_raw) if seq_raw else i,
                "年級": int(grade_raw) if grade_raw else 0,
                "科目": [s.strip() for s in row.get("小題科目", "").split(";") if s.strip()],
                "核心素養": [s.strip() for s in row.get("核心素養", "").split(";") if s.strip()],
                "學習內容": _parse_lc_field(row.get("學習內容", "")),
                "學習表現": _parse_lc_field(row.get("學習表現", "")),
                "出題概念": row.get("出題概念", "").strip(),
                "認知歷程": row.get("認知歷程", "").strip(),
                "題型": sq_type or first.get("題型", "").strip(),
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

        example: dict = {
            "題目內容類型": group_content_type,
            "description": first.get("description", "").strip(),
            "question": question,
        }
        if images_dir is not None:
            imgs = _load_example_images(images_dir, key)
            if imgs:
                example["images"] = imgs
        examples.append(example)
    return examples


def _safe_content_type_dir(few_shot_dir: Path, content_type: str | None) -> Path | None:
    """Resolve a Channel-1 key without allowing traversal or Channel-2 access."""
    if not content_type:
        return None
    relative = Path(content_type)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(
            part in {".", "..", "images", "process_exemplars"}
            for part in relative.parts
        )
    ):
        return None
    try:
        root = few_shot_dir.resolve()
        candidate = (root / relative).resolve()
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def load_few_shot_example_groups(
    few_shot_dir: Path,
    content_type: str | None = None,
) -> list[list[dict]]:
    """Load few-shot examples as equal-odds sampling groups.

    Each JSON file under the requested content-type directory is one group.
    Each CSV 範例編號 matching the requested content type is one group.
    Empty and unpopulated keys are valid and return no examples.
    """
    content_type_dir = _safe_content_type_dir(few_shot_dir, content_type)
    if content_type_dir is None:
        return []

    groups: list[list[dict]] = []
    for f in sorted(content_type_dir.glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            loaded = json.load(fh)
        loaded_examples = loaded if isinstance(loaded, list) else [loaded]
        group = [
            ex for ex in loaded_examples if isinstance(ex, dict)
        ]
        if group:
            groups.append(group)

    images_dir = few_shot_dir / "images"
    csv_rows = _read_csv(few_shot_dir / "few_shot_examples.csv")
    image_root = images_dir if images_dir.exists() else None
    csv_examples = _parse_few_shot_csv(csv_rows, content_type, images_dir=image_root)
    groups.extend([ex] for ex in csv_examples)
    return groups


def load_few_shot_examples(
    few_shot_dir: Path,
    content_type: str | None = None,
) -> list[dict]:
    """Load the selected content type as a flat list."""
    return [
        ex
        for group in load_few_shot_example_groups(few_shot_dir, content_type)
        for ex in group
    ]
