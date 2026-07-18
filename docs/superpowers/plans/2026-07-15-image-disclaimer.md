# Image Disclaimer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append the exact string 「圖片僅為示意，非完全等比例繪製」 to every prompt fragment that can cause an image to be rendered (math + social studies + natural sciences content-type blocks and HTML-designer guidance), and add one matching leniency line to every verifier so verifiers stop failing questions purely because the rendered figure is not to scale.

**Architecture:** Additive change — introduce a single shared constant `IMAGE_DISCLAIMER` in `src/common/image_disclaimer.py` and import it into the three `context_builder.py` files (math / social studies / natural sciences) so `CONTENT_TYPE_INSTRUCTIONS["含圖片"]`, `CONTENT_TYPE_INSTRUCTIONS["graphs/charts/tables"]` and the `render_mode: "html"` guidance block in each `SYSTEM_PROMPT_TEMPLATE` interpolate the disclaimer verbatim. The three `verifier.py` files import the same constant and inject one 示意圖 leniency line into `_VERIFICATION_SYSTEM_PROMPT_CORE`. No behaviour outside prompt strings changes.

**Tech Stack:** Python 3.11+, Pydantic (unchanged), pytest via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-07-15-image-disclaimer-design.md`

## Global Constraints

- The disclaimer phrase is defined **exactly once** as `IMAGE_DISCLAIMER = "圖片僅為示意，非完全等比例繪製"` in `src/common/image_disclaimer.py`; every prompt fragment interpolates that constant so tests can import it.
- Every location that can cause an image to be rendered must contain the phrase: `CONTENT_TYPE_INSTRUCTIONS["含圖片"]` and `CONTENT_TYPE_INSTRUCTIONS["graphs/charts/tables"]` for **all three** subjects, plus the `render_mode: "html"` HTML-designer guidance block in math and social studies system prompts (natural sciences has no separate HTML block — its `CONTENT_TYPE_INSTRUCTIONS` covers the html reference).
- `CONTENT_TYPE_INSTRUCTIONS["純文字"]` must **not** contain the disclaimer phrase — text-only questions never render an image.
- The HTML-designer guidance must instruct the generator to place the disclaimer as a caption line inside the figure where layout allows (via `chart_spec.description`); no post-processing of already-generated output.
- Each verifier's `_VERIFICATION_SYSTEM_PROMPT_CORE` (math / social studies / natural sciences) gets a single 示意圖 leniency line: verifiers must not fail a question solely because the rendered figure is not to scale, but must still fail on wrong data values / labels.
- No retroactive updates to already-generated questions; no changes to `題目` array post-processing; no schema changes.
- All Chinese identifiers stay in Chinese (核心問題, 學習內容, 出題指示, etc.).
- All Python commands run from repo root `/workspace/exam-generation/`.

---

### Task 1: Add the shared `IMAGE_DISCLAIMER` constant

**Files:**
- Create: `src/common/image_disclaimer.py`
- Create: `tests/test_image_disclaimer_constant.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `IMAGE_DISCLAIMER: str` — verbatim disclaimer text imported by Tasks 2–5.

- [ ] **Step 1: Write the failing test**

Create `tests/test_image_disclaimer_constant.py`:

```python
"""Contract test for the single-source-of-truth image disclaimer constant."""

from __future__ import annotations

from src.common.image_disclaimer import IMAGE_DISCLAIMER


def test_image_disclaimer_is_verbatim_traditional_chinese() -> None:
    assert IMAGE_DISCLAIMER == "圖片僅為示意，非完全等比例繪製"
    assert isinstance(IMAGE_DISCLAIMER, str)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_image_disclaimer_constant.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.common.image_disclaimer'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/common/image_disclaimer.py`:

```python
"""Single source of truth for the exam-image "figure is illustrative" disclaimer.

Every prompt fragment that can cause an image to be rendered — math /
social-studies / natural-sciences content-type blocks, the `render_mode: "html"`
HTML-designer guidance, and the three verifier system prompts — imports this
constant so the phrase is defined verbatim in exactly one place. Tests import
it too, so a future rewording only needs to happen here.
"""

from __future__ import annotations

IMAGE_DISCLAIMER: str = "圖片僅為示意，非完全等比例繪製"

__all__ = ["IMAGE_DISCLAIMER"]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_image_disclaimer_constant.py -q`
Expected: PASS — 1 test.

