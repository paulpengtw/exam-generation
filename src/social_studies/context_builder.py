"""Assemble LLM prompts for 108課綱 社會領域素養導向 question generation."""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.social_studies.curriculum_loader import (
    content_instructions,
    load_learning_content,
    load_learning_performance,
    load_performance_intro,
    performance_instructions,
)
from src.social_studies.data_loader import load_few_shot_example_groups
from src.social_studies.core_competency_loader import (
    competency_instructions,
    load_core_competencies,
    stage_code_for,
)
from src.social_studies.schema_loader import (
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

CONTENT_TYPE_INSTRUCTIONS: dict[str, str] = {
    "純文字": (
        "本題組必須只使用純連續文本素材。不得輸出 `chart_spec`、`image_spec` 或任何需要渲染成圖片的資料；"
        "題目與答案解析只能依據 `文本` 欄位中的文字內容。"
    ),
    "含圖片": (
        "本題組必須包含圖片式或視覺式非連續素材，例如地圖、圖解、廣告、表單、海報或網頁畫面。"
        "請輸出 `chart_spec`，優先使用 `render_mode: \"html\"`，並在 `description` 與 `data` 中完整描述版面與內容。"
    ),
    "graphs/charts/tables": (
        "本題組必須包含圖表或表格素材。統計圖（直方圖、折線圖、圓餅圖等）請使用 `render_mode: \"chart\"`；"
        "表格或複合資料表請使用 `render_mode: \"html\"`，並在 `data` 中提供完整欄列資料。"
    ),
}

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
  "subquestions": [
    {{
      "序號": 1,
      "年級": 7,
      "科目": ["地理"],
      "核心素養": ["社-J-A2"],
      "學習內容": [{{"編碼": "地Aa-Ⅳ-2", "說明": "全球海陸分布"}}],
      "學習表現": [{{"編碼": "社1b-Ⅳ-1", "說明": "應用社會領域內容知識解析生活經驗或社會現象"}}],
      "出題概念": "評量學生能否……",
      "題型": "選擇題",
      "題目": "問題一\n根據文章內容……\n（A）……\n（B）……\n（C）……\n（D）……",
      "答案": "A",
      "答案解析": "從圖1……",
      "評分規準": []
    }}
  ],
  "題目": ["（將文本和所有小題合併為陣列，供舊版驗證器使用）"],
  "正確解題分析": ["（逐題答案說明，供舊版驗證器使用）"],
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
請根據以下條件生成一道108課綱社會領域素養導向題組：

## 指定條件

- **年級重心**：{grade}年級（{learning_stage}）
- **科目焦點**：{subject}
- **情境**：{context}（PISA閱讀情境）
- **題型種類**：{set_type}
- **題型**：{q_type}
- **閱讀歷程（PISA）**：{reading_process}
- **文本形式**：{text_form}
- **題目內容類型**：{content_type}
- **核心素養（限定使用）**：{core_competencies}
{lc_pool_lines}{lp_pool_lines}{param_instructions}{user_materials}
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
    )


def build_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
    user_passage: str | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
) -> tuple[str, list[Path]]:
    if rng is None:
        rng = random.Random()

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
        ("題型", params.題型.value),
        ("文本形式", params.文本形式.value),
        ("科目", params.科目.value),
    ):
        instr = _INSTRUCTIONS.get(category, {}).get(key)
        if instr:
            param_instruction_lines.append(f"  - **{category}（{key}）補充**：{instr}")
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
    param_instruction_lines.append(f"  - **題目內容類型（{content_type}）補充**：{content_type_instr}")
    param_instructions = (
        "\n## 條件補充說明\n\n" + "\n".join(param_instruction_lines) + "\n"
        if param_instruction_lines else ""
    )

    example_groups = load_few_shot_example_groups(few_shot_dir)
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

    text = USER_PROMPT_TEMPLATE.format(
        grade=params.grade,
        learning_stage=_LEARNING_STAGE,
        subject=params.科目.value,
        context=topic_override or "、".join(c.value for c in params.情境),
        set_type=params.題型種類.value,
        q_type=params.題型.value,
        reading_process=reading_process,
        text_form=params.文本形式.value,
        content_type=content_type,
        core_competencies=core_competencies,
        lc_pool_lines=lc_pool_lines,
        lp_pool_lines=lp_pool_lines,
        param_instructions=param_instructions,
        user_materials=user_materials,
        few_shot_examples=few_shot_text,
    )
    return text, all_image_paths
