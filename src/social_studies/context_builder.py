"""Assemble LLM prompts for 108課綱 社會領域素養導向 question generation.

Figure routing: any `chart_spec` this module instructs the model to emit
(top-level 題組 material or per-小題 supplements) must follow the rule in
``docs/figure-rendering-policy.md`` — precise/quantitative statistical charts
use ``render_mode: "chart"`` (matplotlib); structured or semantic illustrative
figures (menus, posters, scenario cards, tables with domain annotations) use
``render_mode: "html"`` (LLM-HTML + Playwright); realistic diagrams (maps with
real coastlines, historical images, scenario 寫實圖) use
``render_mode: "gpt_image"`` (OpenAI image API). See ``CONTENT_TYPE_INSTRUCTIONS``
below for the per-``文本素材類型`` mapping.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from pathlib import Path

from src.common.batch_dedup import PriorScope, format_prior_scopes_block
from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.social_studies.core_competency_loader import (
    competency_instructions,
    load_core_competencies,
    stage_code_for,
)
from src.social_studies.curriculum_loader import (
    content_instructions,
    load_learning_content,
    load_learning_performance,
    load_performance_intro,
    performance_instructions,
)
from src.social_studies.data_loader import load_few_shot_example_groups
from src.social_studies.schema_loader import (
    build_instructions,
    load_grades,
    load_learning_stage,
    load_schemas,
)
from src.social_studies.schemas import CreativeBrief, SampledParams, SubQuestionConfig

_schemas = load_schemas()
_INSTRUCTIONS: dict[str, dict[str, str]] = build_instructions(_schemas)
_GRADES: list[int] = load_grades(_schemas)
_LEARNING_STAGE: str = load_learning_stage(_schemas)

_CC_DATA: dict = load_core_competencies()
_CC_INSTRUCTIONS: dict[str, str] = competency_instructions(_CC_DATA)
_STAGE_CODE: str = stage_code_for(_CC_DATA, _LEARNING_STAGE)

_PERFORMANCE_DATA: dict = load_learning_performance()
_CONTENT_DATA: dict = load_learning_content()
_PERFORMANCE_INTRO: str = load_performance_intro()

_PERFORMANCE_TEXT: str = json.dumps(_PERFORMANCE_DATA, ensure_ascii=False, indent=2) if _PERFORMANCE_DATA.get("學習表現") else ""
_CONTENT_TEXT: str = json.dumps(_CONTENT_DATA, ensure_ascii=False, indent=2) if _CONTENT_DATA.get("學習內容") else ""
_LC_INSTRUCTIONS: dict[str, str] = content_instructions(_CONTENT_DATA)
_LP_INSTRUCTIONS: dict[str, str] = performance_instructions(_PERFORMANCE_DATA)
LC_INSTRUCTIONS = _LC_INSTRUCTIONS
LP_INSTRUCTIONS = _LP_INSTRUCTIONS

CONTENT_TYPE_INSTRUCTIONS: dict[str, str] = {
    "純文字": (
        "本題組必須只使用純連續文本素材。不得輸出 `chart_spec`、`image_spec` 或任何需要渲染成圖片的資料；"
        "題目與答案解析只能依據 `文本` 欄位中的文字內容。"
    ),
    "含圖片": (
        "本題組必須包含圖片式或視覺式非連續素材，例如地圖、圖解、廣告、表單、海報或網頁畫面。"
        "請在題組頂層輸出非 null 的 `chart_spec`，並依圖片家族選擇 `render_mode`："
        "\n"
        "- **寫實圖 / 地理圖像** — 帶真實海岸線或行政區劃的地圖、歷史照片式的情境圖、"
        "文物照片式插畫、需要接近寫實筆觸的場景插圖，請使用 `render_mode: \"gpt_image\"`。"
        "\n"
        "- **結構化 / 版面** — 廣告、表單、海報、網頁畫面、比較欄位、含語意標註的表格，"
        "請使用 `render_mode: \"html\"`。"
        "\n"
        "在 `description` 與 `data` 中完整描述版面與內容。"
        "（重要）圖片必須是作答的必要條件：至少一道小題的答案必須直接依賴圖片中才有的資訊，無法僅憑文本回答。"
        "設計時請先確定「移除圖片後此題是否仍可作答」——若可以，請重新設計圖片，使其承載文本中未涵蓋的關鍵資訊"
        "（例如地圖上的地名/路線/分布、廣告上的價格/期限/規則、表單上的數據欄位）。"
        f"（示意圖聲明）圖片為示意用途，非完全等比例繪製；若使用 `render_mode: \"html\"`，"
        f"請在 `chart_spec.description` 中要求下游 HTML 產生器將「{IMAGE_DISCLAIMER}」"
        f"以 caption 呈現在圖片下緣或版面空白處。"
    ),
    "graphs/charts/tables": (
        "本題組必須包含圖表或表格素材。統計圖（直方圖、折線圖、圓餅圖等）請使用 `render_mode: \"chart\"`；"
        "表格或複合資料表請使用 `render_mode: \"html\"`，並在題組頂層輸出非 null 的 `chart_spec`，"
        "於 `data` 中提供完整欄列資料。"
        "（重要）圖表/表格必須是作答的必要條件：至少一道小題須讀取圖表中的具體數值、趨勢或分類才能回答，"
        "且這些數值不得在 `文本` 欄位中重複列出。若移除圖表後題目仍可回答，需重新設計使數據只存在於圖表中。"
        f"（示意圖聲明）圖表軸線、格線與座標比例僅為示意，非完全等比例繪製；"
        f"請在 `chart_spec.description` 或圖表 caption 加註「{IMAGE_DISCLAIMER}」，"
        "但圖表中的數值、標籤與分類仍必須完全對應 `data` 內容。"
    ),
}

#: 題目內容類型 values that require the 小題 (or 題組) to carry its own image.
VISUAL_CONTENT_TYPES: frozenset[str] = frozenset({"含圖片", "graphs/charts/tables"})

#: The 小題-level image rule, stated verbatim to both the 文本生成器 (whose
#: per-小題 plan is discarded downstream) and the 子題產生器 that actually
#: writes the 小題 — one rulebook, two stages (issue #319).
SUBQUESTION_IMAGE_RULE: str = (
    "只有文本素材類型為 `含圖片` 或 `graphs/charts/tables` 的小題必須輸出該小題自己的 "
    "`chart_spec`；`image_generation_mode` 只指定渲染方式，不能單獨視為需要圖片。"
)

DIFFICULTY_INSTRUCTIONS: dict[str, str] = _INSTRUCTIONS.get("難度", {})


def _difficulty_section(params: "SampledParams") -> str:
    """Return the shared `## 難度要求` block for text + subquestion prompts."""
    value = params.difficulty.value
    instr = DIFFICULTY_INSTRUCTIONS.get(
        value,
        "本題組無指定難度說明；請以中等難度作為預設。",
    )
    return (
        "\n## 難度要求\n\n"
        f"- **難度等級**：{value}\n"
        f"- **命題指示**：{instr}\n"
    )


_CREATIVE_BRIEF_SYSTEM_BLOCK = """\

