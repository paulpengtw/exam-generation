# Channel-1 ICCS Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refill Social Studies Channel-1 with ICCS-native, teacher-reviewable 題組 groups for the three populated content-type keys while preserving the existing loader and prompt-builder contracts.

**Architecture:** Add one JSON sampling group per authored 題組 under `data/social_studies/few_shot/<題目內容類型>/`. Each group contains a shared text, valid ICCS axes, multiple adapted subquestions, per-option distractor analysis, and visual `chart_spec`/reference-image metadata only where the content type requires it. Add a prompt-seam regression test that exercises every populated key and verifies the instruction-only fallback for unpopulated keys.

**Tech Stack:** Python 3.11, pytest, existing Social Studies data loader/context builders, UTF-8 JSON, ICCS/108課綱 CSV and JSON curriculum data.

**Spec:** GitHub issue #544 (`paulpengtw/exam-generation`), read with `gh issue view 544 --repo paulpengtw/exam-generation --comments`.

## Global Constraints

- Do not modify Social Studies loader or prompt-builder code.
- Use only the four launched `認知歷程` values and the four schema-controlled `內容領域` values.
- Keep at most one Knowing–Defining and Describing subquestion per group.
- Preserve the 3–4-example Relate or Integrate rule, or use two clearly contrasted source records.
- Keep 公民學習內容 codes consistent with `data/social_studies/curriculum/內容領域_mapping.csv`.
- Adapt every ICCS worked example so it is not word-for-word identical to Channel-2 `process_exemplars`.
- Leave `process_exemplars/`, mathematics, and natural-sciences corpora byte-untouched.
- Commit and push after each durable unit; never open a PR or edit GitHub issues.

### Task 1: Prompt-seam regression test and stale post-removal assertion

**Files:**
- Modify: `tests/test_fewshot_clean_cut.py`
- Test: `tests/test_fewshot_clean_cut.py`

**Interfaces:**
- Consumes: `build_text_user_prompt`, `sample_params`, and the checked-in Channel-1 directories.
- Produces: a regression guard proving populated keys inject a corpus marker and unpopulated keys retain the exact designed fallback.

- [ ] **Step 1: Write the failing test**

Add a parametrized test for `純文字`, `混合`, and `graphs/charts/tables` that seeds `build_text_user_prompt`, loads the same key, and asserts one checked-in group description is present in the resulting `## 參考範例` block. Add a companion parametrization for `含圖片`, `customized`, and `數位閱讀` that asserts `（目前暫無範例，請根據指定條件自行設計。）` and no exception. Replace the obsolete “Channel-1 is empty after #542” assertion with a non-empty/shape assertion for the three populated keys.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/test_fewshot_clean_cut.py`

Expected: the new populated-key prompt test fails because the current Channel-1 directories are empty; the fallback test remains green.

- [ ] **Step 3: Keep implementation minimal**

Do not alter loader or prompt code. The data groups added in later tasks are the implementation that makes the new test pass.

- [ ] **Step 4: Commit the regression test**

Run:

```bash
git add tests/test_fewshot_clean_cut.py
git commit -m "test: cover social channel1 prompt injection seam"
git push -u origin feat/544-channel1-iccs-corpus
```

### Task 2: Text-only ICCS groups

**Files:**
- Create: `data/social_studies/few_shot/純文字/iccs_global_mobility.json`
- Create: `data/social_studies/few_shot/純文字/iccs_governance_and_responsibility.json`
- Create: `data/social_studies/few_shot/純文字/iccs_economic_choices.json`
- Create: `data/social_studies/few_shot/純文字/iccs_family_change.json`

**Interfaces:**
- Consumes: ICCS worked examples in `data/social_studies/ICCS_cognitive_domains.md` and the live curriculum mappings.
- Produces: four equal-odds pure-text groups covering the text-based worked examples, all four cognitive buckets, and per-subquestion distractor analysis.

- [ ] **Step 1: Add each group with shared text and adapted subquestions**

Use one Defining and Describing subquestion at most per group. Recompose the global-mobility/臭蟲, local-governance/行政責任/權力分立, currency/market/white-shrimp, and kinship/family-function examples into coherent shared passages. Do not copy the Channel-2 wording.

- [ ] **Step 2: Validate JSON and loader shape**

Run a JSON parse plus `load_few_shot_example_groups` for `純文字`; assert no group has `chart_spec`, every subquestion has a launched process/domain, and every choice subquestion has flat A–D `誘答分析`.

