"""Assemble LLM prompts with curriculum context and few-shot examples.

Figure routing: any `chart_spec` this module instructs the model to emit must
follow the rule in ``docs/figure-rendering-policy.md`` — precise/quantitative
statistical charts use ``render_mode: "chart"`` (matplotlib); structured or
semantic illustrative figures (menus, scenario cards, tables with annotations)
use ``render_mode: "html"`` (LLM-HTML + Playwright); realistic diagrams (maps,
lab apparatus, biology, real-world-proportion geometry) use
``render_mode: "gpt_image"`` (OpenAI image API). See ``CONTENT_TYPE_INSTRUCTIONS``
below for the per-``題目內容類型`` mapping.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from pathlib import Path

from src.common.batch_dedup import PriorScope, format_prior_scopes_block
from src.common.core_competency_loader import (
    competency_instructions,
    load_core_competencies,
    stage_code_for,
)
from src.common.curriculum_loader import (
    content_instructions,
    load_learning_content,
    load_learning_performance,
    load_performance_intro,
    performance_instructions,
)
from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.curriculum_context import (
    CurriculumContext,
    build_curriculum_section,
)
from src.data_loader import load_few_shot_examples
from src.schema_loader import build_instructions, load_grades, load_learning_stage, load_schemas
from src.schemas import SampledParams

_schemas = load_schemas()
_INSTRUCTIONS: dict[str, dict[str, str]] = build_instructions(_schemas)
_GRADES: list[int] = load_grades(_schemas)
_LEARNING_STAGE: str = load_learning_stage(_schemas)

_MATH_DATA_DIR = Path(__file__).parent.parent / "data" / "math" / "curriculum"
_CC_DATA: dict = load_core_competencies(_MATH_DATA_DIR / "core_competencies.json")
_CC_INSTRUCTIONS: dict[str, str] = competency_instructions(_CC_DATA)
_STAGE_CODE: str = stage_code_for(_CC_DATA, _LEARNING_STAGE)

_PERFORMANCE_DATA: dict = load_learning_performance(_MATH_DATA_DIR)
_CONTENT_DATA: dict = load_learning_content(_MATH_DATA_DIR)
_PERFORMANCE_INTRO: str = load_performance_intro(_MATH_DATA_DIR)

_PERFORMANCE_TEXT: str = (
    json.dumps(_PERFORMANCE_DATA, ensure_ascii=False, indent=2)
    if _PERFORMANCE_DATA.get("學習表現")
    else ""
)
_CONTENT_TEXT: str = (
    json.dumps(_CONTENT_DATA, ensure_ascii=False, indent=2)
    if _CONTENT_DATA.get("學習內容")
    else ""
)
_LC_INSTRUCTIONS: dict[str, str] = content_instructions(_CONTENT_DATA)
_LP_INSTRUCTIONS: dict[str, str] = performance_instructions(_PERFORMANCE_DATA)


CONTENT_TYPE_INSTRUCTIONS: dict[str, str] = {
    "純文字": (
        "本題目必須只使用純文字描述。不得輸出 `chart_spec`、`image_spec` 或任何需要渲染成圖片的資料；"
        "題目與解題分析只能依據文字內容。"
    ),
    "含圖片": (
        "本題目必須包含圖片或視覺示意素材（幾何圖形、示意圖、版面等）。"
        "請輸出 `chart_spec`，並依圖片家族選擇 `render_mode`："
        "\n"
        "- **寫實圖 / 真實比例幾何** — 需符合真實比例的幾何、示意情境圖、需要接近寫實筆觸的插圖，"
        "請使用 `render_mode: \"gpt_image\"`。"
        "\n"
        "- **結構化 / 語意版面** — 版面型的說明圖、附語意標註或表格化的比較，"
        "請使用 `render_mode: \"html\"`。"
        "\n"
        "在 `description` 與 `data` 中完整描述版面與內容。"
        f"（示意圖聲明）本題所有圖片皆為示意用途，非完全等比例繪製；"
        f"若使用 `render_mode: \"html\"`，請在 `chart_spec.description` 中明確要求下游 HTML 產生器"
        f"將「{IMAGE_DISCLAIMER}」以 caption 形式呈現在圖片下緣或版面空白處。"
    ),
    "graphs/charts/tables": (
        "本題目必須包含圖表或表格素材。統計圖（直方圖、折線圖、圓餅圖等）請使用 `render_mode: \"chart\"`；"
        "表格或複合資料表請使用 `render_mode: \"html\"`，並在 `data` 中提供完整欄列資料。"
        f"（示意圖聲明）圖表軸線、格線與座標比例僅為示意，非完全等比例繪製；"
        f"請在 `chart_spec.description` 或圖表 caption 中加註「{IMAGE_DISCLAIMER}」，"
        "但圖表中的數值、標籤與分類仍必須完全對應 `data` 內容。"
    ),
    "customized": (
        "本題目內容類型由使用者自訂，請依照使用者提供的素材與指示生成題目。"
    ),
}

DIFFICULTY_INSTRUCTIONS: dict[str, str] = _INSTRUCTIONS.get("難度", {})


SYSTEM_PROMPT_TEMPLATE = """\
你是一位資深的台灣國中數學命題教師，專門為{learning_stage}（{grade_names}）的學生設計考試題目。
**本題庫專為{learning_stage}設計：所有 `核心素養` 代號必須使用 `數-{stage_code}-*` 開頭（如 數-{stage_code}-A2、數-{stage_code}-C3），不得使用其他學習階段的代號。**

