# Hybrid Routing — Natural-Sciences `CONTENT_TYPE_INSTRUCTIONS` + Whole-Suite Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the HYBRID routing rollout on issue #110 by teaching the natural-sciences LLM prompt the same routing rule (realistic diagrams → `render_mode: "gpt_image"`, structured/semantic → `render_mode: "html"`) and running the whole-suite gate that confirms all three subjects are green together. Refreshes the NS `src/natural_sciences/context_builder.py` module docstring and updates its `含圖片` instruction; then closes the plan-set with a final regression sweep.

**Architecture:** Pure prompt / docstring edit for NS, plus a suite-wide validation task. One source file touched (NS context builder). No schema, renderer, or web changes.

**Tech Stack:** Python 3.11 + uv + pytest. No frontend changes.

**Issue:** https://github.com/paulpengtw/exam-generation/issues/110 (Part B — natural-sciences prompt + final gate).

**Depends on:** `docs/superpowers/plans/2026-07-19-hybrid-routing-01-foundation.md` MUST land first. Plans 02 and 03 SHOULD also be landed before Task 3's whole-suite gate is run (otherwise the gate will still see red parametrizations for the missing subjects — that is a valid partial-rollout state but not the completion criterion this plan asserts).

**Sibling plans (independent — can execute in any order after 01):**
- `docs/superpowers/plans/2026-07-19-hybrid-routing-02-math-prompt.md`
- `docs/superpowers/plans/2026-07-19-hybrid-routing-03-social-studies-prompt.md`

## Global Constraints

- **Backward compatibility:** `render_mode: "html"` and `render_mode: "chart"` remain valid. This plan only ADDS the option for the model to emit `render_mode: "gpt_image"` for realistic diagrams.
- **Doc update-order rule (verbatim from CLAUDE.md):** policy → docstring → instruction table. Plan 01 landed the policy step. Task 1 here updates the docstring, Task 2 updates the instruction.
- **NS-specific `ruff: noqa: E501` line preserved:** `src/natural_sciences/context_builder.py` starts with `# ruff: noqa: E501` at line 1. Keep that line intact; the docstring begins at line 2.
- **Per-小題 supplement rule preserved:** the current NS `含圖片` instruction includes the "圖片必須是作答的必要條件" clause. Keep it — the routing addition is orthogonal.
- **`IMAGE_DISCLAIMER` symbol:** already defined in `src/natural_sciences/context_builder.py`. Reuse; do not introduce a new constant.
- **Backend deps:** `uv sync --extra web` should already be done from plan 01.
- **Lint scope:** no NEW E501/F401 violations in touched files.
- **Branch:** work on `feat/110-hybrid-routing-ns` branched from the tip of `feat/110-hybrid-routing-foundation` (once foundation lands to `staging`, rebase onto `staging`). Commit per task; do not push mid-plan.

---

### Task 1: Update NS `src/natural_sciences/context_builder.py` module docstring

**Files:**
- Modify: `src/natural_sciences/context_builder.py:2-10` — module docstring (keep the `# ruff: noqa: E501` line at line 1 unchanged)

**Interfaces:**
- Consumes: the policy wording landed in foundation-plan Task 4.
- Produces: a docstring that names `"gpt_image"` alongside `"chart"` and `"html"`, matching the schema Literal from foundation Task 2 and preparing the reader for Task 2 of this plan.

- [ ] **Step 1: Create the branch**

```bash
cd /workspace/exam-generation
git checkout staging && git pull
git checkout -b feat/110-hybrid-routing-ns
```

Verify foundation plan is present:

```bash
git log --oneline | grep -E "feat\(schema\).*gpt_image|feat\(renderer\).*gpt_image" | head -2
```

Expected: two commits present. If missing, stop and land foundation plan 01 first.

- [ ] **Step 2: Replace NS module docstring (keep line 1 intact)**

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

- [ ] **Step 3: Confirm the file still parses and line 1 is preserved**

```bash
head -1 src/natural_sciences/context_builder.py
uv run python -c "import src.natural_sciences.context_builder as cb; print(cb.__doc__.split(chr(10))[0])"
```

Expected: first line is `# ruff: noqa: E501`; docstring prints `Assemble LLM prompts for PISA Science + 108課綱自然科學 question generation.`

- [ ] **Step 4: Commit**

```bash
git add src/natural_sciences/context_builder.py
git commit -m "docs: cite gpt_image render_mode in NS context-builder docstring (#110)"
```

---

### Task 2: Update NS `含圖片` instruction in `CONTENT_TYPE_INSTRUCTIONS`

**Files:**
- Modify: `src/natural_sciences/context_builder.py:123-132` — NS `含圖片` instruction inside `CONTENT_TYPE_INSTRUCTIONS`

