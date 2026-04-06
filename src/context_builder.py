"""Assemble LLM prompts with curriculum context and few-shot examples."""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.data_loader import load_few_shot_examples
from src.schema_loader import build_style_instructions, load_schemas
from src.schemas import SampledParams

_STYLE_INSTRUCTIONS: dict[str, str] = build_style_instructions(load_schemas())

SYSTEM_PROMPT_TEMPLATE = """\
你是一位資深的台灣國中數學命題教師，專門為第四學習階段（7年級、8年級、9年級）的學生設計考試題目。

## 命題原則

1. 題目必須符合十二年國民基本教育數學領域課程綱要的學習內容。
2. 題目應確保 7-9 年級學生具備足夠先備知識可以作答，但也要有適當的挑戰性。
3. 你必須了解國小（1-6年級）的學習內容作為先備知識基礎，也要了解高中（10-12年級）的學習內容以確保不超出範圍。
4. 選項設計應包含合理的誘答選項，針對學生常見的錯誤概念。
5. 解題分析必須完整、正確，包含逐步推導過程。

## 完整學習內容（1-12年級）

以下為完整的學習內容 JSON，涵蓋所有年級：

{curriculum_json}

## 學習表現標準

{performance_json}

## 課程綱要說明

{intro_text}

## 輸出格式

你必須輸出一個合法的 JSON 物件，格式如下：

```json
{{
  "情境": "（從指定選項中選一個）",
  "題型種類": "（從指定選項中選一個）",
  "題型": "（從指定選項中選一個）",
  "數學思考": ["（1-3個）"],
  "學習內容": [
    {{"編碼": "X-Y-Z", "說明": "..."}}
  ],
  "題目": ["題目文字", "選項或子題..."],
  "正確解題分析": ["步驟一...", "步驟二..."],
  "chart_spec": {{...}}
}}
```

如果題目需要圖表或圖片，請在 JSON 中加入 `chart_spec` 欄位，包含：
- `chart_type`: "histogram" | "boxplot" | "line_chart" | "pie_chart" | "geometry"
- `title`: 圖表標題
- `data`: 圖表所需的數據（具體格式依圖表類型而定）
- `labels`: 座標軸標籤
- `description`: 圖表的文字描述

如果題目不需要圖表，則不要包含 `chart_spec` 欄位。

請只輸出 JSON，不要輸出其他文字。
"""

USER_PROMPT_TEMPLATE = """\
請根據以下條件生成一道數學考試題目：

## 指定條件

- **年級重心**：{grade}年級
- **情境**：{context}
- **題型種類**：{set_type}
- **題型**：{q_type}
- **數學思考**：{thinking}
- **必須涵蓋的學習內容**：
{content_list}

## 題目風格

{style_instruction}

## 參考範例

以下是符合類似風格的範例題目，供你參考格式和難度水準：

{few_shot_examples}

## 重要提醒

1. 不要複製範例題目，必須原創。
2. 確保答案正確，解題過程完整。
3. 學習內容可以跨年級整合（7-9年級範圍內），但核心考點應以指定的學習內容為主。
4. 選項的誘答設計應針對常見錯誤概念。
5. 只輸出 JSON 格式的結果。
"""



def build_system_prompt(
    curriculum_json: str,
    performance_json: str,
    intro_text: str,
) -> str:
    """Build the system prompt with full curriculum context."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        curriculum_json=curriculum_json,
        performance_json=performance_json,
        intro_text=intro_text,
    )


def build_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
) -> str:
    """Build the user prompt with sampled parameters and few-shot examples."""
    if rng is None:
        rng = random.Random()

    # Format learning content list
    content_lines = []
    for item in params.學習內容:
        content_lines.append(f"  - {item.編碼}：{item.說明}")
    content_list = "\n".join(content_lines)

    # Format math thinking
    thinking = "、".join(t.value for t in params.數學思考)

    # Style instruction
    style_instruction = _STYLE_INSTRUCTIONS[params.style.value]

    # Load and format few-shot examples
    examples = load_few_shot_examples(few_shot_dir, params.style.value)
    if examples:
        # Flatten if each file is a list
        flat_examples = []
        for ex in examples:
            if isinstance(ex, list):
                flat_examples.extend(ex)
            else:
                flat_examples.append(ex)

        # Pick 1-2 examples randomly
        sample_count = min(2, len(flat_examples))
        selected = rng.sample(flat_examples, sample_count)
        example_texts = []
        for i, ex in enumerate(selected, 1):
            q = ex.get("question", ex)
            example_texts.append(f"### 範例 {i}：{ex.get('description', '')}\n```json\n{json.dumps(q, ensure_ascii=False, indent=2)}\n```")
        few_shot_text = "\n\n".join(example_texts)
    else:
        few_shot_text = "（此風格暫無範例，請根據指定條件自行設計。）"

    return USER_PROMPT_TEMPLATE.format(
        grade=params.grade,
        context=params.情境.value,
        set_type=params.題型種類.value,
        q_type=params.題型.value,
        thinking=thinking,
        content_list=content_list,
        style_instruction=style_instruction,
        few_shot_examples=few_shot_text,
    )