## 命題原則

1. 題目必須符合十二年國民基本教育數學領域課程綱要的學習內容。
2. 題目應確保 {grade_range} 學生具備足夠先備知識可以作答，但也要有適當的挑戰性。
3. 你必須了解國小（1-6年級）的學習內容作為先備知識基礎，也要了解高中（10-12年級）的學習內容以確保不超出範圍。
4. 選項設計應包含合理的誘答選項，針對學生常見的錯誤概念。
5. 解題分析必須完整、正確，包含逐步推導過程。
6. 題目可選擇填入 `核心素養`（代號清單）、`學習表現`（編碼+說明）、`題目內容類型`、`出題概念`（一句話評量目標），協助課綱對齊；保留math單題（非題組）輸出結構。

## 誘答分析的設計

`誘答分析` 是一個以「選項標籤」為鍵、對應誘答描述為值的 JSON dict：

- **選擇題**：鍵為 `"A"` / `"B"` / `"C"` / `"D"`。錯誤選項描述其針對的認知陷阱（誤讀題意 / 概念混淆 / 部分正確誘騙 / 過度推論 …），正確選項的值為一句 「正確答案：…」。
- **是非題**：鍵為 `"是"` / `"非"`。正確項填「正確答案：…」，錯誤項描述學生常見誤解。
- **建構反應題（封閉式 / 開放式）**：可留空 `{{}}`，或提供 `{{"常見錯誤": "…"}}` 描述一項最常見的錯誤。

範例：

```json
"誘答分析": {{
  "A": "誤讀題意：將『加權平均』誤算為算術平均。",
  "B": "正確答案：74 分鐘（依人數比計算加權平均）。",
  "C": "概念混淆：把加權係數誤用為比例分子的相反值。",
  "D": "過度推論：只取最大群組的平均值代表整體。"
}}
```

## 課程綱要參考

{curriculum_section}

## 輸出格式

你必須輸出一個合法的 JSON 物件，格式如下：

```json
{{
  "情境": ["（可為多個選項）"],
  "題型種類": "（從指定選項中選一個）",
  "題型": "（從指定選項中選一個）",
  "數學思考": ["（1-3個）"],
  "學習內容": [
    {{"編碼": "X-Y-Z", "說明": "..."}}
  ],
  "學習表現": [
    {{"編碼": "n-IV-1", "說明": "..."}}
  ],
  "核心素養": ["數-{stage_code}-A2"],
  "題目內容類型": "純文字 / 含圖片 / graphs/charts/tables / customized",
  "出題概念": "評量學生能否……（一句話）",
  "誘答分析": {{"A": "...", "B": "正確答案：...", "C": "...", "D": "..."}},
  "題目": ["題目文字", "選項或子題..."],
  "正確解題分析": ["步驟一...", "步驟二..."],
  "chart_spec": {{...}}
}}
```