### 創意指引

- 本批次題組已由前置規劃器指定「情境-題材角度」與「參考取材點」，請以此為文本取材主軸。
- 不得直接沿用範例題材（few-shot）中的題材、機構名、資料形式；請以指定角度重新設計素材。
- 題材角度必須具體落地在文本中（不是抽象口號）；至少一項 framing hook 應成為文本或素材的組成元素。
"""


def _render_brief_context_suffix(brief: CreativeBrief | None) -> str:
    """Return the parenthetical creative suffix appended to the 情境 line."""
    if brief is None:
        return ""
    parts = [f"創意取材角度：{brief.題材_angle}"]
    if brief.framing_hooks:
        parts.append("參考取材點：" + "、".join(brief.framing_hooks))
    return "（" + "；".join(parts) + "）"


def _render_brief_guidance_section(brief: CreativeBrief | None) -> str:
    """Return a `## 創意指引` user-prompt section for the given brief."""
    if brief is None:
        return ""
    hook_line = (
        f"\n- 建議取材點：{'、'.join(brief.framing_hooks)}"
        if brief.framing_hooks else ""
    )
    return (
        "\n## 創意指引\n\n"
        f"- 情境：{brief.selected_context}\n"
        f"- 題材角度：{brief.題材_angle}"
        f"{hook_line}\n"
        "- 請以上述題材角度為文本取材主軸，避免直接複製參考範例的題材或格式。\n"
    )


SYSTEM_PROMPT_TEMPLATE = """\
你是一位資深的108課綱社會領域命題教師，專門為{learning_stage}（{grade_names}）設計「社會領域素養導向」考試題目。
本題庫根據國家教育研究院 NAER-2019-041-A-1-1-E1-10 計畫之命題框架設計，涵蓋歷史、地理、公民與社會三科。
**本題庫專為{learning_stage}設計：所有 `核心素養` 代號必須使用 `社-{stage_code}-*` 開頭（如 社-{stage_code}-A2、社-{stage_code}-C3），不得使用其他學習階段的代號。**

## 108課綱社會領域素養導向命題框架

### 題組結構
每道題組（題組題）包含：
1. **核心問題**：一句話說明本題組的跨科主要問題意識（如「如何理解1918年流感疫情的擴散與當代防疫啟示？」）。若使用者在指示中提供了「指定核心問題」，請直接將其逐字用於輸出的 `核心問題` 欄位，不得修改。
2. **文本**：一篇或多篇真實情境素材（連續文本或非連續文本；混合式內容可透過 chart_spec 補充非連續素材）
3. **取材來源**：列出文本的原始資料來源
4. **小題（subquestions）**：3–7 道由淺入深的小題，各小題彼此獨立作答，但共用文本

### 各小題必須標記
- `年級`：7、8 或 9（同一題組內不同小題可以不同年級）
- `科目`：歷史 / 地理 / 公民與社會（一小題可跨科時請列出複數）
- `核心素養`：對應108課綱素養代號，本題庫限用 `社-{stage_code}-*` 開頭（如 社-{stage_code}-A2、社-{stage_code}-C3）
- `學習內容`：對應課綱條目編碼+說明（如 地Aa-Ⅳ-2 全球海陸分布）
- `學習表現`：對應課綱學習表現代號+說明（如 社1b-Ⅳ-1 應用社會領域內容知識解析生活經驗或社會現象）
- `出題概念`：一句話說明此題評量學生何種能力
- `出題指示`：若使用者提供各小題配置中的出題指示，請逐字填入
- `題目內容類型`：若使用者提供各小題配置，依該小題指定值填入
  （純文字 / 含圖片 / graphs/charts/tables / 自訂類型）
- `image_generation_mode`：若該小題指定圖片產生方式，填入 `html` 或 `gpt_image`
- 若某小題的 `題目內容類型` 是 `含圖片` 或 `graphs/charts/tables`，
  該小題必須包含自己的 `chart_spec`。
  `image_generation_mode` 只代表圖片渲染方式；若小題仍是純文字，
  不要只因 `image_generation_mode` 而輸出圖片。

### 題組共用素材圖片規則
- 若指定條件中的全域 `文本素材類型` 是 `含圖片` 或 `graphs/charts/tables`，
  必須在題組 JSON 頂層輸出非 null 的 `chart_spec`，作為整個題組共用的主要素材圖片。