- [ ] **Step 5: Commit**

```bash
git add src/common/image_disclaimer.py tests/test_image_disclaimer_constant.py
git commit -m "feat(common): add IMAGE_DISCLAIMER shared constant (#107)"
```

---

### Task 2: Wire the disclaimer into the math context builder

**Files:**
- Modify: `src/context_builder.py` (import + `CONTENT_TYPE_INSTRUCTIONS` dict at lines 53–69 + `render_mode: "html"` block inside `SYSTEM_PROMPT_TEMPLATE` at lines 127–137)
- Create: `tests/test_math_context_builder.py`

**Interfaces:**
- Consumes: `IMAGE_DISCLAIMER` from `src.common.image_disclaimer` (Task 1).
- Produces: math `CONTENT_TYPE_INSTRUCTIONS["含圖片"]` and `["graphs/charts/tables"]` contain the phrase; `build_system_prompt()` output contains the phrase inside the HTML render-mode guidance; `CONTENT_TYPE_INSTRUCTIONS["純文字"]` does not.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_math_context_builder.py`:

```python
"""Math prompt must warn generators/solvers that figures are illustrative."""

from __future__ import annotations

import random
from pathlib import Path

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS,
    build_system_prompt,
    build_user_prompt,
)
from src.sampler import sample_params


def test_math_content_type_instructions_include_disclaimer_for_image_types() -> None:
    assert IMAGE_DISCLAIMER in CONTENT_TYPE_INSTRUCTIONS["含圖片"]
    assert IMAGE_DISCLAIMER in CONTENT_TYPE_INSTRUCTIONS["graphs/charts/tables"]


def test_math_content_type_instructions_omit_disclaimer_for_text_only() -> None:
    assert IMAGE_DISCLAIMER not in CONTENT_TYPE_INSTRUCTIONS["純文字"]


def test_math_html_designer_guidance_carries_disclaimer() -> None:
    prompt = build_system_prompt()
    # Phrase must appear inside the render_mode: "html" guidance block.
    assert 'render_mode: "html"' in prompt
    assert IMAGE_DISCLAIMER in prompt


def test_math_user_prompt_carries_disclaimer_when_content_type_is_image(
    tmp_path: Path,
) -> None:
    params = sample_params(seed=1, content_type="含圖片")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER in prompt