如果題目需要圖表或圖片，請在 JSON 中加入 `chart_spec` 欄位，依需求選擇以下兩種模式之一：

**統計圖表（`render_mode: "chart"`）** — 適用於有明確數值資料的圖表：
```json
{{
  "render_mode": "chart",
  "chart_type": "histogram" | "boxplot" | "line_chart" | "pie_chart",
  "title": "圖表標題",
  "data": {{ ... }},
  "labels": {{"x": "x軸標籤", "y": "y軸標籤"}}
}}
```

**HTML 示意圖（`render_mode: "html"`）** — 適用於幾何圖形、示意圖、菜單、比較表格、情境圖等一切無法用統計圖表表達的視覺內容：
```json
{{
  "render_mode": "html",
  "description": "詳細描述圖片內容，包含形狀、尺寸、標籤、顏色、文字等，讓 AI 能正確生成圖片。請在 description 結尾指示下游 HTML 產生器在圖片下緣加註 caption：「{image_disclaimer}」。",
  "title": "圖片標題（選填）",
  "data": {{ "key": "value" }}
}}
```

`render_mode: "html"` 的 `description` 請盡量詳細。
所有 `render_mode: "html"` 或 `render_mode: "chart"` 的圖片皆為示意用途、非完全等比例繪製，
因此 `description` 中務必加入 caption 指示「{image_disclaimer}」；文字題不需要 `chart_spec` 欄位。

請只輸出 JSON，不要輸出其他文字。
"""

USER_PROMPT_TEMPLATE = """\
請根據以下條件生成一道數學考試題目：

## 指定條件

- **年級重心**：{grade}年級
- **科目焦點**：{subject_filter}
- **情境**（題目輸出的 `情境` 欄位必須完全使用以下這幾個列舉值）：{context}
- **題型種類**：{set_type}
- **題型**：{q_type}
- **數學思考**：{thinking}
- **題目內容類型**：{content_type}
- **核心素養（限定使用）**：{core_competencies}
- **必須涵蓋的學習內容**：
{content_list}
{lp_pool_lines}{param_instructions}{difficulty_section}
## 題目風格

{style_instruction}
{user_materials}{prior_scopes_block}
## 參考範例

以下是符合類似風格的範例題目，供你參考格式和難度水準：

{few_shot_examples}

## 重要提醒

