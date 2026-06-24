# ruff: noqa: E501
"""Assemble LLM prompts for PISA Science + 108課綱自然科學 question generation."""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.natural_sciences.curriculum_loader import (
    content_instructions,
    load_learning_content,
    load_learning_performance,
    performance_instructions,
)
from src.natural_sciences.data_loader import load_few_shot_example_groups
from src.natural_sciences.schema_loader import (
    build_instructions,
    load_grades,
    load_learning_stage,
    load_schemas,
)
from src.natural_sciences.schemas import SampledParams

_schemas = load_schemas()
_INSTRUCTIONS: dict[str, dict[str, str]] = build_instructions(_schemas)
_GRADES: list[int] = load_grades(_schemas)
_LEARNING_STAGE: str = load_learning_stage(_schemas)

_PERFORMANCE_DATA: dict = load_learning_performance()
_CONTENT_DATA: dict = load_learning_content()


def _stage_filtered_content(data: dict, learning_stage: str) -> dict:
    return {
        "學習階段_to_grades": data.get("學習階段_to_grades", {}),
        "跨科概念": data.get("跨科概念", []),
        "學習內容": [
            row for row in data.get("學習內容", [])
            if row.get("學習階段") == learning_stage
        ],
    }


def _stage_filtered_performance(data: dict, learning_stage: str) -> dict:
    return {
        "學習階段_to_grades": data.get("學習階段_to_grades", {}),
        "學習表現": [
            row for row in data.get("學習表現", [])
            if row.get("學習階段") == learning_stage
        ],
    }


_PERFORMANCE_TEXT: str = json.dumps(
    _stage_filtered_performance(_PERFORMANCE_DATA, _LEARNING_STAGE),
    ensure_ascii=False,
    indent=2,
)
_CONTENT_TEXT: str = json.dumps(
    _stage_filtered_content(_CONTENT_DATA, _LEARNING_STAGE),
    ensure_ascii=False,
    indent=2,
)
_LC_INSTRUCTIONS: dict[str, str] = content_instructions(_CONTENT_DATA)
_LP_INSTRUCTIONS: dict[str, str] = performance_instructions(_PERFORMANCE_DATA)

CONTENT_TYPE_INSTRUCTIONS: dict[str, str] = {
    "純文字": (
        "本題組必須只使用文字素材。不得輸出 `chart_spec` 或任何需要渲染成圖片的資料；"
        "題目、答案與解釋只能依據 `文本` 欄位中的文字、數據描述或實驗敘述。"
    ),
    "含圖片": (
        "本題組必須包含視覺式科學素材，例如實驗裝置圖、模型圖、流程圖、標籤圖、"
        "地圖或情境示意圖。請輸出 `chart_spec`，優先使用 `render_mode: \"html\"`，"
        "並在 `description` 與 `data` 中完整描述版面與作答所需元素。"
    ),
    "graphs/charts/tables": (
        "本題組必須包含數據圖表或表格。統計圖請使用 `render_mode: \"chart\"`；"
        "實驗數據表、分類表或多欄比較表請使用 `render_mode: \"html\"`，並在 `data` 中提供完整資料。"
    ),
}