def test_math_user_prompt_omits_disclaimer_when_content_type_is_text(
    tmp_path: Path,
) -> None:
    params = sample_params(seed=1, content_type="純文字")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER not in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_math_context_builder.py -q`
Expected: FAIL — the four disclaimer assertions fail (constant is not yet interpolated into math prompts).

- [ ] **Step 3: Edit `src/context_builder.py`**

3a) Add the import next to the existing `src.common.*` imports (after line 20, before `from src.data_loader import ...`):

```python
from src.common.image_disclaimer import IMAGE_DISCLAIMER
```

3b) Replace the `CONTENT_TYPE_INSTRUCTIONS` dict literal (lines 53–69) with:

```python
CONTENT_TYPE_INSTRUCTIONS: dict[str, str] = {
    "純文字": (
        "本題目必須只使用純文字描述。不得輸出 `chart_spec`、`image_spec` 或任何需要渲染成圖片的資料；"
        "題目與解題分析只能依據文字內容。"
    ),
    "含圖片": (
        "本題目必須包含圖片或視覺示意素材（幾何圖形、示意圖、版面等）。"
        "請輸出 `chart_spec`，優先使用 `render_mode: \"html\"`，並在 `description` 與 `data` 中完整描述版面與內容。"
        f"（示意圖聲明）本題所有圖片皆為示意用途，非完全等比例繪製；"
        f"請在 `chart_spec.description` 中明確要求下游 HTML 產生器"
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
```

3c) Replace the `**HTML 示意圖（\`render_mode: "html"\`）**` block at lines 127–137 (the block that opens with `**HTML 示意圖（\`render_mode: "html"\`）**` and ends with `\`render_mode: "html"\` 的 \`description\` 請盡量詳細。如果題目不需要圖表，則不要包含 \`chart_spec\` 欄位。`) with:

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

`render_mode: "html"` 的 `description` 請盡量詳細。所有 `render_mode: "html"` 或 `render_mode: "chart"` 的圖片皆為示意用途、非完全等比例繪製，因此 `description` 中務必加入 caption 指示「{image_disclaimer}」；文字題不需要 `chart_spec` 欄位。
```

3d) Update the `SYSTEM_PROMPT_TEMPLATE.format(...)` call inside `build_system_prompt` (around lines 222–228) to pass the new placeholder:

```python
    return SYSTEM_PROMPT_TEMPLATE.format(
        learning_stage=stage,
        grade_range=grade_range,
        grade_names=grade_names,
        curriculum_section=curriculum_section,
        stage_code=sc,
        image_disclaimer=IMAGE_DISCLAIMER,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_math_context_builder.py tests/test_image_disclaimer_constant.py -q`
Expected: PASS — 6 tests total (1 constant + 5 math).

- [ ] **Step 5: Run the full math-touching suite for regressions**

Run: `uv run pytest tests/test_math_sampler.py tests/test_math_context_builder.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/context_builder.py tests/test_math_context_builder.py
git commit -m "feat(math): inject IMAGE_DISCLAIMER into content-type + HTML guidance (#107)"
```

---

### Task 3: Wire the disclaimer into the social-studies context builder

**Files:**
- Modify: `src/social_studies/context_builder.py` (import + `CONTENT_TYPE_INSTRUCTIONS` dict at lines 50–70 + `**HTML排版素材（\`render_mode: "html"\`）**` block at lines 181–189 inside `SYSTEM_PROMPT_TEMPLATE`)
- Modify: `tests/test_social_studies_context_builder.py` (add new tests)

**Interfaces:**
- Consumes: `IMAGE_DISCLAIMER` from `src.common.image_disclaimer` (Task 1).
- Produces: social-studies `CONTENT_TYPE_INSTRUCTIONS["含圖片"]` / `["graphs/charts/tables"]` and the html排版素材 guidance carry the phrase; `["純文字"]` does not. Both `build_user_prompt` (main pipeline) and `build_text_user_prompt` (文本生成器 stage) surface the phrase for image content types since both interpolate `CONTENT_TYPE_INSTRUCTIONS` (verified via `src/social_studies/context_builder.py:321` and `:708`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_social_studies_context_builder.py`:

```python
from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.social_studies.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as SS_CONTENT_TYPE_INSTRUCTIONS,
    build_system_prompt as ss_build_system_prompt,
)


def test_ss_content_type_instructions_include_disclaimer_for_image_types() -> None:
    assert IMAGE_DISCLAIMER in SS_CONTENT_TYPE_INSTRUCTIONS["含圖片"]
    assert IMAGE_DISCLAIMER in SS_CONTENT_TYPE_INSTRUCTIONS["graphs/charts/tables"]


def test_ss_content_type_instructions_omit_disclaimer_for_text_only() -> None:
    assert IMAGE_DISCLAIMER not in SS_CONTENT_TYPE_INSTRUCTIONS["純文字"]


def test_ss_html_designer_guidance_carries_disclaimer() -> None:
    prompt = ss_build_system_prompt()
    assert "HTML排版素材" in prompt
    assert IMAGE_DISCLAIMER in prompt


def test_ss_user_prompt_carries_disclaimer_for_image_content_type(tmp_path) -> None:
    import random
    from src.social_studies.context_builder import build_user_prompt
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=1, content_type="含圖片")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER in prompt


def test_ss_user_prompt_omits_disclaimer_for_text_only(tmp_path) -> None:
    import random
    from src.social_studies.context_builder import build_user_prompt
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=1, content_type="純文字")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER not in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_social_studies_context_builder.py -q -k disclaimer`
Expected: FAIL — the five new assertions fail (constant not yet in SS prompts).

- [ ] **Step 3: Edit `src/social_studies/context_builder.py`**

3a) Add the import next to the other `src.common.*` imports at the top of the file:

```python
from src.common.image_disclaimer import IMAGE_DISCLAIMER
```

3b) Replace the `CONTENT_TYPE_INSTRUCTIONS` dict literal (lines 50–70) with:

```python
CONTENT_TYPE_INSTRUCTIONS: dict[str, str] = {
    "純文字": (
        "本題組必須只使用純連續文本素材。不得輸出 `chart_spec`、`image_spec` 或任何需要渲染成圖片的資料；"
        "題目與答案解析只能依據 `文本` 欄位中的文字內容。"
    ),
    "含圖片": (
        "本題組必須包含圖片式或視覺式非連續素材，例如地圖、圖解、廣告、表單、海報或網頁畫面。"
        "請在題組頂層輸出非 null 的 `chart_spec`，優先使用 `render_mode: \"html\"`，"
        "並在 `description` 與 `data` 中完整描述版面與內容。"
        "（重要）圖片必須是作答的必要條件：至少一道小題的答案必須直接依賴圖片中才有的資訊，無法僅憑文本回答。"
        "設計時請先確定「移除圖片後此題是否仍可作答」——若可以，請重新設計圖片，使其承載文本中未涵蓋的關鍵資訊"
        "（例如地圖上的地名/路線/分布、廣告上的價格/期限/規則、表單上的數據欄位）。"
        f"（示意圖聲明）圖片為示意用途，非完全等比例繪製；請在 `chart_spec.description` 中要求下游 HTML 產生器"
        f"將「{IMAGE_DISCLAIMER}」以 caption 呈現在圖片下緣或版面空白處。"
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
```

3c) Replace the `**HTML排版素材（\`render_mode: "html"\`）**` block (lines 181–189) with:

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
```

3d) Update the `SYSTEM_PROMPT_TEMPLATE.format(...)` call inside `build_system_prompt` (search for the sole `SYSTEM_PROMPT_TEMPLATE.format` in this file, around line 260–275) to add the new placeholder:

```python
        curriculum_section=curriculum_section,
        stage_code=sc,
        image_disclaimer=IMAGE_DISCLAIMER,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_social_studies_context_builder.py -q`
Expected: PASS — all existing tests plus the 5 new disclaimer tests.

- [ ] **Step 5: Regression check the corrector + few-shot suites (they import CONTENT_TYPE_INSTRUCTIONS transitively via context_builder)**

Run: `uv run pytest tests/test_social_studies_context_builder.py tests/test_social_studies_corrector.py tests/test_social_studies_few_shot.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/social_studies/context_builder.py tests/test_social_studies_context_builder.py
git commit -m "feat(social_studies): inject IMAGE_DISCLAIMER into content-type + HTML排版素材 guidance (#107)"
```

---

### Task 4: Wire the disclaimer into the natural-sciences context builder

**Files:**
- Modify: `src/natural_sciences/context_builder.py` (import + `CONTENT_TYPE_INSTRUCTIONS` dict at lines 74–93)
- Modify: `tests/test_natural_sciences_context_builder.py` (add new tests)

**Interfaces:**
- Consumes: `IMAGE_DISCLAIMER` from `src.common.image_disclaimer` (Task 1).
- Produces: natural-sciences `CONTENT_TYPE_INSTRUCTIONS["含圖片"]` and `["graphs/charts/tables"]` contain the phrase; `["純文字"]` does not. NS has no separate `**HTML示意/排版素材**` block inside `SYSTEM_PROMPT_TEMPLATE` (verified — the html reference only lives inside `CONTENT_TYPE_INSTRUCTIONS`), so only the dict needs editing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_natural_sciences_context_builder.py`:

```python
from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.natural_sciences.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as NS_CONTENT_TYPE_INSTRUCTIONS,
)


def test_ns_content_type_instructions_include_disclaimer_for_image_types() -> None:
    assert IMAGE_DISCLAIMER in NS_CONTENT_TYPE_INSTRUCTIONS["含圖片"]
    assert IMAGE_DISCLAIMER in NS_CONTENT_TYPE_INSTRUCTIONS["graphs/charts/tables"]


def test_ns_content_type_instructions_omit_disclaimer_for_text_only() -> None:
    assert IMAGE_DISCLAIMER not in NS_CONTENT_TYPE_INSTRUCTIONS["純文字"]


def test_ns_user_prompt_carries_disclaimer_for_image_content_type(tmp_path) -> None:
    import random
    from src.natural_sciences.context_builder import build_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=1, content_type="含圖片")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER in prompt


def test_ns_user_prompt_carries_disclaimer_for_graphs_charts_tables(tmp_path) -> None:
    import random
    from src.natural_sciences.context_builder import build_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=1, content_type="graphs/charts/tables")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER in prompt


def test_ns_user_prompt_omits_disclaimer_for_text_only(tmp_path) -> None:
    import random
    from src.natural_sciences.context_builder import build_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=1, content_type="純文字")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert IMAGE_DISCLAIMER not in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_natural_sciences_context_builder.py -q -k disclaimer`
Expected: FAIL — the 5 new assertions fail.

- [ ] **Step 3: Edit `src/natural_sciences/context_builder.py`**

3a) Add the import next to the other `src.common.*` imports at the top of the file:

```python
from src.common.image_disclaimer import IMAGE_DISCLAIMER
```

3b) Replace the `CONTENT_TYPE_INSTRUCTIONS` dict literal (lines 74–93) with:

```python
CONTENT_TYPE_INSTRUCTIONS: dict[str, str] = {
    "純文字": (
        "本題組必須只使用文字素材。不得輸出 `chart_spec` 或任何需要渲染成圖片的資料；"
        "題目、答案與解釋只能依據 `文本` 欄位中的文字、數據描述或實驗敘述。"
    ),
    "含圖片": (
        "本題組必須包含視覺式科學素材，例如實驗裝置圖、模型圖、流程圖、標籤圖、"
        "地圖或情境示意圖。請輸出 `chart_spec`，優先使用 `render_mode: \"html\"`，"
        "並在 `description` 與 `data` 中完整描述版面與作答所需元素。"
        "（重要）圖片必須是作答的必要條件：至少一道小題的答案必須直接依賴圖片中才有的資訊，無法僅憑文本回答。"
        "設計時請先確定「移除圖片後此題是否仍可作答」——若可以，請重新設計圖片，使其承載文本中未涵蓋的關鍵資訊"
        "（例如實驗裝置的連接方式、模型圖的標示數據、流程圖的條件分支）。"
        f"（示意圖聲明）圖片為示意用途，非完全等比例繪製；請在 `chart_spec.description` 中要求下游 HTML 產生器"
        f"將「{IMAGE_DISCLAIMER}」以 caption 呈現在圖片下緣或版面空白處。"
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_natural_sciences_context_builder.py -q`
Expected: PASS — all existing tests plus the 5 new disclaimer tests.

- [ ] **Step 5: Regression check the natural-sciences few-shot suite**

Run: `uv run pytest tests/test_natural_sciences_context_builder.py tests/test_natural_sciences_few_shot.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/natural_sciences/context_builder.py tests/test_natural_sciences_context_builder.py
git commit -m "feat(natural_sciences): inject IMAGE_DISCLAIMER into content-type guidance (#107)"
```

---

### Task 5: Add the 示意圖 leniency line to all three verifiers

**Files:**
- Modify: `src/verifier.py` (`_VERIFICATION_SYSTEM_PROMPT_CORE` at lines 20–51)
- Modify: `src/social_studies/verifier.py` (`_VERIFICATION_SYSTEM_PROMPT_CORE` at lines 13–49)
- Modify: `src/natural_sciences/verifier.py` (`_VERIFICATION_SYSTEM_PROMPT_CORE` at lines 18–53)
- Create: `tests/test_math_verifier.py`
- Modify: `tests/test_social_studies_verifier.py` (add new test)
- Create: `tests/test_natural_sciences_verifier.py`

**Interfaces:**
- Consumes: `IMAGE_DISCLAIMER` from `src.common.image_disclaimer` (Task 1); public `VERIFICATION_SYSTEM_PROMPT` symbol re-exported by each verifier module.
- Produces: each verifier's `VERIFICATION_SYSTEM_PROMPT` contains a single leniency line stating the figure is 示意圖, must not fail purely on scale, but must still fail on wrong data values / labels.

- [ ] **Step 1: Write the failing tests**

1a) Create `tests/test_math_verifier.py`:

```python
"""Math verifier must not fail a question purely because the figure is 示意圖."""

