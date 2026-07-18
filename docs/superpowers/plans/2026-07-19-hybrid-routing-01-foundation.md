# Hybrid Routing — Foundation (schema + renderer + policy) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the shared foundation for the 2026-07-19 HYBRID routing decision on issue #110: extend the three `ImageSpec.render_mode` Literals to accept `"gpt_image"`, add a renderer dispatch branch that routes that value to `LLMClient.generate_image()`, update `docs/figure-rendering-policy.md` to name the new value, and rename the parametric illustrative-routing test to accept both `"gpt_image"` and `"html"`. This plan intentionally does NOT touch any subject's `CONTENT_TYPE_INSTRUCTIONS` — those land in the three per-subject sibling plans (02-math / 03-social-studies / 04-natural-sciences).

**Architecture:** Additive schema extension. Each `ImageSpec.render_mode` Literal grows from `["chart", "html"]` to `["chart", "html", "gpt_image"]`. `render_image()` gains one new dispatch branch (parallel to the existing `chart`/`html` branches) that calls the same `llm_client.generate_image()` code path the `image_generation_mode="gpt_image"` caller override already uses; that override is preserved unchanged. The policy doc and the renamed parametric test capture the routing rule that the sibling plans will then satisfy per subject. No renderer replacement, no removal of `"html"`, no schema field changes anywhere else.

**Tech Stack:** Python 3.11 + uv + pytest + pydantic 2 (`Literal` union extension). OpenAI SDK (`images.generate` via existing `LLMClient.generate_image()`). Playwright / matplotlib unchanged. No frontend or web changes.

**Issue:** https://github.com/paulpengtw/exam-generation/issues/110 (Part B implementation via HYBRID decision).

**Sibling plans (all depend on this one landing first):**
- `docs/superpowers/plans/2026-07-19-hybrid-routing-02-math-prompt.md`
- `docs/superpowers/plans/2026-07-19-hybrid-routing-03-social-studies-prompt.md`
- `docs/superpowers/plans/2026-07-19-hybrid-routing-04-natural-sciences-prompt.md`