1. 不要複製範例題目，必須原創。
2. 確保答案正確，解題過程完整。
3. 學習內容可以跨年級整合（{grade_range}範圍內），但核心考點應以指定的學習內容為主。
4. 選項的誘答設計應針對常見錯誤概念。
5. 題目的 `核心素養` 欄位**必須只從指定條件中的核心素養代號選擇**。
6. 題目的 `情境` 欄位**必須完全使用「指定條件 → 情境」中列出的列舉值之一**（合法值僅為：個人 / 社會時事 / 科學 / 職業 / 建築與藝術 / 數學文字情境），不可改寫成題目主題、場景描述、或情境名稱。題目主題若需呈現，請放入題目內文，而不是 `情境` 欄位。
7. 維持單題輸出結構（不是題組）：不要產生 `subquestions`、`核心問題`、`文本`、`評分規準` 等題組欄位。
8. 只輸出 JSON 格式的結果。
9. **誘答分析**：本題若為 選擇題 或 是非題，`誘答分析` **必須**同時涵蓋所有選項標籤（選擇題的 A/B/C/D 或是非題的「是」/「非」）；正確選項填「正確答案：…」，其餘選項描述其針對的錯誤概念。若為 封閉式 / 開放式建構反應題，`誘答分析` 可為空 `{{}}` 或使用 `{{"常見錯誤": "..."}}` 描述一項最常見錯誤。
"""

_CURRICULUM_EMPTY_NOTICE = "（課程綱要資料待研究人員補充至 data/math/curriculum/）"


def _build_curriculum_section(
    content_text: str,
    performance_text: str,
    performance_intro: str = "",
) -> str:
    """Internal helper — delegates to the canonical public function."""
    ctx = CurriculumContext(
        content_text=content_text,
        performance_text=performance_text,
        intro_text=performance_intro,
    )
    return build_curriculum_section(ctx)


def build_system_prompt(
    curriculum_json: str | None = None,
    performance_json: str | None = None,
    intro_text: str | None = None,
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    *,
    curriculum_context: CurriculumContext | None = None,
) -> str:
    """Build the system prompt with full curriculum context.

    All args are optional; defaults use the materialized math curriculum data.
    Positional args are still accepted for backward compat with old callers
    that passed pre-serialized text.

    When *curriculum_context* is supplied it takes priority over all three
    curriculum positional args (``curriculum_json``, ``performance_json``,
    ``intro_text``).
    """
    g = grades if grades is not None else _GRADES
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    grade_range = f"{min(g)}-{max(g)}年級"
    grade_names = "、".join(f"{x}年級" for x in g)
    if curriculum_context is not None:
        c_text = curriculum_context.content_text
        p_text = curriculum_context.performance_text
        p_intro = curriculum_context.intro_text
    else:
        c_text = curriculum_json if curriculum_json is not None else _CONTENT_TEXT
        p_text = performance_json if performance_json is not None else _PERFORMANCE_TEXT
        p_intro = intro_text if intro_text is not None else _PERFORMANCE_INTRO
    curriculum_section = _build_curriculum_section(c_text, p_text, p_intro)
    sc = stage_code_for(_CC_DATA, stage)
    return SYSTEM_PROMPT_TEMPLATE.format(
        learning_stage=stage,
        grade_range=grade_range,
        grade_names=grade_names,
        curriculum_section=curriculum_section,
        stage_code=sc,
        image_disclaimer=IMAGE_DISCLAIMER,
    )


def build_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
    *,
    user_topic: str = "",
    user_passage: str = "",
    user_options: list[str] | None = None,
    user_core_question: str = "",
    prior_scopes: "Sequence[PriorScope] | None" = None,
) -> tuple[str, list[Path]]:
    """Build the user prompt with sampled parameters and few-shot examples.

    Returns (prompt_text, few_shot_image_paths). Math currently returns an
    empty image list because the math few-shot loader is JSON-based.
    """
    if rng is None:
        rng = random.Random(params.seed)

    # Format learning content list
    content_lines = []
    for item in params.學習內容:
        content_lines.append(f"  - {item.編碼}：{item.說明}")
    content_list = "\n".join(content_lines) if content_lines else "  - （無）"

    # Format math thinking
    thinking = "、".join(t.value for t in params.數學思考)

    # 學習表現 detail block
    if params.學習表現:
        lp_detail_lines = "\n".join(
            f"  - {item.編碼}：{item.說明}" for item in params.學習表現
        )
        lp_pool_lines = f"- **指定學習表現**：\n{lp_detail_lines}\n"
    else:
        lp_pool_lines = ""

    # core competency codes line
    core_competencies = "、".join(params.核心素養) if params.核心素養 else "（未指定）"
    content_type = params.題目內容類型 or "純文字"
    subject_filter = params.subject_filter or "（未指定，題目可跨數學各領域）"

    # Per-param instructions
    param_instruction_lines = []
    for c in params.情境:
        instr = _INSTRUCTIONS.get("情境", {}).get(c.value)
        if instr:
            param_instruction_lines.append(f"  - **情境（{c.value}）補充**：{instr}")
    for category, key in (
        ("題型種類", params.題型種類.value),
        ("題型", params.題型.value),
    ):
        instr = _INSTRUCTIONS.get(category, {}).get(key)
        if instr:
            param_instruction_lines.append(f"  - **{category}（{key}）補充**：{instr}")
    for t in params.數學思考:
        instr = _INSTRUCTIONS.get("數學思考", {}).get(t.value)
        if instr:
            param_instruction_lines.append(f"  - **數學思考（{t.value}）補充**：{instr}")
    for code in params.核心素養:
        instr = _CC_INSTRUCTIONS.get(code)
        if instr:
            param_instruction_lines.append(f"  - **核心素養（{code}）補充**：{instr}")
    for item in params.學習內容:
        instr = _LC_INSTRUCTIONS.get(item.編碼)
        if instr:
            param_instruction_lines.append(f"  - **學習內容（{item.編碼}）補充**：{instr}")
    for item in params.學習表現:
        instr = _LP_INSTRUCTIONS.get(item.編碼)
        if instr:
            param_instruction_lines.append(f"  - **學習表現（{item.編碼}）補充**：{instr}")
    content_type_instr = CONTENT_TYPE_INSTRUCTIONS.get(
        content_type,
        f"請將題目內容類型視為「{content_type}」，依此設計題目素材。",
    )
    param_instruction_lines.append(
        f"  - **題目內容類型（{content_type}）補充**：{content_type_instr}"
    )
    param_instructions = (
        "\n## 條件補充說明\n\n" + "\n".join(param_instruction_lines) + "\n"
        if param_instruction_lines else ""
    )

    # Difficulty is a pure passthrough; the resolved value lives on params.difficulty.
    difficulty_value = params.difficulty.value
    difficulty_instr = DIFFICULTY_INSTRUCTIONS.get(
        difficulty_value,
        "本題無指定難度說明；請以中等難度作為預設。",
    )
    difficulty_section = (
        f"\n## 難度要求\n\n"
        f"- **難度等級**：{difficulty_value}\n"
        f"- **命題指示**：{difficulty_instr}\n"
    )

    # Style instruction
    style_instruction = _INSTRUCTIONS.get("question_style", {}).get(params.style.value, "")

    # User-supplied overrides
    user_materials_parts = []
    topic_override = user_topic.strip() if user_topic else ""
    if topic_override:
        user_materials_parts.append(
            "## 指定情境（請以此主題作為題目情境）\n\n"
            f"主題 / 議題：{topic_override}"
        )
    if user_core_question:
        user_materials_parts.append(
            "## 指定核心問題（命題參考方向，請扣題設計）\n\n"
            f"核心問題：{user_core_question}"
        )
    if user_passage:
        user_materials_parts.append(
            "## 使用者指定素材\n\n"
            "**題幹文字（請逐字使用，不得修改）**：\n\n"
            f"```\n{user_passage}\n```"
        )
    if user_options:
        labels = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛"]
        options_list = "\n".join(
            f"({labels[i] if i < len(labels) else str(i + 1)}) {v}"
            for i, v in enumerate(user_options)
        )
        user_materials_parts.append(
            ("## 使用者指定選項\n\n" if not user_passage else "")
            + "**選項（請依序使用，不得更動文字）**：\n\n"
            + options_list
        )
    user_materials = ("\n" + "\n\n".join(user_materials_parts) + "\n") if user_materials_parts else ""

    # Load and format few-shot examples
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

    grade_range = f"{min(_GRADES)}-{max(_GRADES)}年級"
    prior_scopes_block = (
        "\n" + format_prior_scopes_block(prior_scopes) if prior_scopes else ""
    )
    text = USER_PROMPT_TEMPLATE.format(
        grade=params.grade,
        grade_range=grade_range,
        subject_filter=subject_filter,
        context="、".join(c.value for c in params.情境),
        set_type=params.題型種類.value,
        q_type=params.題型.value,
        thinking=thinking,
        content_type=content_type,
        core_competencies=core_competencies,
        content_list=content_list,
        lp_pool_lines=lp_pool_lines,
        param_instructions=param_instructions,
        difficulty_section=difficulty_section,
        style_instruction=style_instruction,
        user_materials=user_materials,
        prior_scopes_block=prior_scopes_block,
        few_shot_examples=few_shot_text,
    )
    return text, []


def _math_group_few_shot_text(
    few_shot_dir: Path,
    rng: random.Random,
    *,
    subquestion_type: str | None = None,
) -> str:
    """Format 題組題 examples from the loader-isolated ``grouped`` style."""
    examples = load_few_shot_examples(few_shot_dir, "grouped")
    flattened: list[dict] = []
    for example in examples:
        if isinstance(example, list):
            flattened.extend(item for item in example if isinstance(item, dict))
        elif isinstance(example, dict):
            flattened.append(example)

    if not flattened:
        return "（目前暫無數學題組題範例，請根據指定條件自行設計。）"

    selected = rng.sample(flattened, min(2, len(flattened)))
    rendered: list[str] = []
    for index, example in enumerate(selected, start=1):
        question = example.get("question", example)
        if subquestion_type and isinstance(question, dict):
            subquestions = question.get("subquestions", [])
            matching = [
                item for item in subquestions
                if isinstance(item, dict) and item.get("題型") == subquestion_type
            ]
            question = matching[0] if matching else (subquestions[0] if subquestions else question)
        rendered.append(
            f"### 範例 {index}：{example.get('description', '')}\n"
            f"```json\n{json.dumps(question, ensure_ascii=False, indent=2)}\n```"
        )
    return "\n\n".join(rendered)


def build_text_system_prompt(
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
) -> str:
    """Build the math 文本生成器 system prompt for an opt-in 題組."""
    prompt = build_system_prompt(
        grades=grades,
        learning_stage=learning_stage,
        curriculum_json=content_text,
        performance_json=performance_text,
    )
    prompt_intro = prompt.split("## 輸出格式", 1)[0].rstrip()
    prompt_intro = prompt_intro.replace(
        "保留math單題（非題組）輸出結構。",
        "本提示詞選用題組輸出結構：先產生共用文本，再規劃多道小題。",
    )
    return prompt_intro + """

