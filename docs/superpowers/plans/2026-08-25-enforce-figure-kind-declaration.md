# Enforce Figure-Kind Declaration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every 社會領域 visual spec declares a free-text 圖像種類 before rendering, with one graceful declaration repair and existing figure-policy trail/collision handling.

**Architecture:** Keep `normalize_figure_kind` and the existing layered collision policy as the comparison seams. Add an optional pre-render hook to the shared generation spec, wire it only for 社會領域, and let the existing shared renderer callback record declaration repairs and unresolved warnings. Natural sciences keeps its existing renderer and receives no declaration enforcement.

**Tech Stack:** Python 3.11+, Pydantic, pytest, uv, existing `FigurePolicyTrailEvent` callback and `SubjectGenerationSpec` pipeline.

**Spec:** `docs/adr/0015-figure-kind-diversity-is-a-layered-guarantee.md` and GitHub issue #551.

## Global Constraints

- 社會領域 only; do not enforce declaration on 自然科學.
- Every visual spec must state `figure_kind`; canonical vocabulary is guidance, not an enum.
- A repaired free-text kind continues through `normalize_figure_kind` for collision comparison.
- One declaration-repair attempt per undeclared spec; unresolved specs render and are recorded, never block.
- Use zh-TW vocabulary: 題組、題幹、小題、圖像種類、題幹.
- After every commit, push `feat/551-enforce-figure-kind-declaration` to `origin`.

---

### Task 1: Prompt declaration contract

**Files:**
- Modify: `src/social_studies/context_builder.py`
- Modify: `src/social_studies/cli.py`
- Test: `tests/test_social_studies_context_builder.py`

**Interfaces:**
- Prompt builders continue returning their existing `(prompt, image_paths)` values.
- `_figure_kind_guidance` and both visual repair prompt templates state that every visual `chart_spec` declares `figure_kind`, offer `CANONICAL_FIGURE_KINDS`, and allow concrete free text.

- [ ] Write a failing public prompt test asserting drafting and repair prompts contain the declaration requirement, canonical vocabulary, and free-text allowance.
- [ ] Run `uv run pytest -q tests/test_social_studies_context_builder.py::<new_test>` and observe the missing declaration wording.
- [ ] Commit `test: red — require figure_kind in social visual prompts (#551)` and push it.
- [ ] Add the minimum prompt wording to the drafting and targeted repair seams.
- [ ] Run the new test plus affected prompt tests and observe green.
- [ ] Commit `feat: require figure_kind in social visual prompts (#551)` and push it.

### Task 2: Declaration repair before rendering

**Files:**
- Modify: `src/common/subject_spec.py`
- Modify: `src/common/generation_core.py`
- Modify: `src/social_studies/cli.py`
- Test: `tests/test_figure_kind_diversity_social_studies.py`

**Interfaces:**
- Add an optional `prepare_visual_policy_fn(question, params, client, on_figure_policy_entry=...)` hook to `SubjectGenerationSpec`; only `_SS_SPEC` supplies it.
- The hook repairs existing top-level declarations before the shared top-level render. `_ss_render_subquestion_images` repairs declarations for every newly available 小題 spec before calling `_render_subquestion_images`.
- Existing `_enforce_figure_kind_diversity` runs only after declaration repair, so `find_figure_kind_collisions` receives declared kinds.

- [ ] Write a failing pipeline test with two undeclared `gpt_image` 小題 specs, asserting two declaration repairs occur before either 小題 PNG render and that collision policy receives the repaired kinds.
- [ ] Run the focused test and observe no declaration repairs plus empty kinds skipped by collision detection.
- [ ] Commit `test: red — repair undeclared visual figure kinds before rendering (#551)` and push it.
- [ ] Implement one declaration repair per spec, preserve existing visual fields, apply `normalize_figure_kind` at comparison/forbidden-kind seams, and wire the social-only pre-render hook.
- [ ] Run the focused pipeline tests and observe green.
- [ ] Commit `feat: repair undeclared social visual figure kinds (#551)` and push it.

### Task 3: Graceful unresolved trail outcome

**Files:**
- Modify: `src/common/figure_policy_trail.py`
- Modify: `src/social_studies/cli.py`
- Test: `tests/test_figure_kind_diversity_social_studies.py`

**Interfaces:**
- A failed declaration repair emits the existing `repair` event with empty `after_effective_figure_kind` and `succeeded=False`, plus an existing `warning` event describing the shipped undeclared visual spec.
- The warning factory supports `duplicate_image_shipped=False` for this non-collision warning while preserving its existing collision default.

- [ ] Write a failing pipeline test where declaration repair still returns an empty kind; assert the question ships, PNG rendering completes, and trail entries identify the failed repair/unresolved declaration.
- [ ] Run it and observe no declaration-specific trail outcome.
- [ ] Commit `test: red — trail unresolved figure-kind declaration (#551)` and push it.
- [ ] Implement the failure event and non-blocking warning with the existing trail callback.
- [ ] Run the focused pipeline/trail persistence tests and observe green.
- [ ] Commit `feat: record unresolved figure-kind declarations (#551)` and push it.

### Task 4: Prompt and pipeline regression gates

**Files:**
- Modify only affected tests/fixtures as needed for the new required prompt contract.

- [ ] Run exactly the affected tests and required regressions: `tests/test_figure_policy.py`, `tests/test_figure_kind_diversity_social_studies.py`, `tests/test_ns_subq_image_contract.py`, `tests/server/test_figure_policy_trail_persistence.py`, and `tests/server/test_no_subject_dispatch.py`.
- [ ] Run formatting/type/lint checks applicable to touched Python files.
- [ ] Inspect `git diff`, verify the lane tree is clean, and push the final branch state.