SYSTEM_PROMPT_TEMPLATE = """\
你是一位資深的108課綱自然科學領域命題教師，專門為{learning_stage}（{grade_names}）設計 PISA Science 風格的科學素養題組。
本題庫要融合兩個框架：
1. PISA Science Framework：情境、科學能力、資料證據、探究設計、科學資訊決策與環境能力。
2. 臺灣108課綱自然科學領域：每道小題必須對應合適的 `學習內容` 與 `學習表現` 代號。

## 題組結構
每道題組（題組題）包含：
1. **核心問題**：一句話說明本題組要探究的科學或社會生態問題。若使用者提供「指定核心問題」，請逐字使用。
2. **文本**：真實科學情境素材，可包含研究摘要、實驗紀錄、圖表描述、新聞或政策資料。
3. **取材來源**：列出素材來源；可為合理擬真來源，但不得捏造不存在的精確網址。
4. **小題（subquestions）**：3–7 道由淺入深的小題，共用同一素材但可獨立作答。

## PISA Science 題型
- **Simple multiple-choice**：四選一單選題，或在圖形／文本中點選答案元素的 hot spot 題。
- **Complex multiple-choice**：一系列是非題且整組計分、多選題、下拉選單填空、拖放配對、排序或分類。
- **Constructed response**：短語、二到四句短段落、或簡單圖形／圖表／示意圖作答。繪圖題需描述簡易作答介面與評分重點。

## 各小題必須標記
- `年級`：7、8 或 9
- `科目`：自然科學
- `科學能力`：從指定條件中的 PISA Science / Environmental Science competency 選擇
- `學習內容`：108課綱自然科學學習內容編碼+說明
- `學習表現`：108課綱自然科學學習表現編碼+說明
- `出題概念`：一句話說明此題評量學生何種科學能力

## 評分規準
- Simple multiple-choice：正確代號 2，錯誤代號 0。
- Complex multiple-choice：通常採整組計分；全對代號 2，部分正確可給 1，錯誤代號 0，未作答 0X。
- Constructed response：必須附 `評分規準`，使用 2 / 1 / 0 / 0X，並提供學生作答實例。

## 課程綱要參考

{curriculum_section}

## 輸出格式
你必須輸出合法 JSON 物件，格式如下：

```json
{{
  "核心問題": "本題組的核心問題",
  "文本": "完整科學情境素材",
  "取材來源": ["來源一", "來源二"],
  "情境": ["Personal"],
  "情境子類別": "Maintenance of health",
  "題型種類": "題組題",
  "題型": "Simple multiple-choice",
  "科學能力": ["能力一：以科學的角度解釋現象"],
  "題目內容類型": "純文字",
  "subquestions": [
    {{
      "序號": 1,
      "年級": 8,
      "科目": ["自然科學"],
      "科學能力": ["能力一：以科學的角度解釋現象"],
      "學習內容": [{{"編碼": "Ka-Ⅳ-1", "說明": "說明文字"}}],
      "學習表現": [{{"編碼": "tr-Ⅳ-1", "說明": "說明文字"}}],
      "出題概念": "評量學生能否……",
      "題型": "Simple multiple-choice",
      "題目": "問題一……",
      "答案": "A",
      "答案解析": "說明正答依據",
      "評分規準": []
    }}
  ],
  "題目": ["文本素材", "問題一……"],
  "正確解題分析": ["問題一答案與解析"],
  "chart_spec": {{...}}
}}
```

純文字題目不需 `chart_spec`。請只輸出 JSON，不要輸出其他文字。
"""

USER_PROMPT_TEMPLATE = """\
請根據以下條件生成一道 PISA Science + 108課綱自然科學素養導向題組：

## 指定條件

- **年級重心**：{grade}年級（{learning_stage}）
- **情境**：{context}
- **情境子類別**：{sub_context}
- **題型種類**：{set_type}
- **題型**：{q_type}
- **科學能力**：{science_competencies}
- **題目內容類型**：{content_type}
- **小題數量**：{sub_question_count}
{subquestion_config_lines}{lc_pool_lines}{lp_pool_lines}{param_instructions}{user_materials}
## 參考範例

{few_shot_examples}

## 重要提醒

1. 不要複製範例題目，必須原創。
2. 題組情境必須貼近指定的 PISA Science 情境與子類別。
3. 每道小題的 `學習內容` / `學習表現` 應優先使用上述指定代號；如需引入其他代號，仍以系統提供的課綱資料為限。
4. 整個題組應盡量讓每個指定的 `科學能力` 至少出現一次。
5. 題型為 Constructed response 時必須附完整評分規準；Complex multiple-choice 若有部分得分也需附規準。
6. `題目` 陣列：第一個元素放文本素材，其後每個元素放一道小題完整文字。
7. `正確解題分析` 陣列：每個元素對應一道小題答案與說明。
8. 只輸出 JSON 格式的結果。
"""

_CURRICULUM_EMPTY_NOTICE = "（課程綱要資料待研究人員補充至 data/natural_sciences/curriculum/）"