- `subquestions[*].chart_spec` 只能表示特定小題自己的補充圖片；
  不能取代全域 `文本素材類型` 要求的題組頂層 `chart_spec`。
- 若同時指定全域視覺素材與各小題視覺素材，可以同時輸出題組頂層 `chart_spec`
  與對應小題的 `subquestions[*].chart_spec`。

### 題型說明
- **選擇題**：四選一；給分代號 2（正確）/ 0（錯誤）
- **封閉式建構反應題**：唯一正確答案（詞彙、數字或短語）；給分代號 2 / 0
- **開放式建構反應題**：需學生組織語言說明思考過程；給分代號 2（完整正確）/ 1（部分正確）/ 0（錯誤或不相關）/ 0X（未作答）；**必須附評分規準（rubric）**，每條規準請提供 1–2 個學生作答實例（含正確與典型錯誤示例）

### PISA閱讀歷程（輔助參考）
試題設計時請參考閱讀歷程分布：
- 擷取訊息（約25%）、形成廣泛理解（約25%）、發展解釋（約25%）、省思與評鑑（約25%）

## 課程綱要參考

{curriculum_section}

## 輸出格式

你必須輸出一個合法的 JSON 物件，格式如下：

```json
{{
  "核心問題": "本題組的跨科核心問題（一句話）",
  "文本": "完整文本素材（包含說明文字、引述文獻、表格描述等）",
  "取材來源": ["來源一", "來源二"],
  "情境": ["（PISA情境，可多個：個人/公共/職業/教育）"],
  "題型種類": "題組題",
  "題型": "（所有小題的主要題型，選擇題/封閉式建構反應題/開放式建構反應題）",
  "閱讀歷程": ["（主要閱讀歷程，1–2個）"],
  "文本形式": "（連續文本—說明文 等）",
  "題目內容類型": "含圖片",
  "subquestions": [
    {{
      "序號": 1,
      "年級": 7,
      "科目": ["地理"],
      "核心素養": ["社-J-A2"],
      "學習內容": [{{"編碼": "地Aa-Ⅳ-2", "說明": "全球海陸分布"}}],
      "學習表現": [{{"編碼": "社1b-Ⅳ-1", "說明": "應用社會領域內容知識解析生活經驗或社會現象"}}],
      "出題概念": "評量學生能否……",
      "出題指示": "使用者指定給本小題的出題方向；若未指定則為 null",
      "題型": "選擇題",
      "題目內容類型": "純文字",
      "image_generation_mode": "html",
      "題目": "問題一\n根據文章內容……\n（A）……\n（B）……\n（C）……\n（D）……",
      "答案": "A",
      "答案解析": "從圖1……",
      "評分規準": [],
      "chart_spec": null
    }}
  ],
  "題目": ["（將文本和所有小題合併為陣列，供舊版驗證器使用）"],
  "正確解題分析": ["（逐題答案說明，供舊版驗證器使用）"],
  "chart_spec": {{...}}
}}
```