**Supersedes:** the monolithic `docs/superpowers/plans/2026-07-19-hybrid-routing.md` (all 9 tasks) and `docs/superpowers/plans/2026-07-18-frontend-ts-render-mode.md` Tasks 6-12 (via PR #148). Do NOT execute either superseded plan; the `frontend_ts` render mode is explicitly rejected.

## Global Constraints

- **Backward compatibility:** `"html"` and `"chart"` remain valid `render_mode` values and are dispatched exactly as they are today. Do NOT remove either. Already-generated `chart_spec` payloads with `render_mode: "html"` must continue to render via the LLM-HTML + Playwright path.
- **Caller override precedence unchanged:** the request-level `image_generation_mode` kwarg on `render_image()` still short-circuits when set to `"gpt_image"` (see `src/renderer.py:290-300`). The new `render_mode: "gpt_image"` is the LLM-driven spec-level choice, not a replacement for the caller override.
- **No new API keys or env vars.** `IMAGE_API_KEY` and `IMAGE_MODEL` already exist for the existing `LLMClient.generate_image()` path.
- **Doc update-order rule (verbatim from CLAUDE.md):** update the policy first, then the docstrings, then the `CONTENT_TYPE_INSTRUCTIONS` tables. Docstrings and `CONTENT_TYPE_INSTRUCTIONS` are the sibling plans' responsibility; this plan lands only the policy step of that rule.
- **Backend deps:** run `uv sync --extra web` once before any test run.
- **Testing:** all tests run from repo root with `uv run pytest <path> -v`. No web tests in this plan.
- **Lint scope:** pre-existing E501 / F401 noise in the repo is out of scope; introduce no new violations in files this plan touches.
- **Branch:** all work lives on `feat/110-hybrid-routing-foundation`, branched from the current `staging` HEAD (which must already contain PR #148, the docs-only HYBRID recording). Commit per task; do not push mid-plan.

---

### Task 1: Create the branch + failing schema tests

**Files:**
- Create: `tests/test_hybrid_routing_schema.py`

**Interfaces:**
- Consumes: `ImageSpec` from `src.schemas`, `src.social_studies.schemas`, `src.natural_sciences.schemas`.
- Produces: three parametric tests that assert `ImageSpec(render_mode="gpt_image", ...)` validates and three companion tests that keep `"chart"` / `"html"` valid. Currently the `gpt_image` variants fail because the Literal only allows `"chart"|"html"`.

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
git checkout -b feat/110-hybrid-routing-foundation
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
- Produces: `render_mode: Literal["chart", "html", "gpt_image"] = "chart"` in all three `ImageSpec` classes; downstream code that reads `spec.get("render_mode")` sees `"gpt_image"` as a valid value.

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
- Modify: `src/renderer.py` — `render_image()` (existing at lines 271-322)
- Modify: `tests/test_figure_rendering_policy.py` — append one new dispatch test after `test_dispatch_gpt_image_mode_bypasses_render_mode` (currently at line 135)

**Interfaces:**
- Consumes: `LLMClient.generate_image(prompt, output_path)` (existing at `src/llm_client.py:452-496`); `_build_gpt_image_prompt(spec, question_text)` (existing at `src/renderer.py:325`).
- Produces: `render_image()` handles `render_mode == "gpt_image"` by calling `llm_client.generate_image()` — same code path as the existing `image_generation_mode == "gpt_image"` caller override, but triggered by spec content instead of a caller kwarg. The caller override remains and still short-circuits first.

- [ ] **Step 1: Write the failing dispatch test**

Append to `tests/test_figure_rendering_policy.py` (after `test_dispatch_gpt_image_mode_bypasses_render_mode`):

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

Expected: FAIL — `render_image` returns `None` and prints `Warning: unknown render_mode 'gpt_image'` (see the fallthrough at the bottom of `render_image`).

- [ ] **Step 3: Add the new dispatch branch in `render_image()`**

`src/renderer.py` — locate the existing dispatch block starting at `if render_mode == "chart":`. INSERT a new branch immediately BEFORE that block:

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

Final block ordering inside `render_image()` must be: `image_generation_mode == "gpt_image"` caller-override branch (unchanged) → new `render_mode == "gpt_image"` branch → `render_mode == "chart"` branch → `render_mode == "html"` branch → unknown-mode warning fallthrough.

- [ ] **Step 4: Run the new dispatch test to verify it passes**

```bash
uv run pytest tests/test_figure_rendering_policy.py::test_dispatch_gpt_image_render_mode_calls_llm_generate_image -v
```

Expected: PASS.

- [ ] **Step 5: Run the full dispatch test suite to confirm no regression**

```bash
uv run pytest tests/test_figure_rendering_policy.py -v
```

Expected: all dispatch tests PASS (including `test_dispatch_chart_render_mode_uses_matplotlib`, `test_dispatch_html_render_mode_uses_playwright`, `test_dispatch_gpt_image_mode_bypasses_render_mode`, `test_dispatch_unknown_render_mode_returns_none`, and the new one). The existing `test_illustrative_content_routes_to_html` still passes at this point — it is renamed in Task 5, not here.

- [ ] **Step 6: Commit**

```bash
git add src/renderer.py tests/test_figure_rendering_policy.py
git commit -m "feat(renderer): dispatch render_mode gpt_image to LLMClient.generate_image (#110)"
```

---

### Task 4: Update `docs/figure-rendering-policy.md` — routing rule + enforcement bullets

**Files:**
- Modify: `docs/figure-rendering-policy.md`

**Interfaces:**
- Consumes: the Renderer selection matrix section landed by PR #148.
- Produces: two edits so the policy doc names `"gpt_image"` as a valid `render_mode` (matching the schema change in Task 2) and instructs the model to emit it for realistic illustrative figures. Enforcement bullets updated to name the tests added in Tasks 1 and 3, and the parametric illustrative-routing test that will land in Task 5.

- [ ] **Step 1: Update the routing-rule table under `## The rule`**

`docs/figure-rendering-policy.md` — locate the table header ``| Figure family | Examples | `render_mode` | Renderer |`` and its two data rows. REPLACE the illustrative-figures row (currently ends with `` `"html"` (or `"frontend_ts"` — see below) `` `LLM-HTML + Playwright ...`) with:

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

APPEND two new bullets to the Enforcement list:

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

Expected: at least 4 occurrences (routing rule table row, `CONTENT_TYPE_INSTRUCTIONS` mapping row for 含圖片, enforcement bullets).

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

### Task 5: Rename the parametric illustrative-routing test

**Files:**
- Modify: `tests/test_figure_rendering_policy.py:34-40` — rewrite `test_illustrative_content_routes_to_html`

**Interfaces:**
- Consumes: `_SUBJECT_TABLES` (existing at `tests/test_figure_rendering_policy.py:18-23`), which lists the three subjects' `CONTENT_TYPE_INSTRUCTIONS` tables.
- Produces: a renamed parametric test `test_illustrative_content_routes_to_gpt_image_or_html` that requires each subject's `含圖片` instruction to name BOTH `render_mode: "gpt_image"` and `render_mode: "html"`. All 3 parametrizations will FAIL here — they are turned green one at a time by the three per-subject sibling plans (02 / 03 / 04). This deliberate red gate is what forces each sibling plan to actually update its `CONTENT_TYPE_INSTRUCTIONS`.

- [ ] **Step 1: Rewrite the existing `test_illustrative_content_routes_to_html`**

`tests/test_figure_rendering_policy.py` — replace the entire body of `test_illustrative_content_routes_to_html` (lines 34-40) with:

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

- [ ] **Step 2: Run the renamed parametric test — expect ALL 3 subjects to FAIL**

```bash
uv run pytest tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html -v
```

Expected: 3 tests FAIL — each subject's `含圖片` instruction currently mentions only `render_mode: "html"`. This red gate is intentional and is closed by the sibling per-subject plans.

- [ ] **Step 3: Run the other two parametric tests to confirm no collateral damage**

```bash
uv run pytest tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec tests/test_figure_rendering_policy.py::test_quantitative_content_routes_to_chart_and_html_for_tables -v
```

Expected: all 6 pass (unchanged tests).

- [ ] **Step 4: Commit the rename**

```bash
git add tests/test_figure_rendering_policy.py
git commit -m "test: rename illustrative routing to require gpt_image or html (#110)"
```

---

### Task 6: Foundation gate + handoff

**Files:** none modified.

**Interfaces:** ensures no plan step introduced a regression outside the touched files and that the intentional red parametric test is the only new failure.

- [ ] **Step 1: Run the full non-server test suite**

```bash
uv run pytest tests/ -v --ignore=tests/server 2>&1 | tail -30
```

Expected: the intentionally-failing `test_illustrative_content_routes_to_gpt_image_or_html` fails on all 3 subject parametrizations (3 FAIL). Every other test passes. No other regressions.

- [ ] **Step 2: Run the server-adjacent tests too**

```bash
uv run pytest tests/server -v 2>&1 | tail -20
```

Expected: PASS (this plan does not touch `server/`).

- [ ] **Step 3: Lint the files touched by this plan**

```bash
uv run ruff check src/schemas.py src/social_studies/schemas.py src/natural_sciences/schemas.py src/renderer.py tests/test_figure_rendering_policy.py tests/test_hybrid_routing_schema.py
```

Expected: no NEW violations in these files. Pre-existing E501/F401 on other lines within these files is out of scope; do not fix unrelated hits in this plan.

- [ ] **Step 4: Confirm commit list**

```bash
git log --oneline feat/110-hybrid-routing-foundation ^staging
```

Expected order of the 5 commits (bottom to top):
1. test (Task 1 — failing schema tests)
2. feat(schema) (Task 2 — schema Literal extension)
3. feat(renderer) (Task 3 — dispatch)
4. docs(policy) (Task 4 — policy doc)
5. test (Task 5 — rename parametric test)

- [ ] **Step 5: DO NOT PUSH.**

Handoff to the operator: report the commit list, note that the 3 parametric-test failures are expected and are closed by the per-subject sibling plans, and wait for explicit push instruction. Do not open a PR as part of this plan.

---

## Deferred / not in this plan

- **Subject `CONTENT_TYPE_INSTRUCTIONS` prompts + module docstrings.** All three subjects' updates land in their dedicated sibling plans (02 / 03 / 04). The intentional red parametric test at the end of Task 5 is what those plans turn green.
- **Web frontend edits.** The web form's per-小題 `image_generation_mode` selector already exists as an override; no new UI value is needed since routing is now spec-driven. If the operator later wants to expose the new render_mode value to power users as an explicit override, that is a separate plan.
- **`server/utility/routes.py` schema exposure.** The API's `/api/schemas` endpoint does not currently surface `render_mode` — no server-side change is required by this plan.
- **Census gate.** The ≥30-real-production-questions-per-subject census gate remains provisional in the HYBRID entry. Revisiting is a follow-up when production traffic accumulates.
- **Migration of already-generated questions.** Existing `chart_spec` payloads retain `render_mode: "html"` and continue to render via the LLM-HTML + Playwright path. No data migration.
- **Verifier / ODT export.** Verifier consumes the server-side PNG regardless of renderer; no verifier change required. ODT export follows the same rule.