## 輸出格式

你必須輸出一個合法的 JSON 物件，格式如下：

```json
{
  "核心問題": "本題組的核心問題",
  "文本": "完整數學情境素材",
  "取材來源": ["來源一"],
  "subquestions": [
    {
      "序號": 1,
      "題型": "選擇題",
      "出題概念": "一句話說明此小題要評量的數學概念"
    }
  ]
}
```

`subquestions` 陣列是小題規劃；每筆提供序號、題型與出題概念即可，
完整題目、答案、答案解析與誘答分析由後續子題產生器負責。請只輸出 JSON，不要輸出其他文字。
"""


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
    text_word_limit: int | None = None,
) -> tuple[str, list[Path]]:
    """Build the math 文本生成器 user prompt for an opt-in 題組."""
    del image_generation_mode
    if rng is None:
        rng = random.Random(params.seed)

    text, image_paths = build_user_prompt(
        params,
        few_shot_dir,
        rng=rng,
        user_topic=user_topic or "",
        user_passage=user_passage or "",
        user_options=user_options,
        user_core_question=user_core_question or "",
        prior_scopes=prior_scopes,
    )
    text = text.replace(
        "請根據以下條件生成一道數學考試題目：",
        "請根據以下條件生成一道數學題組：",
        1,
    )
    count = (
        str(params.sub_question_count)
        if params.sub_question_count is not None
        else "由文本生成器依素材決定"
    )
    set_type_marker = f"- **題型種類**：{params.題型種類.value}\n"
    text = text.replace(
        set_type_marker,
        set_type_marker + f"- **小題數量**：{count}\n",
        1,
    )

    effective_text_word_limit = (
        params.text_word_limit if text_word_limit is None else text_word_limit
    )
    if effective_text_word_limit is not None:
        text = text.replace(
            "\n## 參考範例\n",
            f"\n- **文本字數上限**：{effective_text_word_limit} 字\n\n## 參考範例\n",
            1,
        )

    reference_start = text.find("\n## 參考範例\n")
    reminder_start = text.find("\n## 重要提醒\n", reference_start)
    if reference_start >= 0 and reminder_start >= 0:
        examples = (
            "（目前停用參考範例，請根據指定條件自行設計。）"
            if disable_reference_fewshot
            else _math_group_few_shot_text(few_shot_dir, rng)
        )
        text = (
            text[:reference_start]
            + "\n## 參考範例\n\n"
            + examples
            + text[reminder_start:]
        )

    reminder_start = text.find("\n## 重要提醒\n")
    if reminder_start >= 0:
        text = text[:reminder_start] + f"""