若題目含非連續文本素材，請加入 `chart_spec`。若全域 `文本素材類型` 是
`含圖片` 或 `graphs/charts/tables`，必須放在題組頂層 `chart_spec`；
若素材只屬於特定小題，才額外放在該小題的 `chart_spec`。
若「各小題配置」指定某小題的文本素材類型為 `含圖片` 或 `graphs/charts/tables`，
該小題必須輸出非 null 的 `chart_spec`：

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
  "description": "詳細描述素材內容與版面結構。請在 description 結尾要求下游 HTML 產生器於素材下緣加註 caption：「{image_disclaimer}」。",
  "title": "素材標題（選填）",
  "data": {{ "key": "value" }}
}}
```
所有輸出的 `chart_spec` 圖片皆為示意用途、非完全等比例繪製；因此無論 `render_mode` 是 `chart` 或 `html`，`description` 都必須要求下游產生器附上 caption「{image_disclaimer}」。圖表中的數值、標籤與分類仍必須忠實對應 `data`。

### 圖片必要性原則
- 凡輸出非 null 的 `chart_spec`，該圖片、圖表或表格必須承載至少一道小題作答所必需的資訊。
- 至少一道小題的答案必須直接依賴 `chart_spec` 中才有的具體資訊，不能只靠 `文本` 欄位回答。
- `chart_spec` 中承載的關鍵數據、標示、路線、分類或規則不得在 `文本` 欄位中重複列出。
- 若移除圖片、圖表或表格後題目仍可回答，請重新設計 `chart_spec`，使必要資訊只存在於視覺素材中。

純連續文本題目不需 `chart_spec`。請只輸出 JSON，不要輸出其他文字。
"""

USER_PROMPT_TEMPLATE = """\
請根據以下條件生成一道108課綱社會領域素養導向題組：

## 指定條件

- **年級重心**：{grade}年級（{learning_stage}）
- **科目焦點**：{subject}
- **情境**：{context}（PISA閱讀情境）
- **題型種類**：{set_type}
- **題型**：由各小題配置指定；若未列出固定小題，允許題型為 {q_types}
- **小題數量**：{sub_question_count}
- **閱讀歷程（PISA）**：{reading_process}
- **文本形式**：{text_form}
- **文本素材類型**：{content_type}
- **圖片生成模式**：{image_generation_mode}
- **核心素養（限定使用）**：{core_competencies}
{lc_pool_lines}{lp_pool_lines}{subquestion_config_lines}{param_instructions}{difficulty_section}{user_materials}
## 參考範例

{few_shot_examples}

## 重要提醒

1. 不要複製範例題目，必須原創。
2. 文本素材應貼近真實情境，語言自然，非教科書式；可使用新聞、報告、圖表、訪談摘要等真實素材形式。
3. 每道小題須填入正確的 學習內容 編碼（參考系統提供的課程綱要）。各小題的 `學習內容` / `學習表現` 應優先使用上述指定代號；如題組設計需引入其他課綱代號，仍以 `## 課程綱要參考` 中列出者為限。
4. 各小題的 `核心素養` 欄位**必須只從指定條件中的核心素養代號選擇**，整個題組應盡量讓每個指定代號至少出現一次。
5. 開放式建構反應題必須附完整的評分規準（rubric），每條含 1–2 個學生作答實例。
6. 評分代號請使用：2（滿分）/ 1（部分得分，限開放式）/ 0（零分）/ 0X（未作答）。
7. `題目` 陣列（舊版格式）：第一個元素放文本素材，其後每個元素放一道小題完整文字。
8. `正確解題分析` 陣列（舊版格式）：每個元素對應一道小題的答案與說明。
9. 只輸出 JSON 格式的結果。
10. 若題組含圖片（`chart_spec` 非 null），必須確認：至少一道小題的答案無法在沒有圖片的情況下得出；且 `chart_spec` 中承載的關鍵數據/資訊不得在 `文本` 欄位中重複說明。
"""

_CURRICULUM_EMPTY_NOTICE = "（課程綱要資料待研究人員補充至 data/social_studies/curriculum/）"


def _build_curriculum_section(
    content_text: str,
    performance_text: str,
    performance_intro: str = "",
) -> str:
    if not content_text and not performance_text:
        return _CURRICULUM_EMPTY_NOTICE
    parts = []
    if performance_intro:
        parts.append("### 學習表現架構說明\n\n" + performance_intro)
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
    g = grades if grades is not None else _GRADES
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    grade_names = "、".join(f"{x}年級" for x in g)
    c_text = content_text if content_text is not None else _CONTENT_TEXT
    p_text = performance_text if performance_text is not None else _PERFORMANCE_TEXT
    p_intro = _PERFORMANCE_INTRO
    curriculum_section = _build_curriculum_section(c_text, p_text, p_intro)
    sc = stage_code_for(_CC_DATA, stage)
    return SYSTEM_PROMPT_TEMPLATE.format(
        learning_stage=stage,
        grade_names=grade_names,
        curriculum_section=curriculum_section,
        stage_code=sc,
        image_disclaimer=IMAGE_DISCLAIMER,
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

    reading_process = "、".join(p.value for p in params.閱讀歷程)
    topic_override = user_topic.strip() if user_topic else ""
    content_type = params.題目內容類型 or "純文字"

    param_instruction_lines = []
    if not topic_override:
        for c in params.情境:
            instr = _INSTRUCTIONS.get("情境", {}).get(c.value)
            if instr:
                param_instruction_lines.append(f"  - **情境（{c.value}）補充**：{instr}")
    for category, key in (
        ("題型種類", params.題型種類.value),
        ("文本形式", params.文本形式.value),
        ("科目", params.科目.value),
    ):
        instr = _INSTRUCTIONS.get(category, {}).get(key)
        if instr:
            param_instruction_lines.append(f"  - **{category}（{key}）補充**：{instr}")
    for qt in params.題型:
        instr = _INSTRUCTIONS.get("題型", {}).get(qt.value)
        if instr:
            param_instruction_lines.append(f"  - **題型（{qt.value}）補充**：{instr}")
    for p in params.閱讀歷程:
        instr = _INSTRUCTIONS.get("閱讀歷程", {}).get(p.value)
        if instr:
            param_instruction_lines.append(f"  - **閱讀歷程（{p.value}）補充**：{instr}")
    for c in params.核心素養:
        instr = _CC_INSTRUCTIONS.get(c.value)
        if instr:
            param_instruction_lines.append(f"  - **核心素養（{c.value}）補充**：{instr}")
    content_type_instr = CONTENT_TYPE_INSTRUCTIONS.get(
        content_type,
        f"請將題目內容類型視為「{content_type}」，依此設計文本、素材形式與題目，不得偏離此指定類型。",
    )
    param_instruction_lines.append(
        f"  - **題目內容類型（{content_type}）補充**：{content_type_instr}"
    )
    if content_type in {"含圖片", "graphs/charts/tables"}:
        param_instruction_lines.append(
            "  - **題組共用圖片規則**：全域 `文本素材類型` 是 `含圖片` 或 "
            "`graphs/charts/tables` 時，必須在題組 JSON 頂層輸出非 null 的 "
            "`chart_spec`；`subquestions[*].chart_spec` 只能作為特定小題補充，"
            "不能取代全域 `文本素材類型` 要求的題組頂層 `chart_spec`。"
        )
    param_instructions = (
        "\n## 條件補充說明\n\n" + "\n".join(param_instruction_lines) + "\n"
        if param_instruction_lines else ""
    )

    difficulty_section = _difficulty_section(params)

    example_groups = (
        [] if disable_reference_fewshot else load_few_shot_example_groups(few_shot_dir)
    )
    all_image_paths: list[Path] = []
    if example_groups:
        sample_count = min(2, len(example_groups))
        selected_groups = rng.sample(example_groups, sample_count)
        selected = [rng.choice(group) for group in selected_groups]
        example_texts = []
        for i, ex in enumerate(selected, 1):
            q = ex.get("question", ex)
            ex_images: list[dict] = ex.get("images", [])
            img_notes = ""
            if ex_images:
                for j, img in enumerate(ex_images, 1):
                    caption = img.get("caption", "")
                    label = f"圖{j}" + (f"（{caption}）" if caption else "")
                    img_notes += f"\n<!-- {label} 附於此範例後 -->"
                    all_image_paths.append(Path(img["path"]))
            example_texts.append(
                f"### 範例 {i}：{ex.get('description', '')}\n```json\n{json.dumps(q, ensure_ascii=False, indent=2)}\n```{img_notes}"
            )
        few_shot_text = "\n\n".join(example_texts)
    else:
        few_shot_text = "（目前暫無範例，請根據指定條件自行設計。）"

    core_competencies = "、".join(c.value for c in params.核心素養)

    # 指定學習內容 / 指定學習表現 lines
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

    # #100/#101: per-subquestion count, word limits, content type, image mode, type, and instruction.
    sq_config_parts = []
    for i, cfg in enumerate(params.subquestion_configs, start=1):
        cfg_parts = []
        has_structural_config = any((
            cfg.question_type,
            cfg.instruction,
            cfg.content_type,
            cfg.image_generation_mode,
            cfg.question_word_limit,
            cfg.option_word_limit,
            cfg.learning_content,
            cfg.learning_performance,
        ))
        has_config = has_structural_config or bool(cfg.text_word_limit)
        if cfg.question_type:
            cfg_parts.append(f"題型={cfg.question_type.value}")
        if cfg.instruction:
            cfg_parts.append(f"出題指示={cfg.instruction}")
        if cfg.learning_content:
            cfg_parts.append(f"學習內容={','.join(cfg.learning_content)}")
        if cfg.learning_performance:
            cfg_parts.append(f"學習表現={','.join(cfg.learning_performance)}")
        if has_structural_config:
            cfg_parts.append(f"文本素材類型={cfg.content_type or content_type}")
            cfg_parts.append(
                f"圖片生成模式={cfg.image_generation_mode or image_generation_mode}",
            )
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
            sq_config_parts.append(
                f"  - 每個選項字數上限：{params.option_word_limit} 字（限選擇題）",
            )
    if sq_config_parts:
        sq_config_content_types = list(
            {
                cfg.content_type or content_type
                for cfg in params.subquestion_configs
                if any((
                    cfg.content_type,
                    cfg.image_generation_mode,
                    cfg.question_word_limit,
                    cfg.option_word_limit,
                    cfg.question_type,
                    cfg.instruction,
                    cfg.learning_content,
                    cfg.learning_performance,
                ))
            },
        )
        for ct in sq_config_content_types:
            ct_instr = CONTENT_TYPE_INSTRUCTIONS.get(ct, "")
            if ct_instr:
                sq_config_parts.append(f"  - **{ct} 說明**：{ct_instr}")
        if any(ct in VISUAL_CONTENT_TYPES for ct in sq_config_content_types):
            sq_config_parts.append(f"  - **小題圖片規則**：{SUBQUESTION_IMAGE_RULE}")
    subquestion_config_lines = (
        "\n## 各小題配置\n\n" + "\n".join(sq_config_parts) + "\n"
        if sq_config_parts else ""
    )

    user_materials_parts = []
    if topic_override:
        user_materials_parts.append(
            "## 指定情境（請直接取代原本的 PISA 情境）\n\n"
            f"主題 / 議題：{topic_override}\n\n"
            "請以此主題 / 議題作為題組的真實情境與文本取材方向。"
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
            + "**選項（請依序使用，不得更動文字）**：\n\n"
            + options_list
        )
    user_materials = ("\n" + "\n\n".join(user_materials_parts) + "\n") if user_materials_parts else ""

    if prior_scopes:
        prior_scopes_text = format_prior_scopes_block(prior_scopes)
        user_materials = (user_materials or "\n") + "\n" + prior_scopes_text

    q_types_str = "、".join(t.value for t in params.題型)
    sub_q_count_str = (
        str(params.sub_question_count)
        if params.sub_question_count else "3–7（由命題教師自行決定）"
    )

    brief = getattr(params, "creative_brief", None)
    if topic_override:
        context_line = topic_override
    elif brief is not None:
        suffix = _render_brief_context_suffix(brief)
        context_line = f"{brief.selected_context}{suffix}"
    else:
        context_line = "、".join(c.value for c in params.情境)

    text = USER_PROMPT_TEMPLATE.format(
        grade=params.grade,
        learning_stage=_LEARNING_STAGE,
        subject=params.科目.value,
        context=context_line,
        set_type=params.題型種類.value,
        q_types=q_types_str,
        sub_question_count=sub_q_count_str,
        reading_process=reading_process,
        text_form=params.文本形式.value,
        content_type=content_type,
        image_generation_mode=image_generation_mode,
        core_competencies=core_competencies,
        lc_pool_lines=lc_pool_lines,
        lp_pool_lines=lp_pool_lines,
        subquestion_config_lines=subquestion_config_lines,
        param_instructions=param_instructions,
        difficulty_section=difficulty_section,
        user_materials=user_materials,
        few_shot_examples=few_shot_text,
    )
    return text, all_image_paths


# ---------------------------------------------------------------------------
# Phase-split prompt builders for parallel-subquestion generation
# ---------------------------------------------------------------------------

_TEXT_GENERATION_SYSTEM_PROMPT_TEMPLATE = """\
你是一位資深的108課綱社會領域命題教師，專門為{learning_stage}（{grade_names}）設計「社會領域素養導向」考試題組。
你目前的任務是**只**生成題組的文本素材與頂層元數據，不需要生成任何小題。