- [ ] **Step 3: Commit and push the text groups**

```bash
git add data/social_studies/few_shot/純文字
git commit -m "data: add ICCS pure-text social groups"
git push -u origin feat/544-channel1-iccs-corpus
```

### Task 3: Graph/table groups and ICCS chart stimuli

**Files:**
- Create: `data/social_studies/few_shot/graphs/charts/tables/iccs_female_unemployment.json`
- Create: `data/social_studies/few_shot/graphs/charts/tables/iccs_media_literacy.json`
- Create: `data/social_studies/few_shot/graphs/charts/tables/iccs_voting_eligibility.json`
- Create: `data/social_studies/few_shot/graphs/charts/tables/iccs_surname_choices.json`
- Create: `data/social_studies/few_shot/graphs/charts/tables/iccs_married_women_labor.json`
- Create: `data/social_studies/few_shot/graphs/charts/tables/iccs_school_size.json`

**Interfaces:**
- Consumes: ICCS table/chart items 1–4, 6, and 7 plus `ICCS_cognitive_domains_fig12.png` and `ICCS_cognitive_domains_fig20.png`.
- Produces: genuine chart/table groups with complete visual specs and the two source images attached through the existing JSON example shape.

- [ ] **Step 1: Add complete data-bearing chart specs**

Use `render_mode: "chart"` for statistical line charts and `render_mode: "html"` for structured tables. Keep answer-required values in `chart_spec.data`, not duplicated in `文本`. Attach the two ICCS PNGs with repository-relative paths and captions.

- [ ] **Step 2: Validate visual groups**

Run the loader and assert each group has non-null `chart_spec`, a canonical figure kind, and at least one subquestion whose answer depends on a chart/table value or trend. Check both image paths exist.

- [ ] **Step 3: Commit and push the graph/table groups**

```bash
git add data/social_studies/few_shot/graphs
git commit -m "data: add ICCS chart and table social groups"
git push -u origin feat/544-channel1-iccs-corpus
```

### Task 4: Mixed cross-subject groups

**Files:**
- Create: `data/social_studies/few_shot/混合/iccs_migrant_workers.json`
- Create: `data/social_studies/few_shot/混合/iccs_public_works.json`

**Interfaces:**
- Consumes: ICCS Relate or Integrate examples for 外籍移工 and 公共建設甲乙.
- Produces: mixed text-plus-table groups with explicit cross-subject `科目` and learning-content codes.

- [ ] **Step 1: Add the mixed groups**

Use the migrant table as geography material for a civic gender/work concept and the two public-works records as history material for a civic rule-of-law concept. Preserve the four-country comparison and the two-record contrast; include a companion subquestion per group without duplicating the source item.

- [ ] **Step 2: Validate cross-subject code truth**

Run the live domain mapping against every `公` code. Assert the selected top-level domain is in each public code’s mapped domain set, and assert every `歷`/`地`/`公` code agrees with its listed `科目`.

- [ ] **Step 3: Commit and push the mixed groups**

```bash
git add data/social_studies/few_shot/混合
git commit -m "data: add ICCS mixed cross-subject groups"
git push -u origin feat/544-channel1-iccs-corpus
```

### Task 5: Verification and handoff

**Files:**
- Modify: `tests/test_fewshot_clean_cut.py` if any data-contract assertion needs correction
- No production code changes permitted

- [ ] **Step 1: Run affected tests**

Run `.venv/bin/python -m pytest -q tests/test_fewshot_clean_cut.py tests/test_few_shot_distractor_coverage.py tests/test_範例_template_parity.py tests/test_no_pisa_on_live_ss_surfaces.py`.

- [ ] **Step 2: Run the new test and adjacent social prompt tests**

Run `.venv/bin/python -m pytest -q tests/test_social_studies_context_builder.py tests/test_prompt_seam_post_removal.py` plus the new prompt-seam test if it is split out.

- [ ] **Step 3: Run broader backend tests in progress-printing chunks**

Run the remaining backend test files in bounded groups, retaining real pass/fail/skip totals and stopping to diagnose any regression before claiming completion.

- [ ] **Step 4: Inspect, commit, push, and verify clean state**

Run `git diff --check`, inspect `git status --short`, confirm only the planned data/test/plan files changed, ensure each commit is on the remote, and report the teacher-review summary group by group.
