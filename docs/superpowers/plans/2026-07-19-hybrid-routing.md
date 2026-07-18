> **SUPERSEDED — 2026-07-19.** Split at operator request into four smaller
> per-subsystem plans that can execute independently after the foundation
> plan lands:
>
> - `docs/superpowers/plans/2026-07-19-hybrid-routing-01-foundation.md` — schema Literal + renderer dispatch + policy doc + parametric test rename
> - `docs/superpowers/plans/2026-07-19-hybrid-routing-02-math-prompt.md` — math docstring + `含圖片` instruction
> - `docs/superpowers/plans/2026-07-19-hybrid-routing-03-social-studies-prompt.md` — SS docstring + `含圖片` instruction
> - `docs/superpowers/plans/2026-07-19-hybrid-routing-04-natural-sciences-prompt.md` — NS docstring + `含圖片` instruction + whole-suite gate
>
> Do NOT execute the tasks below. The 9-task monolith is preserved for
> history / audit only; every step maps to a task in one of the four sub-plans.

---

# Hybrid Routing — `render_mode: "gpt_image"` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the operator-approved 2026-07-19 HYBRID routing decision from issue #110: extend the `render_mode` schema with a new `"gpt_image"` value, route the renderer to `LLMClient.generate_image()` for that value, and update `CONTENT_TYPE_INSTRUCTIONS` in all three subjects so the LLM emits `"gpt_image"` for realistic diagrams (maps, lab apparatus, biology, real-world-proportion geometry) while keeping `"html"` for structured/semantic illustrative content and tables.

**Architecture:** Additive schema extension — the Pydantic `render_mode` Literal in each `ImageSpec` grows from `["chart", "html"]` to `["chart", "html", "gpt_image"]`. `render_image()` gains one new dispatch branch (parallel to the existing chart/html branches) that calls the same `llm_client.generate_image()` code path the `image_generation_mode="gpt_image"` caller override already uses; that override is preserved unchanged. The three `CONTENT_TYPE_INSTRUCTIONS` tables are the only prompt-level change — they teach the LLM a per-family routing rule. Docstrings and the policy doc are updated in step. No renderer replacement, no removal of `"html"`, no schema field changes anywhere else.

**Tech Stack:** Python 3.11 + uv + pytest + pydantic 2 (`Literal` union extension); OpenAI SDK (`images.generate` via existing `LLMClient.generate_image()`); Playwright / matplotlib unchanged. No frontend or web changes in this plan.

**Issue:** https://github.com/paulpengtw/exam-generation/issues/110 (Part B implementation via HYBRID decision).

