"""Build natural-sciences curriculum JSON files from the canonical XLSX.

Run from repo root:

    python3 scripts/build_natural_sciences_curriculum.py

The workbook is read directly with the Python standard library so this script
does not require openpyxl or other spreadsheet dependencies.
"""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent
CURRICULUM_DIR = ROOT / "data" / "natural_sciences" / "curriculum"
WORKBOOK_PATH = CURRICULUM_DIR / "converted" / "課綱各項指標列表.xlsx"
CONTENT_PERFORMANCE_DOCX_PATH = (
    CURRICULUM_DIR / "to-be-convert" / "自然科_學習內容:學習表現對照表.docx"
)
SOCIAL_CC_PATH = ROOT / "data" / "social_studies" / "curriculum" / "core_competencies.json"

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

STAGE_TO_GRADES = {
    "第二學習階段": [3, 4],
    "第三學習階段": [5, 6],
    "第四學習階段": [7, 8, 9],
    "第五學習階段": [10, 11, 12],
}

CONTENT_SHEETS = [
    ("學習內容_國小II", "第二學習階段"),
    ("學習內容_國小III", "第三學習階段"),
    ("學習內容_國中", "第四學習階段"),
    ("學習內容_高中生物", "第五學習階段"),
    ("學習內容_高中物理", "第五學習階段"),
    ("學習內容_高中化學", "第五學習階段"),
    ("學習內容_高中地球科學", "第五學習階段"),
]

CROSS_CONCEPT_SHEET = "跨科概念"
CROSS_CONCEPT_COLUMNS = ["課題", "跨科概念", "主題", "次主題"]

PERFORMANCE_SHEETS = [
    ("學習表現_小II", "第二學習階段"),
    ("學習表現_小III", "第三學習階段"),
    ("學習表現_國", "第四學習階段"),
    ("學習表現_高", "第五學習階段"),
]

HIGH_SCHOOL_SUBJECTS = {
    "B": "生物",
    "P": "物理",
    "C": "化學",
    "E": "地球科學",
}

EXAMPLE_MARKER = "(我是範例)"
CORE_CODE_RE = re.compile(r"^(自S-[EJU]-[ABC][1-3])")
DASH_TRANSLATION = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
        "－": "-",
    }
)
ROMAN_STAGE_TOKENS = {
    "III": "Ⅲ",
    "IV": "Ⅳ",
    "II": "Ⅱ",
    "V": "Ⅴ",
}


def xml_tag(local_name: str) -> str:
    return f"{{{MAIN_NS}}}{local_name}"


def word_tag(local_name: str) -> str:
    return f"{{{WORD_NS}}}{local_name}"


def column_index(cell_ref: str) -> int:
    match = re.match(r"^([A-Za-z]+)", cell_ref)
    if not match:
        raise ValueError(f"Cell reference has no column: {cell_ref!r}")
    index = 0
    for char in match.group(1).upper():
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(text_node.text or "" for text_node in element.iter(xml_tag("t")))