## 題組輸出要求

1. 請輸出 `核心問題`、`文本`、`取材來源` 與 `subquestions`。
   `subquestions` 必須規劃 {count} 道小題。
2. `文本` 應提供所有小題共同使用的數學情境與必要資料，
   `核心問題` 應以一句話界定題組的主要問題。
3. `subquestions` 先提供每道小題的 `序號`、`題型` 與 `出題概念`，
   不要在此階段撰寫完整題目、答案或答案解析。
4. 請依指定的學習內容與數學思考設計小題，並確保每道小題可根據共用文本作答。
5. 只輸出 JSON 格式的結果。
"""
    return text, image_paths


def build_subquestion_system_prompt(
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
) -> str:
    """Build the math 子題產生器 system prompt for one complete 小題."""
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    curriculum = _build_curriculum_section(
        content_text if content_text is not None else _CONTENT_TEXT,
        performance_text if performance_text is not None else _PERFORMANCE_TEXT,
        _PERFORMANCE_INTRO,
    )
    return f"""\
你是一位108課綱數學領域子題命題教師。你會收到一份共用數學文本，以及一道小題的出題規劃；
請只根據該文本與規劃撰寫一道完整的小題 JSON，不要撰寫其他小題。

目前學習階段：{stage}

輸出必須是合法 JSON 物件，格式如下：

