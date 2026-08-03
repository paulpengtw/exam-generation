# ruff: noqa: E501
"""Assemble LLM prompts for PISA Science + 108課綱自然科學 question generation.

Figure routing: any `chart_spec` this module instructs the model to emit
must follow the rule in ``docs/figure-rendering-policy.md`` —
precise/quantitative statistical charts use ``render_mode: "chart"``
(matplotlib); structured data tables and semantic-overlay figures use
``render_mode: "html"`` (LLM-HTML + Playwright); realistic diagrams (實驗裝置圖,
模型圖, 標籤圖, 生物剖面, 地圖) use ``render_mode: "gpt_image"`` (OpenAI image
API). See ``CONTENT_TYPE_INSTRUCTIONS`` below for the per-``題目內容類型`` mapping.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from pathlib import Path

from src.common.batch_dedup import PriorScope, format_prior_scopes_block
from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.natural_sciences.curriculum_loader import (
    content_instructions,
    grade_to_learning_stage,
    load_learning_content,
    load_learning_performance,
    performance_instructions,
    relevant_cross_concepts,
)
from src.natural_sciences.data_loader import load_few_shot_example_groups
from src.natural_sciences.reporting_scale import (
    REPORTING_SCALE_LEVELS,
    REPORTING_SCALE_ORDER,
)
from src.natural_sciences.schema_loader import (
    build_instructions,
    load_grades,
    load_learning_stage,
    load_schemas,
)
from src.natural_sciences.schemas import SampledParams, SubQuestionConfig

_schemas = load_schemas()
_INSTRUCTIONS: dict[str, dict[str, str]] = build_instructions(_schemas)
_GRADES: list[int] = load_grades(_schemas)
_LEARNING_STAGE: str = load_learning_stage(_schemas)

_PERFORMANCE_DATA: dict = load_learning_performance()
_CONTENT_DATA: dict = load_learning_content()


def _stage_filtered_content(
    data: dict,
    learning_stage: str,
    lc_codes: Sequence[str] | None = None,
) -> dict:
    cross_concepts = data.get("跨科概念", [])
    if lc_codes:
        cross_concepts = relevant_cross_concepts(cross_concepts, lc_codes)
    return {
        "學習階段_to_grades": data.get("學習階段_to_grades", {}),
        "跨科概念": cross_concepts,
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
_STAGE_TO_GRADES: dict[str, list[int]] = _CONTENT_DATA.get("學習階段_to_grades", {})

# One representative (grade, LC code, LP code) per 學習階段 — used in prompt examples so
# the example JSON always matches the request's stage and never leaks codes from another stage.
_STAGE_EXAMPLE: dict[str, tuple[int, str, str]] = {
    "第二學習階段": (3, "INa-II-1", "ti-Ⅱ-1"),
    "第三學習階段": (5, "INa-III-1", "ti-Ⅲ-1"),
    "第四學習階段": (8, "Ka-Ⅳ-1", "tr-Ⅳ-1"),
    "第五學習階段": (11, "BDa-Ⅴa-1", "pa-Ⅴa-1"),
}


def _example_for_stage(stage: str) -> tuple[int, str, str]:
    """Return (example_grade, example_lc, example_lp) for the given 學習階段."""
    return _STAGE_EXAMPLE.get(stage, _STAGE_EXAMPLE["第四學習階段"])


def curriculum_texts(
    learning_stage: str,
    lc_codes: Sequence[str] | None = None,
) -> tuple[str, str]:
    """Return (content_text, performance_text) JSON blocks for one 學習階段.

    `lc_codes` narrows the injected 跨科概念 taxonomy to the concept groups
    related to the sampled 學習內容 codes; empty or unknown codes fall back
    to the full 48-entry taxonomy (issue #91).
    """
    content = json.dumps(
        _stage_filtered_content(_CONTENT_DATA, learning_stage, lc_codes=lc_codes),
        ensure_ascii=False,
        indent=2,
    )
    performance = json.dumps(
        _stage_filtered_performance(_PERFORMANCE_DATA, learning_stage),
        ensure_ascii=False,
        indent=2,
    )
    return content, performance
_LC_INSTRUCTIONS: dict[str, str] = content_instructions(_CONTENT_DATA)
_LP_INSTRUCTIONS: dict[str, str] = performance_instructions(_PERFORMANCE_DATA)
LC_INSTRUCTIONS = _LC_INSTRUCTIONS
LP_INSTRUCTIONS = _LP_INSTRUCTIONS

CONTENT_TYPE_INSTRUCTIONS: dict[str, str] = {
    "純文字": (
        "本題組必須只使用文字素材。不得輸出 `chart_spec` 或任何需要渲染成圖片的資料；"
        "題目、答案與解釋只能依據 `文本` 欄位中的文字、數據描述或實驗敘述。"
    ),
    "含圖片": (
        "本題組必須包含視覺式科學素材，例如實驗裝置圖、模型圖、流程圖、標籤圖、地圖或情境示意圖。"
        "請輸出 `chart_spec`，並依圖片家族選擇 `render_mode`："
        "\n"
        "- **寫實圖 / 實體示意** — 實驗裝置圖（含真實器材幾何）、生物剖面/標籤圖、"
        "岩石或天體照片式示意、需符合真實比例的模型圖，請使用 `render_mode: \"gpt_image\"`。"
        "\n"
        "- **結構化 / 抽象示意** — 流程圖、概念關係圖、電路連接圖、含語意標註的比較版面，"
        "請使用 `render_mode: \"html\"`。"
        "\n"
        "在 `description` 與 `data` 中完整描述版面與作答所需元素。"
        "（重要）圖片必須是作答的必要條件：至少一道小題的答案必須直接依賴圖片中才有的資訊，無法僅憑文本回答。"
        "設計時請先確定「移除圖片後此題是否仍可作答」——若可以，請重新設計圖片，使其承載文本中未涵蓋的關鍵資訊"
        "（例如實驗裝置的連接方式、模型圖的標示數據、流程圖的條件分支）。"
        f"（示意圖聲明）圖片為示意用途，非完全等比例繪製；若使用 `render_mode: \"html\"`，"
        f"請在 `chart_spec.description` 中要求下游 HTML 產生器將「{IMAGE_DISCLAIMER}」"
        f"以 caption 呈現在圖片下緣或版面空白處。"
    ),
    "graphs/charts/tables": (
        "本題組必須包含數據圖表或表格。統計圖請使用 `render_mode: \"chart\"`；"
        "實驗數據表、分類表或多欄比較表請使用 `render_mode: \"html\"`，並在 `data` 中提供完整資料。"
        "（重要）圖表/表格必須是作答的必要條件：至少一道小題須讀取圖表中的具體數值、趨勢或分類才能回答，"
        "且這些數值不得在 `文本` 欄位中重複列出。若移除圖表後題目仍可回答，需重新設計使數據只存在於圖表中。"
        f"（示意圖聲明）圖表軸線、格線與座標比例僅為示意，非完全等比例繪製；"
        f"請在 `chart_spec.description` 或圖表 caption 加註「{IMAGE_DISCLAIMER}」，"
        "但圖表中的數值、標籤與分類仍必須完全對應 `data` 內容。"
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
- `年級`：{grade_names}其中之一
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
      "年級": {example_grade},
      "科目": ["自然科學"],
      "科學能力": ["能力一：以科學的角度解釋現象"],
      "學習內容": [{{"編碼": "{example_lc}", "說明": "說明文字"}}],
      "學習表現": [{{"編碼": "{example_lp}", "說明": "說明文字"}}],
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

### 圖片必要性原則
- 凡輸出非 null 的 `chart_spec`，該圖片、圖表或表格必須承載至少一道小題作答所必需的資訊。
- 至少一道小題的答案必須直接依賴 `chart_spec` 中才有的具體資訊，不能只靠 `文本` 欄位回答。
- `chart_spec` 中承載的關鍵數據、標示、連接方式、條件分支或分類不得在 `文本` 欄位中重複列出。
- 若移除圖片、圖表或表格後題目仍可回答，請重新設計 `chart_spec`，使必要資訊只存在於視覺素材中。

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
{subquestion_config_lines}{lc_pool_lines}{lp_pool_lines}{param_instructions}{reporting_scale_section}{user_materials}
## 參考範例

{few_shot_examples}

## 重要提醒

1. 不要複製範例題目，必須原創。
2. 題組情境必須貼近指定的 PISA Science 情境與子類別。
3. 每道小題的 `學習內容` / `學習表現` 必須使用指定學習階段的代號；不得使用其他學習階段的學習內容或學習表現代號。
4. 整個題組應盡量讓每個指定的 `科學能力` 至少出現一次。
5. 題型為 Constructed response 時必須附完整評分規準；Complex multiple-choice 若有部分得分也需附規準。
6. `題目` 陣列：第一個元素放文本素材，其後每個元素放一道小題完整文字。
7. `正確解題分析` 陣列：每個元素對應一道小題答案與說明。
8. 只輸出 JSON 格式的結果。
9. 若題組含圖片（`chart_spec` 非 null），必須確認：至少一道小題的答案無法在沒有圖片的情況下得出；且 `chart_spec` 中承載的關鍵數據/資訊不得在 `文本` 欄位中重複說明。
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


def _grades_for(grades: list[int] | None, learning_stage: str | None) -> list[int]:
    """Grade list for system prompts: explicit grades win, then the stage's
    own grades (學習階段_to_grades), then the schema_meta default."""
    if grades is not None:
        return grades
    if learning_stage is not None:
        return _STAGE_TO_GRADES.get(learning_stage, _GRADES)
    return _GRADES


def build_system_prompt(
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
) -> str:
    g = _grades_for(grades, learning_stage)
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    grade_names = "、".join(f"{x}年級" for x in g)
    c_text = content_text if content_text is not None else _CONTENT_TEXT
    p_text = performance_text if performance_text is not None else _PERFORMANCE_TEXT
    curriculum_section = _build_curriculum_section(c_text, p_text)
    example_grade, example_lc, example_lp = _example_for_stage(stage)
    return SYSTEM_PROMPT_TEMPLATE.format(
        learning_stage=stage,
        grade_names=grade_names,
        curriculum_section=curriculum_section,
        example_grade=example_grade,
        example_lc=example_lc,
        example_lp=example_lp,
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
    disable_reference_fewshot: bool = False,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> tuple[str, list[Path]]:
    if rng is None:
        rng = random.Random(params.seed)

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

    # Issue #280: 題組-level Reporting Scale block (verbatim PISA descriptor; no all-eight ref).
    rs_level = params.reporting_scale
    reporting_scale_section = (
        "\n## 目標報告等級（Reporting Scale）\n\n"
        f"本題組的命題目標等級為 **{rs_level}**。"
        "請確保題組整體認知需求符合以下 PISA Science 等級描述：\n\n"
        f"{REPORTING_SCALE_LEVELS[rs_level]}\n"
        if rs_level
        else ""
    )

    example_groups = (
        []
        if disable_reference_fewshot
        else load_few_shot_example_groups(few_shot_dir, q_type=params.題型.value)
    )
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
        has_structural_config = any((
            cfg.question_type, cfg.instruction, cfg.content_type,
            cfg.image_generation_mode, cfg.question_word_limit,
            cfg.option_word_limit,
            cfg.learning_content, cfg.learning_performance,
            cfg.reporting_scale,
        ))
        if cfg.question_type:
            cfg_parts.append(f"題型={cfg.question_type.value}")
        if cfg.instruction:
            cfg_parts.append(f"出題指示={cfg.instruction}")
        if cfg.learning_content:
            cfg_parts.append(f"學習內容={','.join(cfg.learning_content)}")
        if cfg.learning_performance:
            cfg_parts.append(f"學習表現={','.join(cfg.learning_performance)}")
        if cfg.reporting_scale:
            cfg_parts.append(f"目標報告等級={cfg.reporting_scale}")
        if has_structural_config:
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

    if prior_scopes:
        prior_scopes_text = format_prior_scopes_block(prior_scopes)
        user_materials = (user_materials or "\n") + "\n" + prior_scopes_text

    text = USER_PROMPT_TEMPLATE.format(
        grade=params.grade,
        learning_stage=grade_to_learning_stage(params.grade),
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
        reporting_scale_section=reporting_scale_section,
        user_materials=user_materials,
        few_shot_examples=few_shot_text,
    )
    return text, all_image_paths


_TEXT_OUTPUT_FORMAT_BLOCK = """\
## 輸出格式
你必須輸出合法 JSON 物件，只包含以下欄位：

{{
  "核心問題": "本題組的核心問題",
  "文本": "完整科學情境素材",
  "取材來源": ["來源一"],
  "subquestions": [
    {{
      "序號": 1,
      "題型": "Simple multiple-choice",
      "出題概念": "一句話說明此小題要評量的能力"
    }}
  ]
}}

`subquestions` 陣列為各小題的出題規劃，每筆只需序號、題型與一句出題概念說明；
詳細題目與答案將由後續子題產生器負責。請只輸出 JSON，不要輸出其他文字。
"""

_FULL_OUTPUT_FORMAT_BLOCK = """\
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
      "年級": {example_grade},
      "科目": ["自然科學"],
      "科學能力": ["能力一：以科學的角度解釋現象"],
      "學習內容": [{{"編碼": "{example_lc}", "說明": "說明文字"}}],
      "學習表現": [{{"編碼": "{example_lp}", "說明": "說明文字"}}],
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

TEXT_SYSTEM_PROMPT_TEMPLATE = SYSTEM_PROMPT_TEMPLATE.replace(
    _FULL_OUTPUT_FORMAT_BLOCK,
    _TEXT_OUTPUT_FORMAT_BLOCK,
)

TEXT_USER_PROMPT_TEMPLATE = USER_PROMPT_TEMPLATE.replace(
    """\
6. `題目` 陣列：第一個元素放文本素材，其後每個元素放一道小題完整文字。
7. `正確解題分析` 陣列：每個元素對應一道小題答案與說明。
8. 只輸出 JSON 格式的結果。
""",
    """\
6. `subquestions` 陣列中每筆只需提供 `序號`、`題型` 與 `出題概念`；不要輸出題目文字、答案或評分規準。
7. 只輸出 JSON 格式的結果。
""",
)


def build_text_system_prompt(
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
) -> str:
    g = _grades_for(grades, learning_stage)
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    grade_names = "、".join(f"{x}年級" for x in g)
    c_text = content_text if content_text is not None else _CONTENT_TEXT
    p_text = performance_text if performance_text is not None else _PERFORMANCE_TEXT
    curriculum_section = _build_curriculum_section(c_text, p_text)
    example_grade, example_lc, example_lp = _example_for_stage(stage)
    return TEXT_SYSTEM_PROMPT_TEMPLATE.format(
        learning_stage=stage,
        grade_names=grade_names,
        curriculum_section=curriculum_section,
        example_grade=example_grade,
        example_lc=example_lc,
        example_lp=example_lp,
    )


def build_text_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    disable_reference_fewshot: bool = False,
    prior_scopes: Sequence[PriorScope] | None = None,
    balanced_batch: bool = False,
) -> tuple[str, list[Path]]:
    text, image_paths = build_user_prompt(
        params=params,
        few_shot_dir=few_shot_dir,
        rng=rng,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        disable_reference_fewshot=disable_reference_fewshot,
        prior_scopes=prior_scopes,
    )
    text = text.replace(
        """\
6. `題目` 陣列：第一個元素放文本素材，其後每個元素放一道小題完整文字。
7. `正確解題分析` 陣列：每個元素對應一道小題答案與說明。
8. 只輸出 JSON 格式的結果。
""",
        """\
6. `subquestions` 陣列中每筆只需提供 `序號`、`題型` 與 `出題概念`；不要輸出題目文字、答案或評分規準。
7. 只輸出 JSON 格式的結果。
""",
    )
    if balanced_batch:
        text = text.replace(
            "\n## 參考範例\n",
            "\n## 出題模式：均衡\n\n"
            "本題與同批次其他題目的 題型 與 取材角度 請盡量平均分散，"
            "並避開「已生成題目（請避免相似範圍）」中已列出的取材範圍，"
            "不要重複相近主題。\n\n"
            "## 參考範例\n",
            1,
        )
    if params.text_word_limit:
        text = text.replace(
            "\n## 參考範例\n",
            f"\n- **文本字數上限**：{params.text_word_limit} 字\n\n## 參考範例\n",
            1,
        )
    return text, image_paths