from __future__ import annotations

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.verifier import VERIFICATION_SYSTEM_PROMPT


def test_math_verifier_prompt_contains_illustrative_figure_leniency_line() -> None:
    assert "示意圖" in VERIFICATION_SYSTEM_PROMPT
    assert IMAGE_DISCLAIMER in VERIFICATION_SYSTEM_PROMPT
    # Both halves of the leniency contract must be present.
    assert "不得僅因" in VERIFICATION_SYSTEM_PROMPT
    assert "數值" in VERIFICATION_SYSTEM_PROMPT
    assert "標籤" in VERIFICATION_SYSTEM_PROMPT
```

1b) Append to `tests/test_social_studies_verifier.py`:

```python
def test_social_studies_verifier_prompt_contains_illustrative_figure_leniency_line() -> None:
    from src.common.image_disclaimer import IMAGE_DISCLAIMER

    assert "示意圖" in VERIFICATION_SYSTEM_PROMPT
    assert IMAGE_DISCLAIMER in VERIFICATION_SYSTEM_PROMPT
    assert "不得僅因" in VERIFICATION_SYSTEM_PROMPT
    assert "數值" in VERIFICATION_SYSTEM_PROMPT
    assert "標籤" in VERIFICATION_SYSTEM_PROMPT
```

1c) Create `tests/test_natural_sciences_verifier.py`:

```python
"""Natural-sciences verifier must not fail a question purely because the figure is 示意圖."""

