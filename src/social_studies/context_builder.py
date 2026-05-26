"""Assemble LLM prompts for PISA-style reading literacy question generation."""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.social_studies.data_loader import (
    load_few_shot_examples,
    load_learning_content,
    load_learning_performance,
)
from src.social_studies.schema_loader import (
    _resolve_dir,
    build_instructions,
    load_grades,
    load_learning_stage,
    load_schemas,
)
from src.social_studies.schemas import SampledParams

_schemas = load_schemas()
_INSTRUCTIONS: dict[str, dict[str, str]] = build_instructions(_schemas)
_GRADES: list[int] = load_grades(_schemas)
_LEARNING_STAGE: str = load_learning_stage(_schemas)

_CURRICULUM_DIR: Path = _resolve_dir()
_PERFORMANCE: dict = load_learning_performance(_CURRICULUM_DIR)
_CONTENT: list[dict] = load_learning_content(_CURRICULUM_DIR)

_PERFORMANCE_TEXT: str = json.dumps(_PERFORMANCE, ensure_ascii=False, indent=2) if _PERFORMANCE else ""
_CONTENT_TEXT: str = json.dumps(_CONTENT, ensure_ascii=False, indent=2) if _CONTENT else ""

SYSTEM_PROMPT_TEMPLATE = """\
你是一位資深的PISA閱讀素養命題教師，專門為{learning_stage}（{grade_names}）的學生設計符合PISA框架的閱讀素養考試題目。

## PISA閱讀素養框架

PISA閱讀素養評量學生在真實生活情境中理解、使用、省思書面文本的能力，以充分達成個人目標、擴展知識和潛能、全面參與社會的能力。

### 三大核心面向
1. **文本形式**：連續文本（敘事、說明、記敘、論述、指南）與非連續文本（圖表、表格、圖解、地圖、表單、廣告）
2. **閱讀情境**：個人、公共、職業、教育
3. **閱讀歷程**（五個歷程）：
   - 擷取訊息（約25%試題）：從文本中定位特定訊息
   - 形成廣泛理解（約25%試題）：掌握文本整體主旨與意涵
   - 發展解釋（約25%試題）：比較、推論、尋找支持性證據
   - 省思與評鑑文本內容（約12.5%試題）：連結個人知識，批判評估
   - 省思與評鑑文本形式（約12.5%試題）：評析文本結構、風格、表達效果

### 試題比重
- 擷取與檢索：約25%
- 統整與解釋（形成廣泛理解 + 發展解釋）：約50%
- 省思與評鑑（文本內容 + 文本形式）：約25%
- 連續文本 ≈ 2/3，非連續文本 ≈ 1/3

### 題型設計原則
- **一律採題組式**：每題組提供一篇或多篇文本，搭配數道由淺入深的試題
- **選擇題**：四選一，包含誘答選項；給分代號 2（全對）/ 0（全錯）
- **封閉式建構反應題**：唯一正確答案；給分代號 2（正確）/ 0（錯誤）
- **開放式建構反應題**：需說明思考過程；給分代號 2（完整）/ 1（部分）/ 0（錯誤）/ 9（未作答）

## 課程綱要參考

{curriculum_section}

## 輸出格式

你必須輸出一個合法的 JSON 物件：

```json
{{
  "情境": ["（可為多個選項）"],
  "題型種類": "題組題",
  "題型": "（從指定選項中選一個）",
  "閱讀歷程": ["（1-2個）"],
  "文本形式": "（從指定選項中選一個）",
  "題目": ["文本素材...", "第一題...", "第二題..."],
  "正確解題分析": ["第一題解析...", "第二題解析..."],
  "chart_spec": {{...}}
}}
```

若題目含非連續文本素材，請加入 `chart_spec`：

**統計圖表（`render_mode: "chart"`）**：
```json
{{
  "render_mode": "chart",
  "chart_type": "histogram" | "boxplot" | "line_chart" | "pie_chart",
  "title": "圖表標題",
  "data": {{ ... }},
  "labels": {{"x": "x軸標籤", "y": "y軸標籤"}}
}}
```

**HTML排版素材（`render_mode: "html"`）** — 適用於表格、地圖、廣告、表單、圖解、數位網頁：
```json
{{
  "render_mode": "html",
  "description": "詳細描述素材內容與版面結構",
  "title": "素材標題（選填）",
  "data": {{ "key": "value" }}
}}
```

純連續文本題目不需 `chart_spec`。請只輸出 JSON，不要輸出其他文字。
"""