def build_subquestion_system_prompt(
    learning_stage: str,
    content_text: str | None = None,
    performance_text: str | None = None,
) -> str:
    c_text = content_text if content_text is not None else _CONTENT_TEXT
    p_text = performance_text if performance_text is not None else _PERFORMANCE_TEXT
    curriculum_section = _build_curriculum_section(c_text, p_text)
    example_grade, example_lc, example_lp = _example_for_stage(learning_stage)
    return f"""\
你是一位108課綱自然科學領域子題命題教師。你會收到一份共用科學文本，以及一道小題的出題規劃；請只根據該文本與規劃撰寫 exactly one SubQuestion JSON。

目前學習階段：{learning_stage}

輸出必須是合法 JSON 物件，格式如下：

```json
{{
  "序號": 1,
  "年級": {example_grade},
  "科目": ["自然科學"],
  "科學能力": ["能力一：以科學的角度解釋現象"],
  "核心素養": [],
  "學習內容": [{{"編碼": "{example_lc}", "說明": "說明文字"}}],
  "學習表現": [{{"編碼": "{example_lp}", "說明": "說明文字"}}],
  "出題概念": "評量學生能否……",
  "reporting_scale": "3",
  "題型": "Simple multiple-choice",
  "題目": "完整題目文字（含選項）",
  "答案": "A",
  "答案解析": "說明正答依據",
  "評分規準": [],
  "誘答分析": {{"A": "...", "B": "正確答案：...", "C": "...", "D": "..."}}
}}
```

## 誘答分析的設計

`誘答分析` 是一個以「選項標籤」為鍵、對應誘答描述為值的 JSON dict：

- **Simple / Complex multiple-choice**：鍵為 `"A"` / `"B"` / `"C"` / `"D"`（Complex 的複選題請對每個獨立敘述使用 `"A是"` / `"A非"` 等鍵，或直接沿用 A/B/C/D）。錯誤選項描述其針對的科學迷思（概念混淆 / 誤讀證據 / 過度推論 / 忽略前提 …），正確選項的值為一句 「正確答案：…」。
- **Constructed response**：可留空 `{{}}`，或提供 `{{"常見錯誤": "…"}}` 描述一項最常見的科學迷思。

範例：

```json
"誘答分析": {{
  "A": "誤讀證據：把長期趨勢誤解為短期波動。",
  "B": "正確答案：能量守恆造成振幅衰減。",
  "C": "概念混淆：把慣性誤讀為摩擦力效應。",
  "D": "過度推論：從單一實驗推論到所有系統。"
}}
```

## 評分規準
- Simple multiple-choice：正確代號 2，錯誤代號 0。
- Complex multiple-choice：通常採整組計分；全對代號 2，部分正確可給 1，錯誤代號 0，未作答 0X。
- Constructed response：必須附 `評分規準`，使用 2 / 1 / 0 / 0X，並提供學生作答實例。

## 課程綱要參考

{curriculum_section}

請只輸出 JSON，不要輸出其他文字。
"""