from __future__ import annotations

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.natural_sciences.verifier import VERIFICATION_SYSTEM_PROMPT


def test_natural_sciences_verifier_prompt_contains_illustrative_figure_leniency_line() -> None:
    assert "示意圖" in VERIFICATION_SYSTEM_PROMPT
    assert IMAGE_DISCLAIMER in VERIFICATION_SYSTEM_PROMPT
    assert "不得僅因" in VERIFICATION_SYSTEM_PROMPT
    assert "數值" in VERIFICATION_SYSTEM_PROMPT
    assert "標籤" in VERIFICATION_SYSTEM_PROMPT
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_math_verifier.py tests/test_natural_sciences_verifier.py tests/test_social_studies_verifier.py -q -k illustrative_figure`
Expected: FAIL — 3 tests fail because none of the three verifier prompts mentions 示意圖 or the disclaimer yet.

- [ ] **Step 3: Edit `src/verifier.py`**

3a) Add the import next to the other `src.*` imports at the top:

```python
from src.common.image_disclaimer import IMAGE_DISCLAIMER
```

3b) Replace the assignment of `_VERIFICATION_SYSTEM_PROMPT_CORE` (lines 20–51) — insert the new leniency line as an f-string interpolation just before the closing `"""`, immediately after the `chart_verification` JSON schema block and before `若題目未附圖表圖片，請省略 chart_verification 欄位。只輸出 JSON，不要輸出其他文字。`:

```python
_VERIFICATION_SYSTEM_PROMPT_CORE = f"""\
你是一位數學教師，負責審核考試題目的正確性。你會收到一道數學題目，請你：

1. 完全獨立地解這道題目（不要看提供的解答）。
2. 將你的解答與提供的解答進行比較。
3. 檢查是否有以下問題：
   - 數學計算錯誤
   - 邏輯推理錯誤
   - 答案不一致
   - 選項設計不合理（例如正確答案不在選項中）
   - 題目敘述有歧義或矛盾
4. 如果提供了圖表圖片，請一併檢查圖表是否正確呈現題目所描述的數據。

## 示意圖判讀原則

附上的圖表為示意圖（{IMAGE_DISCLAIMER}）。不得僅因圖形比例、線段長度、角度、軸距或版面留白不完全符合實際尺寸而判定 failed；但若圖表中的數值、標籤、單位、分類、資料點或關鍵標示錯誤，或與題目描述矛盾，仍應判定 failed。

請以 JSON 格式回覆：

```json
{{
  "my_answer": "你獨立解題的答案",
  "provided_answer": "題目提供的答案",
  "answer_match": true/false,
  "passed": true/false,
  "details": "詳細說明（如有錯誤，指出具體問題）",
  "chart_verification": {{
    "chart_data_match": true/false,
    "chart_labels_correct": true/false,
    "chart_details": "圖表檢查說明"
  }}
}}
```