def normalize_xl_target(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


class XlsxWorkbook:
    def __init__(self, path: Path):
        self.path = path
        self._zip = ZipFile(path)
        self._shared_strings = self._read_shared_strings()
        self._sheet_targets = self._read_sheet_targets()

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> "XlsxWorkbook":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _read_shared_strings(self) -> list[str]:
        if "xl/sharedStrings.xml" not in self._zip.namelist():
            return []
        root = ET.fromstring(self._zip.read("xl/sharedStrings.xml"))
        return [element_text(item) for item in root.findall(xml_tag("si"))]

    def _read_sheet_targets(self) -> dict[str, str]:
        workbook = ET.fromstring(self._zip.read("xl/workbook.xml"))
        relationships = ET.fromstring(self._zip.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
        }

        sheet_targets: dict[str, str] = {}
        for sheet in workbook.findall(f"{xml_tag('sheets')}/{xml_tag('sheet')}"):
            name = sheet.attrib["name"].strip()
            relationship_id = sheet.attrib[f"{{{OFFICE_REL_NS}}}id"]
            target = normalize_xl_target(rel_targets[relationship_id])
            if name in sheet_targets:
                raise ValueError(f"Duplicate sheet name after trimming whitespace: {name}")
            sheet_targets[name] = target
        return sheet_targets

    def rows(self, sheet_name: str) -> list[tuple[int, list[str]]]:
        name = sheet_name.strip()
        if name not in self._sheet_targets:
            available = ", ".join(sorted(self._sheet_targets))
            raise ValueError(f"Workbook has no sheet {sheet_name!r}; available: {available}")

        root = ET.fromstring(self._zip.read(self._sheet_targets[name]))
        rows: list[tuple[int, list[str]]] = []
        for row in root.findall(f"{xml_tag('sheetData')}/{xml_tag('row')}"):
            row_number = int(row.attrib.get("r", str(len(rows) + 1)))
            cells: dict[int, str] = {}
            max_index = -1
            for cell in row.findall(xml_tag("c")):
                index = column_index(cell.attrib.get("r", "A1"))
                cells[index] = self._cell_value(cell)
                max_index = max(max_index, index)
            values = [cells.get(index, "") for index in range(max_index + 1)] if max_index >= 0 else []
            while values and values[-1] == "":
                values.pop()
            rows.append((row_number, values))
        return rows

    def _cell_value(self, cell: ET.Element) -> str:
        cell_type = cell.attrib.get("t")
        value = cell.find(xml_tag("v"))

        if cell_type == "s":
            if value is None or value.text is None:
                return ""
            return self._shared_strings[int(value.text)]
        if cell_type == "inlineStr":
            return element_text(cell.find(xml_tag("is")))
        return value.text if value is not None and value.text is not None else ""


def cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return row[index].strip()


def text_cell(row: list[str], index: int) -> str:
    return re.sub(r"\s+", " ", cell(row, index)).strip()


def is_blank(row: list[str]) -> bool:
    return not any(value.strip() for value in row)


def is_example(row: list[str]) -> bool:
    return any(EXAMPLE_MARKER in value for value in row)


def note_text(parts: list[tuple[str, str]]) -> str:
    return "；".join(f"{key}：{value}" for key, value in parts if value)


def subject_for_content(code: str, stage: str) -> str:
    if stage != "第五學習階段":
        return ""
    return HIGH_SCHOOL_SUBJECTS.get(code[:1], "")


def data_rows(workbook: XlsxWorkbook, sheet_name: str) -> list[tuple[int, list[str]]]:
    rows = workbook.rows(sheet_name)
    if not rows:
        raise ValueError(f"{sheet_name} is empty")
    return rows[1:]


def build_cross_concepts(workbook: XlsxWorkbook) -> list[dict[str, str]]:
    sheet_name = CROSS_CONCEPT_SHEET
    rows = workbook.rows(sheet_name)
    if not rows:
        raise ValueError(f"{sheet_name} is empty")

    _, header = rows[0]
    actual_columns = [text_cell(header, index) for index in range(len(header))]
    if actual_columns != CROSS_CONCEPT_COLUMNS:
        raise ValueError(
            f"{sheet_name} has unexpected columns: {actual_columns}; expected: {CROSS_CONCEPT_COLUMNS}"
        )

    entries: list[dict[str, str]] = []
    for row_number, source_row in rows[1:]:
        if is_blank(source_row) or is_example(source_row):
            continue

        entry = {
            column: text_cell(source_row, index)
            for index, column in enumerate(CROSS_CONCEPT_COLUMNS)
        }
        missing = [column for column, value in entry.items() if not value]
        if missing:
            raise ValueError(f"{sheet_name}!{row_number} has incomplete cross-concept data: {', '.join(missing)}")
        entries.append(entry)

    return entries


def build_learning_content(workbook: XlsxWorkbook) -> dict:
    cross_concepts = build_cross_concepts(workbook)
    rows: list[dict] = []
    for sheet_name, stage in CONTENT_SHEETS:
        for row_number, source_row in data_rows(workbook, sheet_name):
            if is_blank(source_row) or is_example(source_row):
                continue

            code = cell(source_row, 3)
            description = text_cell(source_row, 4)
            if not code or not description:
                raise ValueError(f"{sheet_name}!{row_number} has incomplete learning content")

            notes = note_text(
                [
                    ("跨科概念", text_cell(source_row, 0)),
                    ("主題", text_cell(source_row, 1)),
                    ("次主題", text_cell(source_row, 2)),
                    ("來源工作表", sheet_name),
                ]
            )
            rows.append(
                {
                    "value": code,
                    "學習階段": stage,
                    "科目": subject_for_content(code, stage),
                    "條目說明": description,
                    "備註": notes,
                    "對應學習表現": [],
                }
            )

    assert_unique_values(rows, "學習內容")
    return {"學習階段_to_grades": STAGE_TO_GRADES, "跨科概念": cross_concepts, "學習內容": rows}


def build_learning_performance(workbook: XlsxWorkbook) -> dict:
    rows: list[dict] = []
    for sheet_name, stage in PERFORMANCE_SHEETS:
        for row_number, source_row in data_rows(workbook, sheet_name):
            if is_blank(source_row) or is_example(source_row):
                continue

            dimension = text_cell(source_row, 0)
            item = text_cell(source_row, 1)
            code = cell(source_row, 2)
            description = text_cell(source_row, 3)
            if not code and not description:
                continue
            if not dimension or not item or not code or not description:
                raise ValueError(f"{sheet_name}!{row_number} has incomplete learning performance")

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

    assert_unique_values(rows, "學習表現")
    return {"學習階段_to_grades": STAGE_TO_GRADES, "學習表現": rows}


def normalize_code_for_lookup(code: str) -> str:
    normalized = re.sub(r"\s+", "", code.translate(DASH_TRANSLATION))
    roman_tokens = sorted(ROMAN_STAGE_TOKENS.items(), key=lambda item: len(item[0]), reverse=True)
    for ascii_roman, unicode_roman in roman_tokens:
        normalized = re.sub(
            rf"(?<=-){ascii_roman}(?=[-a-zA-Z])",
            unicode_roman,
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized


def normalized_code_lookup(rows: list[dict], label: str) -> dict[str, str]:
    lookup: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for row in rows:
        value = row["value"]
        normalized = normalize_code_for_lookup(value)
        if normalized in lookup:
            duplicates.setdefault(normalized, [lookup[normalized]]).append(value)
        lookup[normalized] = value
    if duplicates:
        details = "; ".join(f"{key}: {', '.join(values)}" for key, values in duplicates.items())
        raise ValueError(f"Duplicate normalized {label} values: {details}")
    return lookup


def docx_cell_text(cell_element: ET.Element) -> str:
    return "".join(text_node.text or "" for text_node in cell_element.iter(word_tag("t")))


def docx_table_rows(path: Path) -> list[tuple[int, int, list[str]]]:
    with ZipFile(path) as docx:
        root = ET.fromstring(docx.read("word/document.xml"))

    rows: list[tuple[int, int, list[str]]] = []
    for table_index, table in enumerate(root.findall(f".//{word_tag('tbl')}"), start=1):
        for row_index, row in enumerate(table.findall(word_tag("tr")), start=1):
            cells = [docx_cell_text(cell_element) for cell_element in row.findall(word_tag("tc"))]
            rows.append((table_index, row_index, cells))
    return rows


def extract_codes_from_cell(
    raw_value: str,
    lookup: dict[str, str],
    sorted_normalized_codes: list[str],
    label: str,
    table_index: int,
    row_index: int,
) -> list[str]:
    normalized_value = normalize_code_for_lookup(raw_value)
    codes: list[str] = []
    index = 0
    while index < len(normalized_value):
        for normalized_code in sorted_normalized_codes:
            if normalized_value.startswith(normalized_code, index):
                codes.append(lookup[normalized_code])
                index += len(normalized_code)
                break
        else:
            raise ValueError(
                f"{CONTENT_PERFORMANCE_DOCX_PATH.name} table {table_index} row {row_index} "
                f"has unknown {label} code near {normalized_value[index:]!r} from {raw_value!r}"
            )
    return codes


def content_performance_links(
    learning_content: dict,
    learning_performance: dict,
) -> dict[str, set[str]]:
    content_lookup = normalized_code_lookup(learning_content["學習內容"], "學習內容")
    performance_lookup = normalized_code_lookup(learning_performance["學習表現"], "學習表現")
    sorted_content_codes = sorted(content_lookup, key=len, reverse=True)
    sorted_performance_codes = sorted(performance_lookup, key=len, reverse=True)
    links: dict[str, set[str]] = {row["value"]: set() for row in learning_content["學習內容"]}

    for table_index, row_index, cells in docx_table_rows(CONTENT_PERFORMANCE_DOCX_PATH):
        if len(cells) < 3:
            continue

        performance_raw = cells[0]
        content_raw = cells[2]
        if "學習表現" in performance_raw or "學習內容" in content_raw:
            continue
        if not performance_raw.strip() and not content_raw.strip():
            continue
        if not performance_raw.strip() or not content_raw.strip():
            raise ValueError(
                f"{CONTENT_PERFORMANCE_DOCX_PATH.name} table {table_index} row {row_index} "
                "has an incomplete content/performance mapping row"
            )

        performance_codes = extract_codes_from_cell(
            performance_raw,
            performance_lookup,
            sorted_performance_codes,
            "學習表現",
            table_index,
            row_index,
        )
        content_codes = extract_codes_from_cell(
            content_raw,
            content_lookup,
            sorted_content_codes,
            "學習內容",
            table_index,
            row_index,
        )

        for content_code in content_codes:
            links[content_code].update(performance_codes)

    return links


def populate_learning_content_performance_links(
    learning_content: dict,
    learning_performance: dict,
) -> None:
    links = content_performance_links(learning_content, learning_performance)
    reverse_links: dict[str, set[str]] = {
        row["value"]: set() for row in learning_performance["學習表現"]
    }

    for row in learning_content["學習內容"]:
        content_code = row["value"]
        row["對應學習表現"] = sorted(links[content_code], key=normalize_code_for_lookup)
        for performance_code in links[content_code]:
            reverse_links[performance_code].add(content_code)

    for row in learning_performance["學習表現"]:
        row["對應學習內容"] = sorted(reverse_links[row["value"]], key=normalize_code_for_lookup)


def extract_core_code(code: str, instruction: str, sheet_name: str, row_number: int) -> str:
    if code:
        return code
    match = CORE_CODE_RE.match(instruction)
    if not match:
        raise ValueError(f"{sheet_name}!{row_number} has no 指標代碼 and no leading code")
    return match.group(1)


def remove_leading_code(instruction: str, code: str) -> str:
    if instruction.startswith(code):
        return instruction[len(code) :].strip()
    return instruction


def core_meta_from_code(code: str, sheet_name: str, row_number: int) -> tuple[str, str, str]:
    parts = code.split("-")
    if len(parts) != 3 or not parts[1] or not parts[2]:
        raise ValueError(f"{sheet_name}!{row_number} has invalid core competency code: {code}")
    stage = parts[1]
    item = parts[2]
    dimension = item[:1]
    return stage, dimension, item


def build_core_competencies(workbook: XlsxWorkbook) -> dict:
    social_core = json.loads(SOCIAL_CC_PATH.read_text(encoding="utf-8"))
    entries: list[dict] = []
    sheet_name = "核心素養"

    for row_number, source_row in data_rows(workbook, sheet_name):
        if is_blank(source_row) or is_example(source_row):
            continue

        instruction = text_cell(source_row, 3)
        code = extract_core_code(cell(source_row, 2), instruction, sheet_name, row_number)
        if not instruction:
            raise ValueError(f"{sheet_name}!{row_number} has no core competency instruction")

        stage, dimension, item = core_meta_from_code(code, sheet_name, row_number)
        entries.append(
            {
                "value": code,
                "stage": stage,
                "面向": dimension,
                "項目": item,
                "instruction": remove_leading_code(instruction, code),
            }
        )

    assert_unique_values(entries, "核心素養")
    return {
        "學習階段_to_stage": social_core["學習階段_to_stage"],
        "面向": social_core["面向"],
        "項目": social_core["項目"],
        "核心素養": entries,
    }


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    with XlsxWorkbook(WORKBOOK_PATH) as workbook:
        learning_content = build_learning_content(workbook)
        learning_performance = build_learning_performance(workbook)
        core_competencies = build_core_competencies(workbook)

    populate_learning_content_performance_links(learning_content, learning_performance)

    write_json(CURRICULUM_DIR / "learning_content.json", learning_content)
    write_json(CURRICULUM_DIR / "learning_performance.json", learning_performance)
    write_json(CURRICULUM_DIR / "core_competencies.json", core_competencies)

    print(
        f"Wrote {CURRICULUM_DIR}/learning_content.json "
        f"({len(learning_content['跨科概念'])} cross-concept entries, {len(learning_content['學習內容'])} content entries)"
    )
    print(f"Wrote {CURRICULUM_DIR}/learning_performance.json ({len(learning_performance['學習表現'])} entries)")
    print(f"Wrote {CURRICULUM_DIR}/core_competencies.json ({len(core_competencies['核心素養'])} entries)")


if __name__ == "__main__":
    main()