def build_subquestion_user_prompt(
    核心問題: str,
    文本: str,
    取材來源: list[str],
    sq_plan: dict,
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
    image_generation_mode: str = "html",
    cfg: "SubQuestionConfig | None" = None,
    disable_reference_fewshot: bool = False,
) -> tuple[str, list[Path]]:
    del image_generation_mode
    if rng is None:
        rng = random.Random(params.seed)

    q_type = (
        cfg.question_type.value
        if cfg is not None and cfg.question_type is not None
        else sq_plan["題型"]
    )
    example_groups = (
        []
        if disable_reference_fewshot
        else load_few_shot_example_groups(few_shot_dir, q_type=q_type)
    )
    all_image_paths: list[Path] = []
    if example_groups:
        selected_group = rng.choice(example_groups)
        ex = rng.choice(selected_group)
        q = ex.get("question", ex)
        if isinstance(q, dict) and q.get("subquestions"):
            matching = [
                sq for sq in q["subquestions"]
                if isinstance(sq, dict) and sq.get("題型") == q_type
            ]
            q = matching[0] if matching else q["subquestions"][0]
        ex_images: list[dict] = ex.get("images", [])
        img_notes = ""
        if ex_images:
            for j, img in enumerate(ex_images, 1):
                caption = img.get("caption", "")
                label = f"圖{j}" + (f"（{caption}）" if caption else "")
                img_notes += f"\n<!-- {label} 附於此範例後 -->"
                all_image_paths.append(Path(img["path"]))
        few_shot_text = (
            f"### 範例 1：{ex.get('description', '')}\n"
            f"```json\n{json.dumps(q, ensure_ascii=False, indent=2)}\n```{img_notes}"
        )
    else:
        few_shot_text = "（目前暫無範例，請根據指定條件自行設計。）"

    science_competencies = "、".join(c.value for c in params.科學能力)

    lc_explicit = bool(cfg and cfg.learning_content)
    lc_for_slot = cfg.learning_content if lc_explicit else params.學習內容_pool
    if lc_for_slot:
        lc_codes = "、".join(lc_for_slot)
        lc_detail_lines = "\n".join(
            f"  - {c}：{_LC_INSTRUCTIONS[c]}" for c in lc_for_slot if c in _LC_INSTRUCTIONS
        )
        if lc_explicit:
            lc_pool_lines = f"- **指定學習內容（本小題務必使用下列指定學習內容，不得替換或新增）**：\n{lc_codes}\n{lc_detail_lines}\n"
        else:
            lc_pool_lines = f"- **指定學習內容**：{lc_codes}\n{lc_detail_lines}\n"
    else:
        lc_pool_lines = ""

    lp_explicit = bool(cfg and cfg.learning_performance)
    lp_for_slot = cfg.learning_performance if lp_explicit else params.學習表現_pool
    if lp_for_slot:
        lp_codes = "、".join(lp_for_slot)
        lp_detail_lines = "\n".join(
            f"  - {c}：{_LP_INSTRUCTIONS[c]}" for c in lp_for_slot if c in _LP_INSTRUCTIONS
        )
        if lp_explicit:
            lp_pool_lines = f"- **指定學習表現（本小題務必使用下列指定學習表現，不得替換或新增）**：\n{lp_codes}\n{lp_detail_lines}\n"
        else:
            lp_pool_lines = f"- **指定學習表現**：{lp_codes}\n{lp_detail_lines}\n"
    else:
        lp_pool_lines = ""

    reporting_scale = cfg.reporting_scale if cfg and cfg.reporting_scale else None
    reporting_scale_target_line = (
        f"- **目標報告等級**：{reporting_scale}（{REPORTING_SCALE_LEVELS[reporting_scale]}）\n"
        if reporting_scale
        else ""
    )
    reporting_scale_reference = (
        "\n## PISA Science 報告等級（Reporting Scale）參考\n\n"
        "以下為 PISA Science 各等級之能力描述，供命題時參考各等級之認知需求差異：\n\n"
        + "\n".join(
            f"- **等級 {level}**：{REPORTING_SCALE_LEVELS[level]}"
            for level in REPORTING_SCALE_ORDER
        )
        + "\n"
        if reporting_scale
        else ""
    )

    source_text = json.dumps(取材來源, ensure_ascii=False, indent=2)
    config_parts = [f"題型={q_type}"]
    if cfg is not None and cfg.instruction:
        config_parts.append(f"出題指示={cfg.instruction}")
    if cfg is not None and cfg.learning_content:
        config_parts.append(f"學習內容={','.join(cfg.learning_content)}")
    if cfg is not None and cfg.learning_performance:
        config_parts.append(f"學習表現={','.join(cfg.learning_performance)}")
    question_limit = (
        cfg.question_word_limit
        if cfg is not None and cfg.question_word_limit
        else params.question_word_limit
    )
    option_limit = (
        cfg.option_word_limit
        if cfg is not None and cfg.option_word_limit
        else params.option_word_limit
    )
    if question_limit:
        config_parts.append(f"題目字數上限={question_limit}")
    if option_limit:
        config_parts.append(f"選項字數上限={option_limit}")
    subquestion_config_section = (
        "## 各小題配置\n\n"
        f"  - 第{sq_plan.get('序號', 1)}小題：" + "，".join(config_parts)
    )
    return f"""\
請根據以下共用素材與小題規劃，生成一道 PISA Science + 108課綱自然科學小題：

## 共用素材

- **核心問題**：{核心問題}
- **文本**：

```
{文本}
```

- **取材來源**：

```json
{source_text}
```

## 本小題規劃

- **序號**：{sq_plan.get("序號", 1)}
- **題型**：{q_type}
- **出題概念**：{sq_plan.get("出題概念", "")}

{subquestion_config_section}

## 指定條件

- **年級重心**：{params.grade}年級（{grade_to_learning_stage(params.grade)}）
- **情境**：{"、".join(c.value for c in params.情境)}
- **情境子類別**：{params.情境子類別.value}
- **科學能力**：{science_competencies}
{lc_pool_lines}{lp_pool_lines}{reporting_scale_target_line}{reporting_scale_reference}
## 參考範例

{few_shot_text}

## 重要提醒

1. 只撰寫序號 {sq_plan.get("序號", 1)} 的一道小題。
2. 小題必須能依據共用文本作答，不要引入無法由文本支持的新情境。
3. `學習內容` / `學習表現` 必須使用指定學習階段的代號；不得使用其他學習階段的學習內容或學習表現代號。
4. **誘答分析**：本小題若為 `Simple multiple-choice` 或 `Complex multiple-choice`，`誘答分析` **必須**同時涵蓋題目所有選項標籤（預設 A/B/C/D）；正確選項填「正確答案：…」，其餘選項描述其針對的科學迷思。若為 `Constructed response`，可留空 `{{}}` 或使用 `{{"常見錯誤": "..."}}` 描述一項最常見的科學迷思。
5. 請只輸出一道小題的 JSON，不要輸出其他文字。
""", all_image_paths