若題目未附圖表圖片，請省略 chart_verification 欄位。只輸出 JSON，不要輸出其他文字。
"""
```

Note: converting the triple-quoted string to `f"""..."""` forces the two existing single-brace JSON schemas above to become `{{ ... }}` doubled braces so f-string parsing does not consume them — the shown replacement already doubles them.

- [ ] **Step 4: Edit `src/social_studies/verifier.py`**

4a) Add the import next to the other imports at the top:

```python
from src.common.image_disclaimer import IMAGE_DISCLAIMER
```

4b) Replace the assignment of `_VERIFICATION_SYSTEM_PROMPT_CORE` (lines 13–49). Convert to an f-string and add the same leniency section just before the `請以 JSON 格式回覆：` block:

```python
_VERIFICATION_SYSTEM_PROMPT_CORE = f"""\
你是一位108課綱社會領域素養導向命題審核教師，負責審核考試題組的可用性與明顯錯誤。你會收到一道題組，請你：

1. 完全獨立地閱讀文本素材並回答每一道小題（不要看提供的解答）。
2. 將你的解答與提供的解答進行比較。
3. 採取「寬鬆通過、只攔重大問題」的標準：
   - 如果提供的答案或解題分析能被文本合理支持，即使你的答案措辭不同，也應視為通過。
   - 開放式題目可有多種合理回答；只要評分規準（rubric）清楚、公平、能涵蓋合理答案，就應視為通過。
   - 小幅措辭、格式、詳略、誘答力不足但不影響作答的問題，請在 details 提醒，但不要因此判定 failed。
   - 只有在答案明顯無文本支持、與文本矛盾、選項正解不存在、題目嚴重歧義、評分規準缺失或不公平時，才判定 failed。
4. 如果提供了圖表圖片，請一併檢查圖表是否正確呈現素材。
   - 圖表或非連續文本有輕微標籤/排版問題但仍可理解時，請提醒但不要 failed。
   - 圖表資料明顯錯誤、缺少作答必要資訊，或與題目描述矛盾時，才 failed。

## 示意圖判讀原則

附上的圖表、地圖、圖解或版面素材為示意圖（{IMAGE_DISCLAIMER}）。不得僅因比例、路線曲度、地標位置或版面留白不完全符合實際尺寸而判定 failed；但若素材中的數值、標籤、單位、分類、圖例或關鍵標示錯誤，或與題目描述矛盾，仍應判定 failed。

answer_match 的判斷也請寬鬆：
- 若你的答案與提供答案語意相同、可由相同文本依據支持，或符合開放式題目的評分規準，請回傳 true。
- 只有當提供答案與你的獨立判讀有實質衝突，且無法被文本合理支持時，才回傳 false。

請以 JSON 格式回覆：

```json
{{
  "my_answer": "你獨立解題後各題的答案（逐題說明）",
  "provided_answer": "題目提供的答案摘要",
  "answer_match": true/false,
  "passed": true/false,
  "details": "詳細說明；若只是小幅改善建議，請明確寫出仍可通過",
  "chart_verification": {{
    "chart_data_match": true/false,
    "chart_labels_correct": true/false,
    "chart_details": "素材檢查說明"
  }}
}}
```

若題目未附圖表圖片，請省略 chart_verification 欄位。只輸出 JSON，不要輸出其他文字。
"""
```

- [ ] **Step 5: Edit `src/natural_sciences/verifier.py`**

5a) Add the import next to the other imports at the top:

```python
from src.common.image_disclaimer import IMAGE_DISCLAIMER
```

5b) Replace the assignment of `_VERIFICATION_SYSTEM_PROMPT_CORE` (lines 18–53). Convert to an f-string and insert the same leniency section before the `answer_match 的判斷也請寬鬆：` block:

```python
_VERIFICATION_SYSTEM_PROMPT_CORE = f"""\
你是一位 PISA Science 與108課綱自然科學領域命題審核教師，負責審核考試題組的可用性與明顯錯誤。你會收到一道題組，請你：

1. 完全獨立地閱讀科學情境素材並回答每一道小題（不要先看提供的解答）。
2. 將你的解答與提供的解答進行比較。
3. 檢查小題是否合理對應指定的 PISA Science 題型、科學能力、學習內容與學習表現。
4. 採取「寬鬆通過、只攔重大問題」的標準：
   - 如果提供的答案或解題分析能被素材與科學知識合理支持，即使措辭不同，也應視為通過。
   - 建構反應題可有多種合理回答；只要評分規準清楚、公平、能涵蓋合理答案，就應視為通過。
   - 小幅措辭、格式、誘答力不足但不影響作答的問題，請在 details 提醒，但不要因此判定 failed。
   - 只有在答案明顯無素材或科學依據、與素材矛盾、選項正解不存在、題目嚴重歧義、評分規準缺失或不公平時，才判定 failed。
