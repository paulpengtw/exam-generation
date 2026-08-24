# NS Subquestion Chart Spec Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair a missing Natural Sciences 小題 `chart_spec` exactly once when that slot’s configuration requires a visual, then render the repaired spec without aborting the 題組 on repair failure.

**Architecture:** Keep the existing `generation_core` lifecycle unchanged. Add an NS-local `ensure_visual_spec_fn` callback that resolves each parsed subquestion back to its plan slot, sends a sanitized repair request only for `含圖片` or `graphs/charts/tables`, adopts a valid returned `chart_spec`, and leaves the existing NS renderer responsible for the image endpoint call.

**Tech Stack:** Python, Pydantic schemas, pytest, `uv run pytest`.

**Spec:** GitHub issue #531 and the user-provided acceptance criteria in this task.

## Global Constraints

- Do not modify `web/`.
- Do not run `tests/integration/`; use `uv run pytest -q <paths>` with `UV_CACHE_DIR=/tmp/exam-generation-uv-cache` in this sandbox.
- `image_generation_mode` is rendering-only and must not trigger repair by itself.
- Repair exceptions or malformed repair responses must leave the 題組 result alive without a subquestion image.
- Commit on the existing `feat/531-ns-subq-chart-spec-repair` branch and do not push.

---

### Task 1: Add the red NS repair seam tests

**Files:**
- Create: `tests/test_ns_subq_chart_spec_repair.py`

**Interfaces:**
- Consumes: `src.natural_sciences.cli.generate_one`, `sample_params`, and the existing `sub_client_factory` seam.
- Produces: Four regression tests covering successful repair/rendering, plain-text no-op, mode-only no-op, and graceful repair failure.

- [ ] **Step 1: Write the failing test**

Create a main-client fake whose first `generate_json` call returns a three-slot text shell, whose later calls record repair prompts and return a valid `chart_spec`, and whose `generate_image` writes a sentinel PNG. Create a sub-client fake that returns valid Natural Sciences subquestions but omits `chart_spec`. Configure only slot 1 as `{"content_type": "含圖片", "image_generation_mode": "gpt_image"}` and call NS `generate_one` with `skip_verify=True`, `disable_reference_fewshot=True`, and the fake factory.

The primary assertion must be behavioral: exactly one main-client repair call, a non-null `question.subquestions[0].chart_spec`, a PNG at `<tmp>/ns_repair_test_sq1.png`, one captured image call, and the expected image path. Add separate tests asserting zero repair calls for slot content type `純文字` and for a config containing only `image_generation_mode`. Add a failure fake that raises on the repair call and assert `generate_one` returns an `ExamQuestion`, leaves the missing spec unset, and writes no PNG.

- [ ] **Step 2: Run the new test to verify it fails for the missing wiring**

Run:

```bash
UV_CACHE_DIR=/tmp/exam-generation-uv-cache uv run pytest -q tests/test_ns_subq_chart_spec_repair.py
```

Expected: the successful-repair test fails because `_NS_SPEC.ensure_visual_spec_fn` is currently `None`, so the main fake records zero repair calls and no repaired image is rendered. The no-op tests may pass; the red evidence must identify the missing production behavior rather than a fixture/import error.

### Task 2: Wire NS subquestion chart-spec repair

**Files:**
- Modify: `src/natural_sciences/cli.py` near the existing NS parser/renderer and `_NS_SPEC` declaration.

**Interfaces:**
- Consumes: parsed NS `SubQuestion._plan_index`, `params.subquestion_configs`, `client.generate_json`, and the existing `_ns_render_subquestion_images` callback.
- Produces: `_ns_ensure_visual_spec(question, params, client)` assigned to `_NS_SPEC.ensure_visual_spec_fn`.

- [ ] **Step 1: Add the minimal NS repair contract**

Define the visual content set `{"含圖片", "graphs/charts/tables"}` and an NS repair system/user prompt pair requiring a single JSON `chart_spec` for the specific 小題. Resolve a subquestion’s config by `_plan_index` with `序號` as the fallback. For each visual-configured slot with a missing spec, serialize the subquestion while excluding `圖片`, `答案`, `答案解析`, `評分規準`, and `誘答分析`, then call the main client once with `purpose="generate"`. Accept either `image_spec` or `chart_spec`, parse a valid NS `ImageSpec`, and assign it to the subquestion.

Catch exceptions and ignore invalid repair payloads after logging a warning; do not re-raise. Do not call the client for an existing spec, a plain-text slot, a mode-only slot, or a missing client. Assign the callback to `_NS_SPEC.ensure_visual_spec_fn`; leave `_ns_render_subquestion_images` as the rendering-only stage so a repaired spec reaches the existing image endpoint.

- [ ] **Step 2: Run the focused tests to verify they pass**

Run:

```bash
UV_CACHE_DIR=/tmp/exam-generation-uv-cache uv run pytest -q tests/test_ns_subq_chart_spec_repair.py tests/test_ns_subq_image_contract.py tests/test_ss_subq_chart_spec_repair.py
```

Expected: all focused NS and SS repair/contract tests pass, including exactly one repair call and one rendered NS image for the missing-spec case.

### Task 3: Verify the repository and commit

**Files:**
- Verify: `src/natural_sciences/cli.py`, `tests/test_ns_subq_chart_spec_repair.py`, and this plan file.

**Interfaces:**
- Consumes: the green focused implementation from Tasks 1–2.
- Produces: a clean, committed branch with the full non-integration test summary recorded in the final report.

- [ ] **Step 1: Run the full non-integration suite**

Run:

```bash
UV_CACHE_DIR=/tmp/exam-generation-uv-cache uv run pytest -q --ignore=tests/integration
```

Expected: exit code 0; record the exact final summary line for the report.

- [ ] **Step 2: Inspect scope and commit the verified change**

Run `git diff --check`, `git status --short`, and `git diff --stat` to confirm only the plan, NS CLI, and NS repair tests changed and `web/` is untouched. Then commit with a conventional message referencing the issue:

```bash
git add docs/superpowers/plans/2026-08-25-ns-subq-chart-spec-repair.md src/natural_sciences/cli.py tests/test_ns_subq_chart_spec_repair.py
git commit -m "feat: repair missing NS subquestion chart specs (#531)"
```

- [ ] **Step 3: Re-check the committed state**

Run `git status --short --branch` and `git log -1 --oneline` after the commit. Report the commit hash, red failure output, focused green result, full-suite summary, and any conservative ambiguity decisions.