```json
{{
  "id": "題組編號-01",
  "序號": 1,
  "年級": 8,
  "題型": "選擇題",
  "題目": "完整題目文字（含選項，若為選擇題）",
  "答案": "A",
  "答案解析": "詳細計算與推理",
  "誘答分析": {{"A": "正確答案：A"}},
  "學習內容": [{{"編碼": "A-8-1", "說明": "說明文字"}}],
  "學習表現": [{{"編碼": "a-IV-1", "說明": "說明文字"}}],
  "出題概念": "評量學生能否……"
}}
```

## 課程綱要參考

{curriculum}

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
    cfg: object | None = None,
    disable_reference_fewshot: bool = False,
) -> tuple[str, list[Path]]:
    """Build the math 子題產生器 user prompt for one planned 小題."""
    del image_generation_mode, cfg
    if rng is None:
        rng = random.Random(params.seed)

    q_type = sq_plan.get("題型", params.題型.value)
    content_lines = "\n".join(
        f"  - {item.編碼}：{item.說明}" for item in params.學習內容
    ) or "  - （依課綱自行選用）"
    performance_lines = "\n".join(
        f"  - {item.編碼}：{item.說明}" for item in params.學習表現
    ) or "  - （依課綱自行選用）"
    few_shot_text = (
        "（目前停用參考範例，請根據指定條件自行設計。）"
        if disable_reference_fewshot
        else _math_group_few_shot_text(few_shot_dir, rng, subquestion_type=q_type)
    )
    source_text = json.dumps(取材來源, ensure_ascii=False, indent=2)
    slot_number = sq_plan.get("序號", 1)
    return f"""\
請根據以下共用素材與小題規劃，生成一道數學領域小題：

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

- **序號**：第 {slot_number} 小題
- **題型**：{q_type}
- **出題概念**：{sq_plan.get("出題概念", "")}

## 指定條件

- **年級重心**：{params.grade}年級
- **情境**：{"、".join(c.value for c in params.情境)}
- **數學思考**：{"、".join(t.value for t in params.數學思考)}
- **學習內容**：
{content_lines}
- **學習表現**：
{performance_lines}

## 參考範例

{few_shot_text}

## 重要提醒

1. 只撰寫序號 {slot_number} 的一道完整小題，題目必須能依據共用文本作答。
2. 題型必須嚴格遵守本小題規劃中的 `題型`，出題概念需回應規劃中的能力提示。
3. 請輸出 `題目`、`答案`、`答案解析`、`誘答分析`、`學習內容`、`學習表現` 與 `出題概念`。
4. 只輸出一道小題的 JSON，不要輸出其他文字。
""", []
