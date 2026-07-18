# Hybrid Routing — Social-Studies `CONTENT_TYPE_INSTRUCTIONS` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the social-studies LLM prompt the HYBRID routing rule from issue #110: the SS `含圖片` instruction in `src/social_studies/context_builder.py::CONTENT_TYPE_INSTRUCTIONS` must direct the model to emit `render_mode: "gpt_image"` for realistic diagrams (real-coastline maps, historical photo-style scene, real-proportion geographic images) and `render_mode: "html"` for structured / semantic material (posters, ads, forms, comparison layouts, semantic-annotated tables). Also refresh the SS `src/social_studies/context_builder.py` module docstring to name `"gpt_image"` alongside the existing `"chart"` and `"html"` values.

**Architecture:** Pure prompt / docstring edit. One file touched. This plan turns the `social_studies` parametrization of the intentionally-red `test_illustrative_content_routes_to_gpt_image_or_html` (from foundation plan Task 5) green while leaving math and NS unchanged — math is 02's responsibility, NS is 04's.

**Tech Stack:** Python 3.11 + uv + pytest. No schema, renderer, or web changes.

**Issue:** https://github.com/paulpengtw/exam-generation/issues/110 (Part B — social-studies prompt).

**Depends on:** `docs/superpowers/plans/2026-07-19-hybrid-routing-01-foundation.md` MUST land first. If foundation Task 5 (parametric rename) is not on your branch base, stop and land 01.

**Sibling plans (independent — can execute in any order after 01):**
- `docs/superpowers/plans/2026-07-19-hybrid-routing-02-math-prompt.md`
- `docs/superpowers/plans/2026-07-19-hybrid-routing-04-natural-sciences-prompt.md`

## Global Constraints

- **Backward compatibility:** `render_mode: "html"` and `render_mode: "chart"` remain valid. This plan only ADDS the option for the model to emit `render_mode: "gpt_image"` for realistic diagrams.
- **Doc update-order rule (verbatim from CLAUDE.md):** update the policy first, then the docstrings, then the `CONTENT_TYPE_INSTRUCTIONS` tables. Plan 01 landed the policy step. This plan follows with docstring → instruction table.
- **No changes to other subjects.** Math and NS `context_builder.py` files are untouched — that's plans 02 and 04's job.
- **`IMAGE_DISCLAIMER` symbol:** already defined in `src/social_studies/context_builder.py` and used inside `CONTENT_TYPE_INSTRUCTIONS`. Reuse the exact same symbol; do not introduce a new constant.
- **Per-小題 supplement rule preserved:** the current SS `含圖片` instruction includes the "圖片必須是作答的必要條件" clause. Keep it — the routing addition is orthogonal to that requirement.
- **Backend deps:** `uv sync --extra web` should already be done from plan 01.
- **Lint scope:** no NEW E501/F401 violations in touched files.
- **Branch:** work on `feat/110-hybrid-routing-ss` branched from the tip of `feat/110-hybrid-routing-foundation` (once foundation lands to `staging`, rebase onto `staging`). Commit per task; do not push mid-plan.

---

### Task 1: Update SS `src/social_studies/context_builder.py` module docstring

**Files:**
- Modify: `src/social_studies/context_builder.py:1-10` — module docstring

**Interfaces:**
- Consumes: the policy wording landed in foundation-plan Task 4.
- Produces: a docstring that names `"gpt_image"` alongside `"chart"` and `"html"`, matching the schema Literal from foundation Task 2 and preparing the reader for Task 2 of this plan.

- [ ] **Step 1: Create the branch**

```bash
cd /workspace/exam-generation
git checkout staging && git pull
git checkout -b feat/110-hybrid-routing-ss
```

Verify foundation plan is present:

```bash
git log --oneline | grep -E "feat\(schema\).*gpt_image|feat\(renderer\).*gpt_image" | head -2
```

Expected: two commits present. If missing, stop and land foundation plan 01 first.

- [ ] **Step 2: Replace SS module docstring**

`src/social_studies/context_builder.py:1-10` — replace the entire existing module docstring with:

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

- [ ] **Step 3: Confirm the file still parses**

```bash
uv run python -c "import src.social_studies.context_builder as cb; print(cb.__doc__.split(chr(10))[0])"
```

Expected: prints `Assemble LLM prompts for 108課綱 社會領域素養導向 question generation.`

- [ ] **Step 4: Commit**

```bash
git add src/social_studies/context_builder.py
git commit -m "docs: cite gpt_image render_mode in SS context-builder docstring (#110)"
```

---

### Task 2: Update SS `含圖片` instruction in `CONTENT_TYPE_INSTRUCTIONS`

**Files:**
- Modify: `src/social_studies/context_builder.py:67-76` — SS `含圖片` instruction inside `CONTENT_TYPE_INSTRUCTIONS`

**Interfaces:**
- Consumes: the renamed parametric test `test_illustrative_content_routes_to_gpt_image_or_html` from foundation plan Task 5 (currently red for `social_studies`). `IMAGE_DISCLAIMER` module-level string already defined in the SS context builder.
- Produces: the SS `含圖片` instruction teaching the LLM to pick `render_mode` per figure family, phrased for 108課綱 社會領域 素材 vocabulary. Turns the `social_studies` parametrization of the foundation red test green.

- [ ] **Step 1: Run the currently-red SS parametrization to confirm the starting state**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[social_studies]' -v
```

Expected: FAIL — `render_mode: "gpt_image"` not found in current SS `含圖片` string.

- [ ] **Step 2: Update SS `含圖片` instruction**

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

- [ ] **Step 3: Run the SS parametrizations to verify state**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[social_studies]' 'tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec[social_studies]' 'tests/test_figure_rendering_policy.py::test_quantitative_content_routes_to_chart_and_html_for_tables[social_studies]' -v
```

Expected: all 3 PASS.

- [ ] **Step 4: Confirm math and NS parametrizations follow their expected state**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[math]' 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[natural_sciences]' -v
```

Expected: math parametrization state depends on whether plan 02 has landed — pass if landed, fail if not. NS parametrization FAIL (still owned by plan 04).

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/context_builder.py
git commit -m "feat(SS prompt): route 含圖片 realistic diagrams to gpt_image, structured to html (#110)"
```

---

### Task 3: Local regression check + handoff

**Files:** none modified.

- [ ] **Step 1: Run the full non-server test suite**

```bash
uv run pytest tests/ -v --ignore=tests/server 2>&1 | tail -30
```

Expected: the `social_studies` parametrization is now green. `math` and `natural_sciences` parametrization state depends on whether the sibling plans have landed.

- [ ] **Step 2: Lint the touched file**

```bash
uv run ruff check src/social_studies/context_builder.py
```

Expected: no NEW violations on the touched lines.

- [ ] **Step 3: Confirm commit list**

```bash
git log --oneline feat/110-hybrid-routing-ss ^staging
```

Expected 2 commits (bottom to top): docs (Task 1), feat(SS prompt) (Task 2).

- [ ] **Step 4: DO NOT PUSH.**

Handoff to the operator: report the commit list. Do not open a PR as part of this plan.

---

## Deferred / not in this plan

- Math and NS prompts / docstrings — see plans 02 and 04.
- Whole-suite final gate for the full HYBRID rollout — see plan 04 Task 3.
- Per-小題 image-mode UI/backend changes — orthogonal to this plan; explicitly out of scope.
