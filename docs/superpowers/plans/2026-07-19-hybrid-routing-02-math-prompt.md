# Hybrid Routing — Math `CONTENT_TYPE_INSTRUCTIONS` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the math LLM prompt the HYBRID routing rule from issue #110: the math `含圖片` instruction in `src/context_builder.py::CONTENT_TYPE_INSTRUCTIONS` must direct the model to emit `render_mode: "gpt_image"` for realistic diagrams (real-proportion geometry, scenario 寫實圖) and `render_mode: "html"` for structured / semantic layouts (menus, scenario cards, forms). Also refresh the math `src/context_builder.py` module docstring to name `"gpt_image"` alongside the existing `"chart"` and `"html"` values.

**Architecture:** Pure prompt / docstring edit. Two files touched (math context builder + its policy test parametrization is exercised by the shared file). This plan turns the math parametrization of the intentionally-red `test_illustrative_content_routes_to_gpt_image_or_html` (from foundation plan Task 5) green while leaving SS and NS parametrizations still failing — they land in plans 03 and 04.

**Tech Stack:** Python 3.11 + uv + pytest. No schema, renderer, or web changes.

**Issue:** https://github.com/paulpengtw/exam-generation/issues/110 (Part B — math prompt).

**Depends on:** `docs/superpowers/plans/2026-07-19-hybrid-routing-01-foundation.md` MUST land first (schema Literal + renderer dispatch + policy doc + parametric test rename). If Task 5 of that plan is not committed on your branch base, stop and land 01 first.

**Sibling plans (independent — can execute in any order after 01):**
- `docs/superpowers/plans/2026-07-19-hybrid-routing-03-social-studies-prompt.md`
- `docs/superpowers/plans/2026-07-19-hybrid-routing-04-natural-sciences-prompt.md`

## Global Constraints

- **Backward compatibility:** `render_mode: "html"` and `render_mode: "chart"` continue to be valid model outputs. This plan only ADDS the option for the model to emit `render_mode: "gpt_image"` when the figure is realistic.
- **Doc update-order rule (verbatim from CLAUDE.md):** update the policy first, then the docstrings, then the `CONTENT_TYPE_INSTRUCTIONS` tables. Plan 01 landed the policy step. This plan follows with docstring → instruction table.
- **No changes to other subjects.** SS `context_builder.py` and NS `context_builder.py` are untouched by this plan — that's plans 03 and 04's job.
- **`IMAGE_DISCLAIMER` symbol:** the math `src/context_builder.py` already defines and uses `IMAGE_DISCLAIMER` inside `CONTENT_TYPE_INSTRUCTIONS`. Reuse the exact same symbol; do not introduce a new constant.
- **Backend deps:** `uv sync --extra web` should already be done from plan 01; re-run only if you cleaned the venv.
- **Lint scope:** no NEW E501/F401 violations in touched files. Pre-existing noise is out of scope.
- **Branch:** work on `feat/110-hybrid-routing-math` branched from the tip of `feat/110-hybrid-routing-foundation` (once foundation lands to `staging`, rebase this branch onto `staging`). Commit per task; do not push mid-plan.

---

### Task 1: Update math `src/context_builder.py` module docstring

**Files:**
- Modify: `src/context_builder.py:1-8` — module docstring

**Interfaces:**
- Consumes: the policy wording landed in foundation-plan Task 4.
- Produces: a docstring that names `"gpt_image"` alongside `"chart"` and `"html"`, matching the schema Literal from foundation Task 2 and preparing the reader for Task 2 of this plan (the `CONTENT_TYPE_INSTRUCTIONS` update).

- [ ] **Step 1: Create the branch**

```bash
cd /workspace/exam-generation
git checkout staging && git pull
git checkout -b feat/110-hybrid-routing-math
```

Verify foundation plan is present:

```bash
git log --oneline | grep -E "feat\(schema\).*gpt_image|feat\(renderer\).*gpt_image" | head -2
```

Expected: two commits (schema Literal + renderer dispatch). If missing, stop and land foundation plan 01 first.

- [ ] **Step 2: Replace math module docstring**

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

- [ ] **Step 3: Confirm the file still parses**

```bash
uv run python -c "import src.context_builder; print(src.context_builder.__doc__.split(chr(10))[0])"
```

Expected: prints `Assemble LLM prompts with curriculum context and few-shot examples.`

- [ ] **Step 4: Commit**

```bash
git add src/context_builder.py
git commit -m "docs: cite gpt_image render_mode in math context-builder docstring (#110)"
```

---

### Task 2: Update math `含圖片` instruction in `CONTENT_TYPE_INSTRUCTIONS`

**Files:**
- Modify: `src/context_builder.py:68-74` — math `含圖片` instruction inside `CONTENT_TYPE_INSTRUCTIONS`

**Interfaces:**
- Consumes: the renamed parametric test `test_illustrative_content_routes_to_gpt_image_or_html` from foundation plan Task 5 (currently red for math). The `IMAGE_DISCLAIMER` module-level string is already defined in `src/context_builder.py`.
- Produces: the math `含圖片` instruction teaching the LLM to pick `render_mode` per figure family. Turns the math parametrization of the foundation red test green.

- [ ] **Step 1: Run the currently-red math parametrization to confirm the starting state**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[math]' -v
```

Expected: FAIL — `render_mode: "gpt_image"` not found in current math `含圖片` string.

- [ ] **Step 2: Update math `含圖片` instruction**

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

- [ ] **Step 3: Run the math parametrization to verify it now passes**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[math]' -v
```

Expected: PASS.

- [ ] **Step 4: Confirm the SS and NS parametrizations still fail (they belong to plans 03 and 04)**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[social_studies]' 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[natural_sciences]' -v
```

Expected: both FAIL. This is the correct starting state for the sibling plans.

- [ ] **Step 5: Confirm math's plain-text and quantitative parametrizations still pass**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec[math]' 'tests/test_figure_rendering_policy.py::test_quantitative_content_routes_to_chart_and_html_for_tables[math]' -v
```

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add src/context_builder.py
git commit -m "feat(math prompt): route 含圖片 realistic diagrams to gpt_image, structured to html (#110)"
```

---

### Task 3: Local regression check + handoff

**Files:** none modified.

- [ ] **Step 1: Run the full non-server test suite**

```bash
uv run pytest tests/ -v --ignore=tests/server 2>&1 | tail -30
```

Expected: the intentionally-red parametric test now fails on only 2 subject parametrizations (`social_studies` and `natural_sciences`); the math parametrization is green. No other regressions.

- [ ] **Step 2: Lint the touched file**

```bash
uv run ruff check src/context_builder.py
```

Expected: no NEW violations on the touched lines.

- [ ] **Step 3: Confirm commit list**

```bash
git log --oneline feat/110-hybrid-routing-math ^staging
```

Expected 2 commits (bottom to top): docs (Task 1), feat(math prompt) (Task 2).

- [ ] **Step 4: DO NOT PUSH.**

Handoff to the operator: report the commit list and note that the SS and NS parametrizations remain intentionally red until plans 03 and 04 land.

---

## Deferred / not in this plan

- SS and NS prompts / docstrings — see plans 03 and 04.
- Whole-suite final gate for the full HYBRID rollout — see plan 04 Task 3.