**Interfaces:**
- Consumes: the renamed parametric test `test_illustrative_content_routes_to_gpt_image_or_html` from foundation plan Task 5 (currently red for `natural_sciences`). `IMAGE_DISCLAIMER` module-level string already defined in the NS context builder.
- Produces: the NS `含圖片` instruction teaching the LLM to pick `render_mode` per figure family, phrased for PISA-Science + 108課綱 自然科學 vocabulary. Turns the `natural_sciences` parametrization of the foundation red test green.

- [ ] **Step 1: Run the currently-red NS parametrization to confirm the starting state**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[natural_sciences]' -v
```

Expected: FAIL — `render_mode: "gpt_image"` not found in current NS `含圖片` string.

- [ ] **Step 2: Update NS `含圖片` instruction**

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

- [ ] **Step 3: Run the NS parametrizations to verify state**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[natural_sciences]' 'tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec[natural_sciences]' 'tests/test_figure_rendering_policy.py::test_quantitative_content_routes_to_chart_and_html_for_tables[natural_sciences]' -v
```

Expected: all 3 PASS.

- [ ] **Step 4: Confirm math and SS parametrizations follow their expected state**

```bash
uv run pytest 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[math]' 'tests/test_figure_rendering_policy.py::test_illustrative_content_routes_to_gpt_image_or_html[social_studies]' -v
```

Expected state depends on whether plans 02 and 03 have landed — pass if landed, fail otherwise.

- [ ] **Step 5: Commit**

```bash
git add src/natural_sciences/context_builder.py
git commit -m "feat(NS prompt): route 含圖片 realistic diagrams to gpt_image, structured to html (#110)"
```

---

### Task 3: Whole-suite gate + full HYBRID rollout handoff

**Precondition:** Plans 02 and 03 have already landed on `staging` (so all three parametrizations should be green together). If either is still outstanding, defer Task 3 until they are — this task's expected outcome assumes the full HYBRID rollout.

**Files:** none modified.

**Interfaces:** ensures the entire HYBRID rollout is green together and no step introduced a regression outside touched files.

- [ ] **Step 1: Run the full non-server test suite**

```bash
uv run pytest tests/ -v --ignore=tests/server 2>&1 | tail -40
```

Expected: PASS. All three subject parametrizations of `test_illustrative_content_routes_to_gpt_image_or_html` are green.

- [ ] **Step 2: Run the server-adjacent tests too**

```bash
uv run pytest tests/server -v 2>&1 | tail -20
```

Expected: PASS (this plan set does not touch `server/`).

- [ ] **Step 3: Lint every file the full plan-set touched**

```bash
uv run ruff check src/schemas.py src/social_studies/schemas.py src/natural_sciences/schemas.py src/renderer.py src/context_builder.py src/social_studies/context_builder.py src/natural_sciences/context_builder.py tests/test_figure_rendering_policy.py tests/test_hybrid_routing_schema.py
```

Expected: no NEW violations on the touched lines. Pre-existing E501/F401 elsewhere in these files is out of scope; do not fix unrelated hits in this plan.

- [ ] **Step 4: Confirm no reference to `frontend_ts` remains**

```bash
grep -rn 'frontend_ts' src/ docs/figure-rendering-policy.md 2>/dev/null || echo "No matches (expected)"
```

Expected: `No matches (expected)`. The `frontend_ts` render mode was explicitly rejected in the HYBRID decision.

- [ ] **Step 5: Confirm the superseded monolith plan is untouched**

```bash
head -3 docs/superpowers/plans/2026-07-19-hybrid-routing.md 2>/dev/null | head -3
```

Expected: the SUPERSEDED banner is at the top. Do not remove it in this plan.

- [ ] **Step 6: Confirm commit list**

```bash
git log --oneline feat/110-hybrid-routing-ns ^staging
```

Expected 2 commits (bottom to top): docs (Task 1), feat(NS prompt) (Task 2). If Tasks 1 and 2 are the only NS-branch commits, Task 3 is a validation-only step and does not add a commit.

- [ ] **Step 7: DO NOT PUSH.**

Handoff to the operator: report the commit list, confirm the whole-suite gate passed, and wait for explicit push instruction. Do not open a PR as part of this plan.

---

## Deferred / not in this plan

- Math and SS prompts / docstrings — see plans 02 and 03.
- **Web frontend edits.** The web form's per-小題 `image_generation_mode` selector already exists as an override; no new UI value needed. Exposing `render_mode` explicitly is a separate plan.
- **`server/utility/routes.py` schema exposure.** No server-side change required.
- **Census gate.** The ≥30-real-production-questions-per-subject census gate remains provisional. Follow-up when production traffic accumulates.
- **Migration of already-generated questions.** Existing `chart_spec` payloads retain `render_mode: "html"` and continue to render via the LLM-HTML + Playwright path. No data migration.
- **Verifier / ODT export.** Verifier consumes the server-side PNG regardless of renderer; no verifier change required.