5. 如果提供了圖表圖片，請檢查圖表是否正確呈現素材。

## 示意圖判讀原則

附上的實驗裝置圖、模型圖、流程圖、地圖或圖表為示意圖（{IMAGE_DISCLAIMER}）。不得僅因比例、線段長度、角度、儀器擺放位置或版面留白不完全符合實際尺寸而判定 failed；但若素材中的數值、標籤、單位、分類、圖例、條件分支或關鍵標示錯誤，或與題目描述矛盾，仍應判定 failed。

answer_match 的判斷也請寬鬆：
- 若你的答案與提供答案語意相同、可由相同素材與科學依據支持，或符合建構反應題評分規準，請回傳 true。
- 只有當提供答案與你的獨立判讀有實質衝突，且無法被素材合理支持時，才回傳 false。

請以 JSON 格式回覆：

```json
{{
  "my_answer": "你獨立解題後各題的答案（逐題說明）",
  "provided_answer": "題目提供的答案摘要",
  "answer_match": true/false,
  "passed": true/false,
  "details": "詳細說明；若只是小幅改善建議，請明確寫出仍可通過",
  "chart_verification": {{
    "chart_data_match": true/false,
    "chart_labels_correct": true/false,
    "chart_details": "素材檢查說明"
  }}
}}
```

若題目未附圖表圖片，請省略 chart_verification 欄位。只輸出 JSON，不要輸出其他文字。
"""
```

- [ ] **Step 6: Run the verifier tests to verify they pass**

Run: `uv run pytest tests/test_math_verifier.py tests/test_social_studies_verifier.py tests/test_natural_sciences_verifier.py -q`
Expected: PASS — all existing verifier tests plus the 3 new leniency-line tests.

- [ ] **Step 7: Run the full test suite for regressions**

Run: `uv run pytest -q`
Expected: PASS across the whole suite.

- [ ] **Step 8: Lint**

Run: `uv run ruff check src/ tests/`
Expected: no errors introduced by these changes (the three verifier files have module-level `# ruff: noqa: E501` where applicable; the math verifier does not, but the added Chinese line is short — if ruff reports a new E501, split the line at 「示意圖」 or apply a `# noqa: E501` inline).

- [ ] **Step 9: Commit**

```bash
git add src/verifier.py src/social_studies/verifier.py src/natural_sciences/verifier.py tests/test_math_verifier.py tests/test_social_studies_verifier.py tests/test_natural_sciences_verifier.py
git commit -m "feat(verifier): add 示意圖 leniency line to math/SS/NS verifiers (#107)"
```

---

## Requirement coverage cross-check

| Spec bullet | Task(s) |
|---|---|
| Single-source constant `IMAGE_DISCLAIMER = "圖片僅為示意，非完全等比例繪製"` | Task 1 |
| `src/context_builder.py` — `CONTENT_TYPE_INSTRUCTIONS["含圖片"]` & `["graphs/charts/tables"]` + `render_mode: "html"` HTML-designer block | Task 2 |
| `src/social_studies/context_builder.py` — same content-type blocks (global + text-generator stage flow) | Task 3 |
| `src/natural_sciences/context_builder.py` — same content-type blocks | Task 4 |
| `src/verifier.py`, `src/social_studies/verifier.py`, `src/natural_sciences/verifier.py` — one 示意圖 leniency line each | Task 5 |
| Test: each subject → 含圖片 & graphs/charts/tables prompt contains phrase; 純文字 absent | Tasks 2, 3, 4 |
| Test: HTML-designer prompt for `render_mode: "html"` contains the phrase | Tasks 2, 3 (NS has no separate block per file inspection) |
| Test: each verifier system prompt contains the not-to-scale leniency line | Task 5 |
| Out of scope — post-processing `題目` array | Explicitly not touched |
| Out of scope — retroactive updates | Explicitly not touched |