def _build_curriculum_section(
    content_text: str,
    performance_text: str,
    performance_intro: str = "",
) -> str:
    del performance_intro
    if not content_text and not performance_text:
        return _CURRICULUM_EMPTY_NOTICE
    parts = []
    if performance_text:
        parts.append("### 學習表現標準\n\n" + performance_text)
    if content_text:
        parts.append("### 學習內容與跨科概念\n\n" + content_text)
    return "\n\n".join(parts)


def build_system_prompt(
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
) -> str:
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
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
) -> tuple[str, list[Path]]:
    if rng is None:
        rng = random.Random()

    topic_override = user_topic.strip() if user_topic else ""
    content_type = params.題目內容類型 or "純文字"

    param_instruction_lines = []
    if not topic_override:
        for c in params.情境:
            instr = _INSTRUCTIONS.get("情境", {}).get(c.value)
            if instr:
                param_instruction_lines.append(f"  - **情境（{c.value}）補充**：{instr}")
    sub_instr = _INSTRUCTIONS.get("情境子類別", {}).get(params.情境子類別.value)
    if sub_instr:
        param_instruction_lines.append(
            f"  - **情境子類別（{params.情境子類別.value}）補充**：{sub_instr}"
        )
    for category, key in (
        ("題型種類", params.題型種類.value),
        ("題型", params.題型.value),
    ):
        instr = _INSTRUCTIONS.get(category, {}).get(key)
        if instr:
            param_instruction_lines.append(f"  - **{category}（{key}）補充**：{instr}")
    for c in params.科學能力:
        instr = _INSTRUCTIONS.get("科學能力", {}).get(c.value)
        if instr:
            param_instruction_lines.append(f"  - **科學能力（{c.value}）補充**：{instr}")
    content_type_instr = CONTENT_TYPE_INSTRUCTIONS.get(
        content_type,
        f"請將題目內容類型視為「{content_type}」，依此設計素材形式與題目，不得偏離此指定類型。",
    )
    param_instruction_lines.append(
        f"  - **題目內容類型（{content_type}）補充**：{content_type_instr}"
    )
    param_instructions = (
        "\n## 條件補充說明\n\n" + "\n".join(param_instruction_lines) + "\n"
        if param_instruction_lines else ""
    )

    example_groups = load_few_shot_example_groups(few_shot_dir, q_type=params.題型.value)
    all_image_paths: list[Path] = []
    if example_groups:
        sample_count = min(2, len(example_groups))
        selected_groups = rng.sample(example_groups, sample_count)
        selected = [rng.choice(group) for group in selected_groups]
        example_texts = []
        for i, ex in enumerate(selected, 1):
            q = ex.get("question", ex)
            example_texts.append(
                f"### 範例 {i}：{ex.get('description', '')}\n"
                f"```json\n{json.dumps(q, ensure_ascii=False, indent=2)}\n```"
            )
        few_shot_text = "\n\n".join(example_texts)
    else:
        few_shot_text = "（目前暫無範例，請根據指定條件自行設計。）"

    science_competencies = "、".join(c.value for c in params.科學能力)

    if params.學習內容_pool:
        lc_codes = "、".join(params.學習內容_pool)
        lc_detail_lines = "\n".join(
            f"  - {c}：{_LC_INSTRUCTIONS[c]}" for c in params.學習內容_pool if c in _LC_INSTRUCTIONS
        )
        lc_pool_lines = f"- **指定學習內容**：{lc_codes}\n{lc_detail_lines}\n"
    else:
        lc_pool_lines = ""

    if params.學習表現_pool:
        lp_codes = "、".join(params.學習表現_pool)
        lp_detail_lines = "\n".join(
            f"  - {c}：{_LP_INSTRUCTIONS[c]}" for c in params.學習表現_pool if c in _LP_INSTRUCTIONS
        )
        lp_pool_lines = f"- **指定學習表現**：{lp_codes}\n{lp_detail_lines}\n"
    else:
        lp_pool_lines = ""

    sq_config_parts: list[str] = []
    for i, cfg in enumerate(params.subquestion_configs, start=1):
        cfg_parts = []
        has_config = any((
            cfg.question_type, cfg.instruction, cfg.content_type,
            cfg.image_generation_mode, cfg.question_word_limit,
            cfg.option_word_limit, cfg.text_word_limit,
            cfg.learning_content, cfg.learning_performance,
        ))
        if cfg.question_type:
            cfg_parts.append(f"題型={cfg.question_type.value}")
        if cfg.instruction:
            cfg_parts.append(f"出題指示={cfg.instruction}")
        if cfg.learning_content:
            cfg_parts.append(f"學習內容={','.join(cfg.learning_content)}")
        if cfg.learning_performance:
            cfg_parts.append(f"學習表現={','.join(cfg.learning_performance)}")
        if has_config:
            cfg_parts.append(f"文本素材類型={cfg.content_type or params.題目內容類型 or '純文字'}")
            cfg_parts.append(f"圖片生成模式={cfg.image_generation_mode or image_generation_mode}")
        if cfg.question_word_limit:
            cfg_parts.append(f"題目字數上限={cfg.question_word_limit}")
        if cfg.option_word_limit:
            cfg_parts.append(f"選項字數上限={cfg.option_word_limit}")
        if cfg.text_word_limit:
            cfg_parts.append(f"文本字數上限={cfg.text_word_limit}")
        if cfg_parts:
            sq_config_parts.append(f"  - 第{i}小題：" + "，".join(cfg_parts))
            for code in cfg.learning_content:
                if code in _LC_INSTRUCTIONS:
                    sq_config_parts.append(f"    - {code}：{_LC_INSTRUCTIONS[code]}")
            for code in cfg.learning_performance:
                if code in _LP_INSTRUCTIONS:
                    sq_config_parts.append(f"    - {code}：{_LP_INSTRUCTIONS[code]}")
    if not sq_config_parts:
        if params.question_word_limit:
            sq_config_parts.append(f"  - 每道小題題目字數上限：{params.question_word_limit} 字")
        if params.option_word_limit:
            sq_config_parts.append(f"  - 每個選項字數上限：{params.option_word_limit} 字（限選擇題）")
    subquestion_config_lines = (
        "\n## 各小題配置\n\n" + "\n".join(sq_config_parts) + "\n"
        if sq_config_parts else ""
    )

    user_materials_parts = []
    if topic_override:
        user_materials_parts.append(
            "## 指定情境（請直接取代原本抽樣情境）\n\n"
            f"主題 / 議題：{topic_override}\n\n"
            "請以此主題 / 議題作為題組的真實科學情境與素材取材方向。"
        )
    if user_core_question:
        user_materials_parts.append(
            "## 指定核心問題（請逐字使用，不得修改）\n\n"
            f"核心問題：{user_core_question}"
        )
    if user_passage:
        user_materials_parts.append(
            "## 使用者指定素材\n\n"
            "**文本（請逐字使用，不得修改）**：\n\n"
            f"```\n{user_passage}\n```"
        )
    if user_options:
        labels = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛"]
        options_list = "\n".join(
            f"({labels[i] if i < len(labels) else str(i + 1)}) {v}"
            for i, v in enumerate(user_options)
        )
        user_materials_parts.append(
            ("## 使用者指定素材\n\n" if not user_passage else "")
            + "**選項或作答限制（請依序使用，不得更動文字）**：\n\n"
            + options_list
        )
    user_materials = (
        "\n" + "\n\n".join(user_materials_parts) + "\n"
        if user_materials_parts
        else ""
    )

    text = USER_PROMPT_TEMPLATE.format(
        grade=params.grade,
        learning_stage=_LEARNING_STAGE,
        context=topic_override or "、".join(c.value for c in params.情境),
        sub_context=params.情境子類別.value,
        set_type=params.題型種類.value,
        q_type=params.題型.value,
        science_competencies=science_competencies,
        content_type=content_type,
        sub_question_count=(
            str(params.sub_question_count)
            if params.sub_question_count else "3–7（由命題教師自行決定）"
        ),
        subquestion_config_lines=subquestion_config_lines,
        lc_pool_lines=lc_pool_lines,
        lp_pool_lines=lp_pool_lines,
        param_instructions=param_instructions,
        user_materials=user_materials,
        few_shot_examples=few_shot_text,
    )
    return text, all_image_paths
