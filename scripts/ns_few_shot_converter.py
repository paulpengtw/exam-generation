"""Convert NS example_exams DOCX files to few_shot JSON format.

Usage:
    python scripts/ns_few_shot_converter.py <docx_file1> [docx_file2 ...]

Each docx is converted to a JSON array and saved to the appropriate
few_shot subfolder based on the dominant question type.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import anthropic
import docx as python_docx

REPO_ROOT = Path(__file__).resolve().parent.parent
NS_DIR = REPO_ROOT / "data" / "natural_sciences"
EXAMPLE_DIR = NS_DIR / "example_exams"
FEW_SHOT_DIR = NS_DIR / "few_shot"
CURRICULUM_DIR = NS_DIR / "curriculum"

# Output folders
SIMPLE_MC_DIR = FEW_SHOT_DIR / "Simple-multiple-choice"
COMPLEX_MC_DIR = FEW_SHOT_DIR / "Complex-multiple-choice"
CONSTRUCTED_DIR = FEW_SHOT_DIR / "Constructed-response"

for d in (SIMPLE_MC_DIR, COMPLEX_MC_DIR, CONSTRUCTED_DIR):
    d.mkdir(parents=True, exist_ok=True)


def load_curriculum():
    lc = json.loads((CURRICULUM_DIR / "learning_content.json").read_text(encoding="utf-8"))
    lp = json.loads((CURRICULUM_DIR / "learning_performance.json").read_text(encoding="utf-8"))
    sp = (CURRICULUM_DIR / "schema_parameters.csv").read_text(encoding="utf-8")
    lc_lookup = {item["value"]: item for item in lc.get("學習內容", [])}
    lp_lookup = {item["value"]: item for item in lp.get("學習表現", [])}
    return lc_lookup, lp_lookup, sp


def extract_docx_content(docx_path: Path) -> dict:
    """Extract all text from a docx into a structured dict."""
    doc = python_docx.Document(str(docx_path))

    metadata = {}
    questions = []

    for ti, table in enumerate(doc.tables):
        rows_data = {}
        for row in table.rows:
            if len(row.cells) >= 2:
                key = row.cells[0].text.strip()
                val = row.cells[1].text.strip()
                if key:
                    rows_data[key] = val

        if ti == 0:
            metadata = rows_data
        else:
            # It's a question table
            q_key = None
            for k in rows_data:
                if re.match(r"問題[一二三四五六七八九十\d]+", k):
                    q_key = k
                    break
            if q_key:
                questions.append(rows_data)

    return {"metadata": metadata, "questions": questions, "filename": docx_path.name}


def build_prompt(content: dict, lc_lookup: dict, lp_lookup: dict, schema_params: str) -> str:
    meta = content["metadata"]
    questions = content["questions"]
    filename = content["filename"]

    # Look up learning content codes from questions
    lc_codes_found = {}
    for q in questions:
        for key_name in ("學習內容", "學習內容(對應課綱)", "學習重點"):
            if key_name in q:
                codes_text = q[key_name]
                for code in re.findall(r"[A-Z][a-z]-[IVX]+-\d+", codes_text):
                    if code in lc_lookup:
                        lc_codes_found[code] = lc_lookup[code].get("條目說明", "")
                    else:
                        lc_codes_found[code] = "(not found in curriculum)"

    lc_info = "\n".join(f"  {k}: {v}" for k, v in lc_codes_found.items()) or "  (none found)"

    raw_questions_text = ""
    for i, q in enumerate(questions, 1):
        raw_questions_text += f"\n--- Question {i} ---\n"
        for k, v in q.items():
            raw_questions_text += f"{k}: {v[:500]}\n"

    prompt = f"""You are converting a Taiwanese natural science exam (PISA-style) from its raw DOCX format into a structured JSON few-shot example.

FILE: {filename}

## Raw Metadata
{json.dumps(meta, ensure_ascii=False, indent=2)[:2000]}

## Raw Questions
{raw_questions_text[:6000]}

## Learning Content Codes Found (from curriculum lookup)
{lc_info}

## Schema Parameters (controlled vocabulary)
{schema_params[:3000]}

## Output Format Required

Produce a JSON array with exactly ONE object. Follow this schema exactly:

```json
[
  {{
    "style": "text_only",
    "description": "<題目名稱 from metadata>",
    "question": {{
      "核心問題": "<core scientific question being explored — one sentence>",
      "文本": "<full 題幹 passage text>",
      "取材來源": [],
      "情境": ["<one of: Personal | Local and national | Global>"],
      "情境子類別": "<appropriate subcategory from schema_parameters.csv>",
      "題型種類": "題組題",
      "題型": "<dominant type: Simple multiple-choice | Complex multiple-choice | Constructed response>",
      "科學能力": ["<one or more from: 能力一：以科學的角度解釋現象 | 能力二：建構和評估科學探究之設計，並批判性地詮釋科學資料和證據 | 能力三：研究、評估和運用科學資訊進行決策與行動>"],
      "題目內容類型": "純文字",
      "題目": ["<題幹 text>", "<question 1 full text>", "<question 2 full text>", "..."],
      "正確解題分析": ["<answer explanation for q1>", "<answer explanation for q2>", "..."],
      "subquestions": [
        {{
          "序號": 1,
          "年級": <8 for 第四學習階段 (Ⅳ), 6 for 第三學習階段 (Ⅲ), 11 for 第五學習階段 (Ⅴ)>,
          "科目": ["自然科學"],
          "科學能力": ["<能力一/二/三 based on 評量架構>"],
          "學習內容": [{{"編碼": "<code>", "說明": "<description from curriculum>"}}],
          "學習表現": [],
          "出題概念": "<what concept is being assessed>",
          "題型": "<Simple multiple-choice | Complex multiple-choice | Constructed response>",
          "題目": "<full question text>",
          "答案": "<answer — for MC: letter(s), for constructed: key points>",
          "答案解析": "<explanation of the answer>",
          "評分規準": <[] for Simple MC; [{{"編碼": "2", "說明": "..."}}, {{"編碼": "1", "說明": "..."}}, {{"編碼": "0", "說明": "..."}}] for Complex MC and Constructed response>
        }}
      ]
    }}
  }}
]
```

## Classification Rules

**題型 per subquestion:**
- Simple multiple-choice: single correct answer from A/B/C/D options, or hot-spot click
- Complex multiple-choice: series of true/false, multiple-select, dropdown, drag-and-drop/matching/ordering
- Constructed response: requires written text answer, drawing, short explanation

**Dominant 題型 for the overall exam:** the type that appears most frequently among subquestions.

**科學能力 mapping from 評量架構:**
- 解釋現象 → 能力一：以科學的角度解釋現象
- 運用證據 / 詮釋資料 → 能力二：建構和評估科學探究之設計，並批判性地詮釋科學資料和證據
- 辨識議題 / 批判 / 決策 → 能力三：研究、評估和運用科學資訊進行決策與行動

**情境 selection:** Choose based on the context of the exam passage:
- Personal: individual health, food, personal science choices
- Local and national: community, national policy, environment
- Global: climate, global sustainability, biodiversity

**年級:** Use the Roman numeral in the 學習內容 code:
- Ⅱ → 4, Ⅲ → 6, Ⅳ → 8, Ⅴ → 11

**style:** Use "text_only" unless the question explicitly references images/charts (then "with_image").

Output ONLY the JSON array, no explanation, no markdown fences.
"""
    return prompt


def slugify(title: str) -> str:
    """Create a filename slug from Chinese title."""
    slug = re.sub(r"[^\w一-鿿㐀-䶿]", "_", title)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:60] or "untitled"


def determine_output_dir(dominant_type: str) -> Path:
    t = dominant_type.lower()
    if "simple" in t:
        return SIMPLE_MC_DIR
    elif "complex" in t:
        return COMPLEX_MC_DIR
    else:
        return CONSTRUCTED_DIR


def convert_file(docx_path: Path, client: anthropic.Anthropic,
                 lc_lookup: dict, lp_lookup: dict, schema_params: str) -> Path | None:
    print(f"Processing: {docx_path.name}", flush=True)

    content = extract_docx_content(docx_path)
    if not content["questions"]:
        print(f"  SKIP: no questions found in {docx_path.name}", flush=True)
        return None

    prompt = build_prompt(content, lc_lookup, lp_lookup, schema_params)

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  ERROR: JSON parse failed for {docx_path.name}: {e}", flush=True)
        print(f"  Raw response start: {raw[:300]}", flush=True)
        return None

    if not data or not isinstance(data, list):
        print(f"  ERROR: unexpected structure for {docx_path.name}", flush=True)
        return None

    dominant_type = data[0].get("question", {}).get("題型", "Constructed response")
    out_dir = determine_output_dir(dominant_type)

    title = data[0].get("description", "") or content["metadata"].get("題目名稱", "untitled")
    slug = slugify(title)
    out_path = out_dir / f"{slug}.json"

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {out_path.relative_to(REPO_ROOT)}", flush=True)
    return out_path


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/ns_few_shot_converter.py <docx_file1> [...]")
        sys.exit(1)

    lc_lookup, lp_lookup, schema_params = load_curriculum()
    client = anthropic.Anthropic()

    files = [Path(f) for f in sys.argv[1:]]
    succeeded = []
    failed = []

    for f in files:
        if not f.exists():
            print(f"NOT FOUND: {f}", flush=True)
            failed.append(str(f))
            continue
        result = convert_file(f, client, lc_lookup, lp_lookup, schema_params)
        if result:
            succeeded.append(str(result))
        else:
            failed.append(str(f))

    print(f"\nDone: {len(succeeded)} succeeded, {len(failed)} failed")
    if failed:
        print("Failed:", failed)


if __name__ == "__main__":
    main()