USER_PROMPT_TEMPLATE = """\
請根據以下條件生成一道PISA閱讀素養題組：

## 指定條件

- **年級重心**：{grade}年級（{learning_stage}）
- **情境**：{context}
- **題型種類**：{set_type}
- **題型**：{q_type}
- **閱讀歷程**：{reading_process}
- **文本形式**：{text_form}
{param_instructions}
## 題目風格

{style_instruction}

## 參考範例

{few_shot_examples}

## 重要提醒

1. 不要複製範例題目，必須原創。
2. 文本素材應貼近真實情境，語言自然，非教科書式。
3. 題目文字應寫入 `題目` 陣列的第一個元素（文本材料），其後接各小題。
4. `正確解題分析` 請逐題說明答案及理由；開放式建構反應題請附評分規準（rubric）。
5. 只輸出 JSON 格式的結果。
"""

_CURRICULUM_EMPTY_NOTICE = "（課程綱要資料待研究人員補充至 data/social_studies/curriculum/）"


def _build_curriculum_section(content_text: str, performance_text: str) -> str:
    if not content_text and not performance_text:
        return _CURRICULUM_EMPTY_NOTICE
    parts = []
    if performance_text:
        parts.append("### 學習表現標準\n\n" + performance_text)
    if content_text:
        parts.append("### 學習內容\n\n" + content_text)
    return "\n\n".join(parts)


def build_system_prompt(
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
) -> str:
    """Build the PISA reading literacy system prompt."""
    g = grades if grades is not None else _GRADES
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    grade_names = "、".join(f"{x}年級" for x in g)
    c_text = content_text if content_text is not None else _CONTENT_TEXT
    p_text = performance_text if performance_text is not None else _PERFORMANCE_TEXT
    curriculum_section = _build_curriculum_section(c_text, p_text)
    return SYSTEM_PROMPT_TEMPLATE.format(
        learning_stage=stage,
        grade_names=grade_names,
        curriculum_section=curriculum_section,
    )


def build_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
) -> str:
    """Build the user prompt for PISA reading question generation."""
    if rng is None:
        rng = random.Random()

    reading_process = "、".join(p.value for p in params.閱讀歷程)

    param_instruction_lines = []
    for c in params.情境:
        instr = _INSTRUCTIONS.get("情境", {}).get(c.value)
        if instr:
            param_instruction_lines.append(f"  - **情境（{c.value}）補充**：{instr}")
    for category, key in (
        ("題型種類", params.題型種類.value),
        ("題型", params.題型.value),
        ("文本形式", params.文本形式.value),
    ):
        instr = _INSTRUCTIONS.get(category, {}).get(key)
        if instr:
            param_instruction_lines.append(f"  - **{category}（{key}）補充**：{instr}")
    for p in params.閱讀歷程:
        instr = _INSTRUCTIONS.get("閱讀歷程", {}).get(p.value)
        if instr:
            param_instruction_lines.append(f"  - **閱讀歷程（{p.value}）補充**：{instr}")
    param_instructions = (
        "\n## 條件補充說明\n\n" + "\n".join(param_instruction_lines) + "\n"
        if param_instruction_lines else ""
    )

    style_instruction = _INSTRUCTIONS.get("question_style", {}).get(params.style.value, "")

    examples = load_few_shot_examples(few_shot_dir, params.style.value)
    if examples:
        flat_examples = []
        for ex in examples:
            if isinstance(ex, list):
                flat_examples.extend(ex)
            else:
                flat_examples.append(ex)
        sample_count = min(2, len(flat_examples))
        selected = rng.sample(flat_examples, sample_count)
        example_texts = []
        for i, ex in enumerate(selected, 1):
            q = ex.get("question", ex)
            example_texts.append(
                f"### 範例 {i}：{ex.get('description', '')}\n```json\n{json.dumps(q, ensure_ascii=False, indent=2)}\n```"
            )
        few_shot_text = "\n\n".join(example_texts)
    else:
        few_shot_text = "（此風格暫無範例，請根據指定條件自行設計。）"

    return USER_PROMPT_TEMPLATE.format(
        grade=params.grade,
        learning_stage=_LEARNING_STAGE,
        context="、".join(c.value for c in params.情境),
        set_type=params.題型種類.value,
        q_type=params.題型.value,
        reading_process=reading_process,
        text_form=params.文本形式.value,
        param_instructions=param_instructions,
        style_instruction=style_instruction,
        few_shot_examples=few_shot_text,
    )