## 題組結構說明
每道題組包含一段或多段真實情境素材（文本），是所有小題共用的閱讀素材。
此階段只要求你輸出文本層的欄位：核心問題、文本、取材來源、情境、題型種類、閱讀歷程、文本形式、題目內容類型，以及視覺素材規格（若適用）。

## 課程綱要參考

{curriculum_section}

## 輸出格式

請只輸出以下 JSON，不要輸出 `subquestions`，不要輸出其他文字：

```json
{{
  "核心問題": "本題組的跨科核心問題（一句話）",
  "文本": "完整文本素材（包含說明文字、引述文獻、表格描述等）",
  "取材來源": ["來源一"],
  "情境": ["個人"],
  "題型種類": "題組題",
  "閱讀歷程": ["擷取訊息"],
  "文本形式": "連續文本—說明文",
  "題目內容類型": "純文字",
  "chart_spec": null
}}
```

若全域 `題目內容類型` 是 `含圖片` 或 `graphs/charts/tables`，必須輸出非 null 的 `chart_spec`。
統計圖使用 `render_mode: "chart"`；HTML排版素材（地圖、表格、廣告等）使用 `render_mode: "html"`。
純連續文本不需 `chart_spec`。請只輸出 JSON，不要輸出其他文字。
"""

_TEXT_GENERATION_USER_PROMPT_TEMPLATE = """\
請根據以下條件，只生成題組的文本素材與頂層元數據（不包含小題）：