**Supersedes:** `docs/superpowers/plans/2026-07-18-frontend-ts-render-mode.md` Tasks 6-12 (marked SUPERSEDED via PR #148). Do NOT execute those tasks. The `frontend_ts` render mode is explicitly rejected.

## Global Constraints

- **Backward compatibility:** `"html"` and `"chart"` remain valid `render_mode` values and are dispatched exactly as they are today. Do NOT remove either. Already-generated `chart_spec` payloads with `render_mode: "html"` must continue to render via the LLM-HTML + Playwright path.
- **Caller override precedence unchanged:** the request-level `image_generation_mode` kwarg on `render_image()` still short-circuits when set to `"gpt_image"` (see `src/renderer.py:290-300`). The new `render_mode: "gpt_image"` is the LLM-driven spec-level choice, not a replacement for the caller override.
- **No new API keys or env vars.** `IMAGE_API_KEY` and `IMAGE_MODEL` (env, default `gpt-image-2-2026-04-21`) already exist for the existing `LLMClient.generate_image()` path.
- **No schema changes to `題目內容類型`.** The enum stays `純文字 / 含圖片 / graphs/charts/tables / customized`. The routing is encoded inside the LLM prompt instruction, not in a new content type.
- **Doc update-order rule (verbatim from CLAUDE.md):** update the policy first, then the docstrings, then the `CONTENT_TYPE_INSTRUCTIONS` tables. This plan orders tasks accordingly (Tasks 2 → 3 → 4-6).
- **Backend deps:** run `uv sync --extra web` once before any test run.
- **Testing:** all tests run from repo root with `uv run pytest <path> -v`. No web tests in this plan.
- **Lint scope:** pre-existing E501 / F401 noise in the repo is out of scope; introduce no new violations in files this plan touches.
- **Branch:** all work lives on `feat/110-hybrid-routing`, branched from the current `staging` HEAD (which must already contain PR #148, the docs-only HYBRID recording). Commit per task; do not push mid-plan.

---

### Task 1: Create the branch + failing schema tests

**Files:**
- Create: `tests/test_hybrid_routing_schema.py`

**Interfaces:**
- Consumes: `ImageSpec` from `src.schemas`, `src.social_studies.schemas`, `src.natural_sciences.schemas`.
- Produces: three subject-parametric tests that assert `ImageSpec(render_mode="gpt_image", ...)` validates. Currently fails because the Literal only allows `"chart"|"html"`.

- [ ] **Step 1: Verify staging has PR #148**

```bash
cd /workspace/exam-generation
git checkout staging && git pull
git log --oneline | grep -E "(#148|hybrid)" | head -3
```

Expected: at least one commit with the HYBRID recording is present. If not, stop and ask the operator.

- [ ] **Step 2: Create the branch**

```bash
cd /workspace/exam-generation
git checkout -b feat/110-hybrid-routing
uv sync --extra web
```

- [ ] **Step 3: Write the failing schema tests**

Create `tests/test_hybrid_routing_schema.py`:

```python
"""ImageSpec.render_mode must accept "gpt_image" across all three subjects (issue #110 HYBRID).

Source of truth: docs/figure-rendering-policy.md — Renderer selection matrix.
"""

from __future__ import annotations

import pytest

from src.natural_sciences.schemas import ImageSpec as NsImageSpec
from src.schemas import ImageSpec as MathImageSpec
from src.social_studies.schemas import ImageSpec as SsImageSpec


@pytest.mark.parametrize(
    "cls",
    [MathImageSpec, SsImageSpec, NsImageSpec],
    ids=["math", "social_studies", "natural_sciences"],
)
def test_imagespec_accepts_gpt_image_render_mode(cls) -> None:
    spec = cls(render_mode="gpt_image", description="示意圖")
    assert spec.render_mode == "gpt_image"


@pytest.mark.parametrize(
    "cls",
    [MathImageSpec, SsImageSpec, NsImageSpec],
    ids=["math", "social_studies", "natural_sciences"],
)
def test_imagespec_still_accepts_chart_and_html(cls) -> None:
    for mode in ("chart", "html"):
        spec = cls(render_mode=mode, description="示意圖")
        assert spec.render_mode == mode
```

- [ ] **Step 4: Run tests to verify the gpt_image test fails**

```bash
uv run pytest tests/test_hybrid_routing_schema.py -v
```

Expected: 3 tests FAIL with `pydantic.ValidationError` for `render_mode="gpt_image"`; the 3 backward-compat tests PASS.

- [ ] **Step 5: Commit the failing tests**

```bash
git add tests/test_hybrid_routing_schema.py
git commit -m "test: assert ImageSpec accepts render_mode gpt_image across 3 subjects (#110)"
```

---

### Task 2: Extend the three `ImageSpec.render_mode` Literals

**Files:**
- Modify: `src/schemas.py:56` — math `ImageSpec.render_mode`
- Modify: `src/social_studies/schemas.py:24` — SS `ImageSpec.render_mode`
- Modify: `src/natural_sciences/schemas.py:21` — NS `ImageSpec.render_mode`

**Interfaces:**
- Consumes: `Literal` from `typing` (already imported in each file).
- Produces: `render_mode: Literal["chart", "html", "gpt_image"] = "chart"` in all three ImageSpec classes; downstream code that reads `spec.get("render_mode")` sees `"gpt_image"` as a valid value.

- [ ] **Step 1: Extend math `ImageSpec.render_mode`**

`src/schemas.py:56` — replace the exact line:

```python
    render_mode: Literal["chart", "html"] = "chart"
```

with:

```python
    render_mode: Literal["chart", "html", "gpt_image"] = "chart"
```

- [ ] **Step 2: Extend SS `ImageSpec.render_mode`**

`src/social_studies/schemas.py:24` — replace the exact line the same way:

```python
    render_mode: Literal["chart", "html", "gpt_image"] = "chart"
```

- [ ] **Step 3: Extend NS `ImageSpec.render_mode`**

`src/natural_sciences/schemas.py:21` — replace the exact line the same way:

```python
    render_mode: Literal["chart", "html", "gpt_image"] = "chart"
```

- [ ] **Step 4: Run the Task 1 tests to verify they now pass**

```bash
uv run pytest tests/test_hybrid_routing_schema.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Run the full policy test file to check nothing regressed**

```bash
uv run pytest tests/test_figure_rendering_policy.py -v
```

Expected: existing tests continue to pass (this task does not touch `CONTENT_TYPE_INSTRUCTIONS`, only the schema).

- [ ] **Step 6: Commit**

```bash
git add src/schemas.py src/social_studies/schemas.py src/natural_sciences/schemas.py
git commit -m "feat(schema): add render_mode gpt_image to 3 ImageSpec Literals (#110)"
```

---

### Task 3: Renderer dispatch for `render_mode: "gpt_image"`

**Files:**
- Modify: `src/renderer.py:271-322` — `render_image()`
- Modify: `tests/test_figure_rendering_policy.py:82-160` — append one new dispatch test

**Interfaces:**
- Consumes: `LLMClient.generate_image(prompt, output_path)` (existing at `src/llm_client.py:452-496`); `_build_gpt_image_prompt(spec, question_text)` (existing at `src/renderer.py:325`).
- Produces: `render_image()` handles `render_mode == "gpt_image"` by calling `llm_client.generate_image()` — same code path as the existing `image_generation_mode == "gpt_image"` caller override, but triggered by spec content instead of a caller kwarg. The caller override remains and still short-circuits first.

- [ ] **Step 1: Write the failing dispatch test**

Append to `tests/test_figure_rendering_policy.py` (after `test_dispatch_gpt_image_mode_bypasses_render_mode` at line 135-153):

```python
def test_dispatch_gpt_image_render_mode_calls_llm_generate_image(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "diagram.png"
    result = renderer.render_image(
        {
            "render_mode": "gpt_image",
            "description": "簡易蒸餾裝置示意圖",
            "data": {"components": []},
        },
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        # caller does NOT override; spec-level render_mode drives the choice
        image_generation_mode="html",
    )

    assert result == str(out)
    assert html_renderer.calls == [], "html Playwright path must NOT be called"
    assert llm_client.html_calls == [], "LLM HTML-generation path must NOT be called"
    assert len(llm_client.image_calls) == 1, "generate_image must be called exactly once"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_figure_rendering_policy.py::test_dispatch_gpt_image_render_mode_calls_llm_generate_image -v
```

Expected: FAIL — likely `render_image` returns `None` and prints `Warning: unknown render_mode 'gpt_image'` (see the fallthrough at `src/renderer.py:321`).

- [ ] **Step 3: Add the new dispatch branch in `render_image()`**

`src/renderer.py` — locate the existing dispatch block starting at line 302 (`if render_mode == "chart":`). INSERT a new branch immediately BEFORE the `if render_mode == "chart":` block:

```python
    if render_mode == "gpt_image":
        if llm_client is None:
            print("  Warning: render_mode='gpt_image' requires LLMClient", file=sys.stderr)
            return None
        try:
            prompt = _build_gpt_image_prompt(image_spec, question_text)
            print("  Generating image via GPT image model (spec-driven)...", file=sys.stderr)
            return llm_client.generate_image(prompt, output_path)
        except Exception as e:
            print(f"  Warning: GPT image generation failed: {e}", file=sys.stderr)
            return None
```

The final block ordering must be: `image_generation_mode == "gpt_image"` caller-override branch (unchanged, line 290-300) → new `render_mode == "gpt_image"` branch (this task) → `render_mode == "chart"` branch → `render_mode == "html"` branch → unknown-mode warning fallthrough.

- [ ] **Step 4: Run the new dispatch test to verify it passes**

```bash
uv run pytest tests/test_figure_rendering_policy.py::test_dispatch_gpt_image_render_mode_calls_llm_generate_image -v
```

Expected: PASS.

- [ ] **Step 5: Run the full dispatch test suite to confirm no regression**

```bash
uv run pytest tests/test_figure_rendering_policy.py -v
```

Expected: all dispatch tests PASS (including `test_dispatch_chart_render_mode_uses_matplotlib`, `test_dispatch_html_render_mode_uses_playwright`, `test_dispatch_gpt_image_mode_bypasses_render_mode`, `test_dispatch_unknown_render_mode_returns_none`, and the new one).

- [ ] **Step 6: Commit**

```bash
git add src/renderer.py tests/test_figure_rendering_policy.py
git commit -m "feat(renderer): dispatch render_mode gpt_image to LLMClient.generate_image (#110)"
```

---

### Task 4: Update `docs/figure-rendering-policy.md` — routing rule table + CONTENT_TYPE_INSTRUCTIONS mapping

**Files:**
- Modify: `docs/figure-rendering-policy.md`

**Interfaces:**
- Consumes: the Renderer selection matrix section landed by PR #148 (already present in `## Renderer selection matrix`).
- Produces: two edits so the policy doc names `"gpt_image"` as a valid `render_mode` (matching the schema change in Task 2) and instructs the model to emit it for realistic illustrative figures. Enforcement bullets updated to name the tests added in Tasks 1 and 3.

- [ ] **Step 1: Update the routing-rule table under `## The rule`**

`docs/figure-rendering-policy.md` — locate the table header `| Figure family | Examples | `render_mode` | Renderer |` and its two data rows. REPLACE the illustrative-figures row (currently ends with `` `"html"` (or `"frontend_ts"` — see below) `` `LLM-HTML + Playwright ... `) with:

```markdown
| Illustrative figures — structured / semantic | 菜單, 情境卡, 廣告, 版面, 表單, 帶語意標註的表格 | `"html"` | LLM-HTML + Playwright (`src/renderer.py::_generate_html_via_llm` + `src/html_renderer.py`) |
| Illustrative figures — realistic diagram | 地圖 (含真實海岸線/經緯線), 實驗裝置, 生物模型/標籤圖, 需符合真實比例的幾何, 情境寫實圖 | `"gpt_image"` | OpenAI image API via `src/llm_client.py::generate_image` |
```

Remove the parenthetical `(or "frontend_ts" — see below)` (it references the superseded plan).

- [ ] **Step 2: Update the "What each subject's prompt must instruct" table**

Locate the table with header `| 題目內容類型 | Instruction MUST direct the model to |`. REPLACE the `含圖片` row and the `graphs/charts/tables` row with:

```markdown
| `含圖片` | Emit `chart_spec` with `render_mode: "gpt_image"` for realistic diagrams (maps, lab apparatus, biology, real-world-proportion geometry) and `render_mode: "html"` for structured/semantic content (menus, scenario cards, layouts, forms). |
| `graphs/charts/tables` | Emit `chart_spec` with `render_mode: "chart"` for statistical charts; `render_mode: "html"` for tables and semantic-overlay charts. |
```

- [ ] **Step 3: Update the Enforcement section**

Locate the `## Enforcement` section. REPLACE the `test_illustrative_content_routes_to_html` bullet with (do not touch the other two):

```markdown
- `tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec`,
  `::test_illustrative_content_routes_to_gpt_image_or_html`, and
  `::test_quantitative_content_routes_to_chart_and_html_for_tables` assert the
  `CONTENT_TYPE_INSTRUCTIONS` strings for each of the three subjects contain
  the correct `render_mode: "…"` fragment.
```

APPEND one new dispatch bullet to the Enforcement list:

```markdown
- `tests/test_figure_rendering_policy.py::test_dispatch_gpt_image_render_mode_calls_llm_generate_image`
  asserts `render_mode: "gpt_image"` routes to `LLMClient.generate_image()`.
- `tests/test_hybrid_routing_schema.py::test_imagespec_accepts_gpt_image_render_mode`
  asserts the schema Literal accepts `"gpt_image"` across all three subjects.
```

- [ ] **Step 4: Verify the doc changes**

```bash
grep -c '"gpt_image"' docs/figure-rendering-policy.md
```

Expected: at least 4 occurrences (routing rule table row, CONTENT_TYPE_INSTRUCTIONS mapping row for 含圖片, enforcement bullets).

```bash
grep 'frontend_ts' docs/figure-rendering-policy.md
```

Expected: zero matches (the parenthetical reference to the superseded plan is removed).

- [ ] **Step 5: Commit**

```bash
git add docs/figure-rendering-policy.md
git commit -m "docs(policy): route realistic illustrative figures to gpt_image (#110)"
```

---

### Task 5: Update the three `context_builder.py` module docstrings

**Files:**
- Modify: `src/context_builder.py:1-8` — math module docstring
- Modify: `src/social_studies/context_builder.py:1-10` — SS module docstring
- Modify: `src/natural_sciences/context_builder.py:2-10` — NS module docstring (keep `# ruff: noqa: E501` at line 1)

**Interfaces:**
- Consumes: the policy wording finalized in Task 4.
- Produces: docstrings that name `"gpt_image"` alongside `"chart"` and `"html"`, matching the schema Literal from Task 2 and preparing the reader for Task 6's `CONTENT_TYPE_INSTRUCTIONS` update.

- [ ] **Step 1: Replace math module docstring**

`src/context_builder.py:1-8` — replace the entire existing module docstring with:

```python
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
```

- [ ] **Step 2: Replace social-studies module docstring**

`src/social_studies/context_builder.py:1-10` — replace with:

```python
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
```

- [ ] **Step 3: Replace natural-sciences module docstring**

`src/natural_sciences/context_builder.py` — keep line 1 (`# ruff: noqa: E501`) intact and replace lines 2-10 with:

```python
"""Assemble LLM prompts for PISA Science + 108課綱自然科學 question generation.

Figure routing: any `chart_spec` this module instructs the model to emit
must follow the rule in ``docs/figure-rendering-policy.md`` —
precise/quantitative statistical charts use ``render_mode: "chart"``
(matplotlib); structured data tables and semantic-overlay figures use
``render_mode: "html"`` (LLM-HTML + Playwright); realistic diagrams (實驗裝置圖,
模型圖, 標籤圖, 生物剖面, 地圖) use ``render_mode: "gpt_image"`` (OpenAI image
API). See ``CONTENT_TYPE_INSTRUCTIONS`` below for the per-``題目內容類型`` mapping.
"""
```

- [ ] **Step 4: Run the docstring-guard test (if it exists) to confirm the policy citation still parses**

```bash
uv run pytest tests/test_context_builder_docstrings.py -v 2>&1 | tail -20
```

Expected: PASS. If the file does not exist in the current tree, skip this step and note it in the commit message.

- [ ] **Step 5: Commit**

```bash
git add src/context_builder.py src/social_studies/context_builder.py src/natural_sciences/context_builder.py
git commit -m "docs: cite gpt_image render_mode in context-builder docstrings (#110)"
```

---

### Task 6: Update math `CONTENT_TYPE_INSTRUCTIONS` and its policy test

**Files:**
- Modify: `tests/test_figure_rendering_policy.py:34-40` — rewrite `test_illustrative_content_routes_to_html`
- Modify: `src/context_builder.py:68-74` — math `含圖片` instruction

**Interfaces:**
- Consumes: the policy wording from Task 4 and the docstring from Task 5.
- Produces: the math `含圖片` instruction that teaches the LLM to pick `render_mode` per figure family. Later subject tasks (7, 8) parametrize the same test to check SS and NS in one shot; this task rewrites the test to accept BOTH `render_mode: "gpt_image"` and `render_mode: "html"` in the illustrative instruction and asserts the routing keywords are present.

- [ ] **Step 1: Rewrite the existing `test_illustrative_content_routes_to_html`**

`tests/test_figure_rendering_policy.py` — replace the entire body of `test_illustrative_content_routes_to_html` (lines 34-40) with a renamed test that enforces both routing targets:

```python
@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_illustrative_content_routes_to_gpt_image_or_html(
    subject: str, table: dict
) -> None:
    """含圖片 must route realistic diagrams to gpt_image and structured/semantic to html."""
    assert "含圖片" in table
    text = table["含圖片"]
    assert 'render_mode: "gpt_image"' in text, (
        f"{subject}: 含圖片 instruction must direct realistic diagrams to "
        f'render_mode: "gpt_image"'
    )
    assert 'render_mode: "html"' in text, (
        f"{subject}: 含圖片 instruction must direct structured/semantic content to "
        f'render_mode: "html"'
    )
```

- [ ] **Step 2: Run all three parametric tests to confirm they now fail for every subject**

```bash
uv run pytest tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html -v
```

Expected: 3 tests FAIL — each subject's `含圖片` instruction currently mentions only `render_mode: "html"`.

- [ ] **Step 3: Update math `含圖片` instruction**

`src/context_builder.py` — locate the `"含圖片"` key inside `CONTENT_TYPE_INSTRUCTIONS` (starts at line 68). REPLACE the current value tuple (lines 68-74) with:

```python
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
```

- [ ] **Step 4: Run the math variant of the new test**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[math]' -v
```

Expected: PASS. The SS and NS variants still FAIL — they land in Tasks 7 and 8.

- [ ] **Step 5: Confirm the plain-text and quantitative tests still pass for math**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec[math]' 'tests/test_figure_rendering_policy.py::test_quantitative_content_routes_to_chart_and_html_for_tables[math]' -v
```

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add src/context_builder.py tests/test_figure_rendering_policy.py
git commit -m "feat(math prompt): route 含圖片 realistic diagrams to gpt_image, structured to html (#110)"
```

---

### Task 7: Update social-studies `CONTENT_TYPE_INSTRUCTIONS`

**Files:**
- Modify: `src/social_studies/context_builder.py:67-76` — SS `含圖片` instruction

**Interfaces:**
- Consumes: the renamed parametric test from Task 6.
- Produces: the SS `含圖片` instruction with the same routing shape as math (Task 6), phrased for 108課綱 社會領域 素材 vocabulary (地圖, 廣告, 表單, 海報, etc.).

- [ ] **Step 1: Update SS `含圖片` instruction**

`src/social_studies/context_builder.py` — locate the `"含圖片"` key inside `CONTENT_TYPE_INSTRUCTIONS` (starts at line 67). REPLACE the current value tuple (lines 67-76) with:

```python
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
```

- [ ] **Step 2: Run the SS variants of the parametric tests**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[social_studies]' 'tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec[social_studies]' 'tests/test_figure_rendering_policy.py::test_quantitative_content_routes_to_chart_and_html_for_tables[social_studies]' -v
```

Expected: all 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add src/social_studies/context_builder.py
git commit -m "feat(SS prompt): route 含圖片 realistic diagrams to gpt_image, structured to html (#110)"
```

---

### Task 8: Update natural-sciences `CONTENT_TYPE_INSTRUCTIONS`

**Files:**
- Modify: `src/natural_sciences/context_builder.py:123-132` — NS `含圖片` instruction

**Interfaces:**
- Consumes: the renamed parametric test from Task 6.
- Produces: the NS `含圖片` instruction with the same routing shape as math/SS, phrased for PISA-Science + 108課綱 自然科學 素材 vocabulary (實驗裝置圖, 標籤圖, 模型圖, 流程圖).

- [ ] **Step 1: Update NS `含圖片` instruction**

`src/natural_sciences/context_builder.py` — locate the `"含圖片"` key inside `CONTENT_TYPE_INSTRUCTIONS` (starts at line 123). REPLACE the current value tuple (lines 123-132) with:

```python
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
```

- [ ] **Step 2: Run the NS variants of the parametric tests**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[natural_sciences]' 'tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec[natural_sciences]' 'tests/test_figure_rendering_policy.py::test_quantitative_content_routes_to_chart_and_html_for_tables[natural_sciences]' -v
```

Expected: all 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add src/natural_sciences/context_builder.py
git commit -m "feat(NS prompt): route 含圖片 realistic diagrams to gpt_image, structured to html (#110)"
```

---

### Task 9: Whole-suite gate + branch validation

**Files:** none modified.

**Interfaces:** ensures no plan step introduced a regression outside the touched files.

- [ ] **Step 1: Run the full non-server test suite**

```bash
uv run pytest tests/ -v --ignore=tests/server 2>&1 | tail -30
```

Expected: PASS. Baseline is the same set that was green on staging before this plan started; the only allowed deltas are the newly added assertions from Tasks 1, 3, 6.

- [ ] **Step 2: Run the server-adjacent tests too**

```bash
uv run pytest tests/server -v 2>&1 | tail -20
```

Expected: PASS (this plan does not touch `server/`).

- [ ] **Step 3: Lint the files touched by this plan**

```bash
uv run ruff check src/schemas.py src/social_studies/schemas.py src/natural_sciences/schemas.py src/renderer.py src/context_builder.py src/social_studies/context_builder.py src/natural_sciences/context_builder.py tests/test_figure_rendering_policy.py tests/test_hybrid_routing_schema.py
```

Expected: no NEW violations in these files. Pre-existing E501/F401 on other lines within these files is out of scope; do not fix unrelated hits in this plan.

- [ ] **Step 4: Confirm the superseded plan doc is untouched**

```bash
head -5 docs/superpowers/plans/2026-07-18-frontend-ts-render-mode.md
```

Expected: the `SUPERSEDED 2026-07-18` banner is still there. Do not remove or edit it in this plan.

- [ ] **Step 5: Confirm the doc-first order was preserved**

```bash
git log --oneline feat/110-hybrid-routing ^staging
```

Expected order of the 8 commits (bottom to top):
1. test (Task 1 — failing schema tests)
2. feat(schema) (Task 2 — schema Literal extension)
3. feat(renderer) (Task 3 — dispatch)
4. docs(policy) (Task 4 — policy doc)
5. docs (Task 5 — context-builder docstrings)
6. feat(math prompt) (Task 6 — math instruction + test rename)
7. feat(SS prompt) (Task 7)
8. feat(NS prompt) (Task 8)

- [ ] **Step 6: DO NOT PUSH.**

Handoff to the operator: report the commit list and wait for explicit push instruction. Do not open a PR as part of this plan.

---

## Deferred / not in this plan

- **Web frontend edits.** The web form's per-小題 `image_generation_mode` selector already exists as an override; no new UI value is needed since routing is now spec-driven. If the operator later wants to expose the new render_mode value to power users as an explicit override, that is a separate plan.
- **`server/utility/routes.py` schema exposure.** The API's `/api/schemas` endpoint does not currently surface `render_mode` — no server-side change is required by this plan. If a future task adds a schema echo, it should include `"gpt_image"` at that time.
- **Census gate.** The ≥30-real-production-questions-per-subject census gate (`docs/figure-rendering-policy.md` Phase A outcome) remains unmet and is explicitly labelled provisional in the HYBRID entry. Revisiting the gate is a follow-up when production traffic accumulates; not this plan.
- **Migration of already-generated questions.** Existing `chart_spec` payloads in `generation_records` retain `render_mode: "html"` and continue to render via the LLM-HTML + Playwright path. This plan makes no data migration.
- **Verifier / ODT export.** Verifier consumes the server-side PNG regardless of which renderer produced it (matplotlib / Playwright / OpenAI image API), so no verifier change is required. ODT export follows the same rule.
- **Additional per-family sub-categories.** Introducing sub-values on `題目內容類型` (e.g. `含圖片_realistic` vs `含圖片_structured`) is deliberately avoided to preserve backward compatibility with existing web forms and stored questions. The routing lives inside the LLM prompt instruction.