## 指定條件

- **年級重心**：{grade}年級（{learning_stage}）
- **科目焦點**：{subject}
- **情境**：{context}
- **題型種類**：題組題
- **閱讀歷程（PISA）**：{reading_process}
- **文本形式**：{text_form}
- **文本素材類型**：{content_type}
- **核心素養（限定本題組使用）**：{core_competencies}
- **預計小題題型分布**：{slot_type_summary}
{lc_pool_lines}{lp_pool_lines}{param_instructions}{difficulty_section}{user_materials}
## 重要提醒

1. 文本素材應貼近真實情境，語言自然，非教科書式；可使用新聞、報告、圖表、訪談摘要等真實素材形式。
2. 文本需足夠豐富，能支撐 {slot_count} 道不同題型的小題（{slot_type_summary}）。
3. 只輸出 JSON，不要包含 `subquestions` 欄位。
"""

_SUBQUESTION_SYSTEM_PROMPT_TEMPLATE = """\
你是一位資深的108課綱社會領域命題教師，專門為{learning_stage}（{grade_names}）設計「社會領域素養導向」小題。
你的任務是根據已生成的題組文本，**只**生成指定的第 {slot_number} 小題。

**本小題限定題型：{slot_type}**
**本小題限定核心素養（從以下代號中選用）：{slot_competencies}**
**本題組核心素養代號必須使用 `社-{stage_code}-*` 開頭。**

## 小題必須標記的欄位
- `年級`：7、8 或 9
- `科目`：歷史 / 地理 / 公民與社會（可跨科）
- `核心素養`：從指定代號中選用，使用 `社-{stage_code}-*` 格式
- `學習內容`：對應課綱條目編碼+說明
- `學習表現`：對應課綱學習表現代號+說明
- `出題概念`：一句話說明此題評量學生何種能力
- `題型`：**必須是 {slot_type}**

## 題型說明
- **選擇題**：四選一；答案為 A/B/C/D；評分規準為空陣列
- **封閉式建構反應題**：唯一正確答案（詞彙、數字或短語）；評分規準為空陣列
- **開放式建構反應題**：需學生組織語言；**必須附評分規準**，給分代號 2/1/0/0X，每條規準附 1–2 個學生作答實例

## 同組其他小題資訊（僅供參考，避免與其他小題重複考點）
{sibling_slots_summary}

## 課程綱要參考

{curriculum_section}

## 輸出格式

只輸出以下 JSON 物件，不要輸出其他文字：

```json
{{
  "序號": {slot_number},
  "年級": 7,
  "科目": ["地理"],
  "核心素養": ["社-{stage_code}-A2"],
  "學習內容": [{{"編碼": "地Aa-Ⅳ-2", "說明": "全球海陸分布"}}],
  "學習表現": [{{"編碼": "社1b-Ⅳ-1", "說明": "應用社會領域內容知識解析生活經驗或社會現象"}}],
  "出題概念": "評量學生能否……",
  "出題指示": null,
  "題型": "{slot_type}",
  "題目內容類型": "純文字",
  "題目": "完整題目文字（含選項，若為選擇題）",
  "答案": "A",
  "答案解析": "詳細解析",
  "評分規準": []
}}
```
"""

_SUBQUESTION_USER_PROMPT_TEMPLATE = """\
以下是已生成的題組文本，請根據此文本生成第 {slot_number} 小題。

## 題組文本

{passage}

## 本小題配置

- **序號**：第 {slot_number} 小題（共 {total_slots} 小題）
- **題型**：{slot_type}
- **核心素養**：{slot_competencies}
- **指定學習內容代號**：{lc_pool}
- **指定學習表現代號**：{lp_pool}
{slot_instruction_line}{difficulty_section}
## 重要提醒

1. 題目必須根據上方文本作答，不得引入文本未提及的外部知識作為答題必要條件。
2. 題型必須嚴格遵守：本小題題型為**{slot_type}**，不得更改。
3. 答案不得與其他小題答案直接關聯或互相揭露（各小題獨立作答）。
4. 若為開放式建構反應題，必須附完整評分規準（rubric）。
5. 只輸出 JSON 物件，不要輸出其他文字。
"""


def build_text_system_prompt(
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
    creative_brief: CreativeBrief | None = None,
) -> str:
    prompt = build_system_prompt(
        grades=grades,
        learning_stage=learning_stage,
        content_text=content_text,
        performance_text=performance_text,
    )
    prompt_intro = prompt.split("## 輸出格式", 1)[0].rstrip()
    body = prompt_intro + """

## 輸出格式

你必須輸出一個合法的 JSON 物件，格式如下：

```json
{
  "核心問題": "本題組的核心問題",
  "文本": "完整閱讀素材",
  "取材來源": ["來源一"],
  "subquestions": [
    {
      "序號": 1,
      "題型": "選擇題",
      "出題概念": "一句話說明此小題要評量的能力"
    }
  ]
}
```

`subquestions` 陣列為各小題的出題規劃，每筆只需序號、題型與一句出題概念說明；詳細題目與答案將由後續子題產生器負責。請只輸出 JSON，不要輸出其他文字。
"""
    if creative_brief is not None:
        body += _CREATIVE_BRIEF_SYSTEM_BLOCK
    return body


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
    brief = getattr(params, "creative_brief", None)
    if brief is not None:
        text += _render_brief_guidance_section(brief)
    text = text.replace(
        """\
6. 評分代號請使用：2（滿分）/ 1（部分得分，限開放式）/ 0（零分）/ 0X（未作答）。
7. `題目` 陣列（舊版格式）：第一個元素放文本素材，其後每個元素放一道小題完整文字。
8. `正確解題分析` 陣列（舊版格式）：每個元素對應一道小題的答案與說明。
9. 只輸出 JSON 格式的結果。
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
    curriculum_section = _build_curriculum_section(c_text, p_text, _PERFORMANCE_INTRO)
    sc = stage_code_for(_CC_DATA, learning_stage)
    return f"""\
你是一位108課綱社會領域子題命題教師。你會收到一份共用閱讀素材，以及一道小題的出題規劃；請只根據該素材與規劃撰寫 exactly one SubQuestion JSON。

目前學習階段：{learning_stage}
本小題的核心素養代號必須使用 `社-{sc}-*` 開頭。

輸出必須是合法 JSON 物件，格式如下：

```json
{{
  "序號": 1,
  "年級": 8,
  "科目": ["歷史"],
  "核心素養": ["社-J-A2"],
  "學習內容": [{{"編碼": "歷Ka-Ⅳ-1", "說明": "說明文字"}}],
  "學習表現": [{{"編碼": "社1b-Ⅳ-1", "說明": "說明文字"}}],
  "出題概念": "評量學生能否……",
  "題型": "選擇題",
  "題目內容類型": "純文字",
  "image_generation_mode": null,
  "chart_spec": null,
  "題目": "完整題目文字（含選項）",
  "答案": "A",
  "答案解析": "說明正答依據",
  "評分規準": [],
  "誘答分析": {{"A": "...", "B": "正確答案：...", "C": "...", "D": "..."}}
}}
```

## 本小題圖片

- `題目內容類型`：若各小題配置指定了本小題的文本素材類型，依該小題指定值填入
  （純文字 / 含圖片 / graphs/charts/tables / 自訂類型）。
- `image_generation_mode`：若該小題指定圖片產生方式，填入 `html` 或 `gpt_image`。
- 若本小題的 `題目內容類型` 是 `含圖片` 或 `graphs/charts/tables`，
  本小題必須輸出自己的 `chart_spec`。
  `image_generation_mode` 只代表圖片渲染方式；若本小題仍是純文字，
  不要只因 `image_generation_mode` 而輸出圖片。
- `chart_spec.render_mode`：統計圖（直方圖、折線圖、圓餅圖等）用 `chart`，
  並提供 `chart_type`、`data`、`labels`；廣告、表單、海報、網頁畫面或含語意標註的表格用
  `html`；帶真實海岸線的地圖、歷史照片式情境圖等寫實圖像用 `gpt_image`。
- 圖片必須是作答的必要條件：本小題的答案必須依賴圖片中才有的資訊，無法僅憑文本回答。

## 誘答分析的設計

`誘答分析` 是一個以「選項標籤」為鍵、對應誘答描述為值的 JSON dict：

- **選擇題**：鍵為 `"A"` / `"B"` / `"C"` / `"D"`。錯誤選項描述其針對的認知陷阱（誤讀題意 / 概念混淆 / 部分正確誘騙 / 過度推論 …），正確選項的值為一句 「正確答案：…」。
- **封閉式 / 開放式建構反應題**：可留空 `{{}}`，或提供 `{{"常見錯誤": "…"}}` 描述一項最常見的錯誤。

範例：

```json
"誘答分析": {{
  "A": "概念混淆：把『生產者剩餘』誤讀為『消費者剩餘』。",
  "B": "正確答案：因供給彈性高，稅賦大部分由消費者承擔。",
  "C": "部分正確誘騙：只提到彈性，未連結稅賦轉嫁方向。",
  "D": "過度推論：忽略市場結構的假設。"
}}
```

## 評分規準
- 選擇題：四選一；答案為 A/B/C/D；正確代號 2，錯誤代號 0，評分規準為空陣列。
- 封閉式建構反應題：唯一正確答案（詞彙、數字或短語）；正確代號 2，錯誤代號 0，評分規準為空陣列。
- 開放式建構反應題：必須附 `評分規準`，使用 2 / 1 / 0 / 0X。2 代表完整正確，1 代表部分正確，0 代表錯誤或不相關，0X 代表未作答；每條規準請提供 1–2 個學生作答實例。

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
    if rng is None:
        rng = random.Random(params.seed)

    q_type = (
        cfg.question_type.value
        if cfg is not None and cfg.question_type is not None
        else sq_plan.get("題型", "")
    )
    example_groups = (
        [] if disable_reference_fewshot else load_few_shot_example_groups(few_shot_dir)
    )
    all_image_paths: list[Path] = []
    matching_examples: list[dict] = []
    fallback_examples: list[dict] = []
    for group in example_groups:
        for ex in group:
            q = ex.get("question", ex)
            fallback_examples.append(ex)
            if isinstance(q, dict):
                if q.get("題型") == q_type:
                    matching_examples.append(ex)
                for subquestion in q.get("subquestions", []):
                    if isinstance(subquestion, dict) and subquestion.get("題型") == q_type:
                        matching_examples.append(ex)
                        break

    if matching_examples or fallback_examples:
        ex = rng.choice(matching_examples or fallback_examples)
        q = ex.get("question", ex)
        if isinstance(q, dict) and q.get("subquestions"):
            matching_subquestions = [
                subquestion
                for subquestion in q["subquestions"]
                if isinstance(subquestion, dict) and subquestion.get("題型") == q_type
            ]
            q = matching_subquestions[0] if matching_subquestions else q["subquestions"][0]
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

    subject_filter = getattr(params, "subject_filter", None)
    if subject_filter:
        subject_value = getattr(subject_filter, "value", subject_filter)
    else:
        subject_value = params.科目.value
    core_competencies = "、".join(c.value for c in params.核心素養)

    lc_explicit = bool(cfg and cfg.learning_content)
    lc_for_slot = cfg.learning_content if lc_explicit else params.學習內容_pool
    if lc_for_slot:
        lc_codes = "、".join(lc_for_slot)
        lc_detail_lines = "\n".join(
            f"  - {c}：{_LC_INSTRUCTIONS[c]}" for c in lc_for_slot if c in _LC_INSTRUCTIONS
        )
        if lc_explicit:
            lc_pool_lines = (
                f"- **指定學習內容（本小題務必使用下列指定學習內容，不得替換或新增）**："
                f"{lc_codes}\n{lc_detail_lines}\n"
            )
        else:
            lc_pool_lines = f"- **指定學習內容**：{lc_codes}\n{lc_detail_lines}\n"
    else:
        lc_pool_lines = "- **指定學習內容**：（依課綱自行選用）\n"

    lp_explicit = bool(cfg and cfg.learning_performance)
    lp_for_slot = cfg.learning_performance if lp_explicit else params.學習表現_pool
    if lp_for_slot:
        lp_codes = "、".join(lp_for_slot)
        lp_detail_lines = "\n".join(
            f"  - {c}：{_LP_INSTRUCTIONS[c]}" for c in lp_for_slot if c in _LP_INSTRUCTIONS
        )
        if lp_explicit:
            lp_pool_lines = (
                f"- **指定學習表現（本小題務必使用下列指定學習表現，不得替換或新增）**："
                f"{lp_codes}\n{lp_detail_lines}\n"
            )
        else:
            lp_pool_lines = f"- **指定學習表現**：{lp_codes}\n{lp_detail_lines}\n"
    else:
        lp_pool_lines = "- **指定學習表現**：（依課綱自行選用）\n"

    source_text = json.dumps(取材來源, ensure_ascii=False, indent=2)
    difficulty_section = _difficulty_section(params).lstrip("\n")
    config_parts = [f"題型={q_type}"]
    if cfg is not None and cfg.instruction:
        config_parts.append(f"出題指示={cfg.instruction}")
    if cfg is not None and cfg.learning_content:
        config_parts.append(f"學習內容={','.join(cfg.learning_content)}")
    if cfg is not None and cfg.learning_performance:
        config_parts.append(f"學習表現={','.join(cfg.learning_performance)}")
    # #319: the 小題's own image contract — 文本素材類型 decides whether an image
    # is required, 圖片生成模式 only decides how it is rendered. Gated exactly as
    # the 文本生成器 gates it (see `build_user_prompt`), so slots without any
    # 各小題配置 keep their previous prompt.
    has_structural_config = cfg is not None and any((
        cfg.question_type,
        cfg.instruction,
        cfg.content_type,
        cfg.image_generation_mode,
        cfg.question_word_limit,
        cfg.option_word_limit,
        cfg.learning_content,
        cfg.learning_performance,
    ))
    slot_content_type = (
        (cfg.content_type if cfg is not None else None) or params.題目內容類型 or "純文字"
    )
    slot_image_mode = (
        cfg.image_generation_mode if cfg is not None else None
    ) or image_generation_mode
    if has_structural_config:
        config_parts.append(f"文本素材類型={slot_content_type}")
        config_parts.append(f"圖片生成模式={slot_image_mode}")
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
    config_lines = [
        f"  - 第{sq_plan.get('序號', 1)}小題：" + "，".join(config_parts),
    ]
    if has_structural_config and slot_content_type in VISUAL_CONTENT_TYPES:
        config_lines.append(f"  - **小題圖片規則**：{SUBQUESTION_IMAGE_RULE}")
    subquestion_config_section = "## 各小題配置\n\n" + "\n".join(config_lines)
    return f"""\
請根據以下共用素材與小題規劃，生成一道108課綱社會領域素養導向小題：

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

- **年級重心**：{params.grade}年級（{_LEARNING_STAGE}）
- **情境**：{"、".join(c.value for c in params.情境)}
- **科目焦點**：{subject_value}
- **核心素養（限定使用）**：{core_competencies}
{lc_pool_lines}{lp_pool_lines}
{difficulty_section}
## 參考範例

{few_shot_text}

## 重要提醒

1. 只撰寫序號 {sq_plan.get("序號", 1)} 的一道小題。
2. 小題必須能依據共用文本作答，不要引入無法由文本支持的新情境。
3. `學習內容` / `學習表現` 應優先使用上述指定代號；如需引入其他代號，仍以系統提供的課綱資料為限。
4. 題型必須符合本小題規劃中的 `題型`，出題概念需回應規劃中的能力提示。
5. **誘答分析**：本小題若為 `選擇題`，`誘答分析` **必須**同時涵蓋題目所有選項標籤（A/B/C/D）；正確選項填「正確答案：…」，其餘選項描述其針對的錯誤概念。若為 `封閉式建構反應題` 或 `開放式建構反應題`，可留空 `{{}}` 或使用 `{{"常見錯誤": "..."}}` 描述一項最常見錯誤。
6. 請只輸出一道小題的 JSON，不要輸出其他文字。
""", all_image_paths
