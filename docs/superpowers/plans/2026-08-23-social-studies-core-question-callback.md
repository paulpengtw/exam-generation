# 社會領域回扣核心問題 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the request-level `core_question_callback` 建議值 to 社會領域 generation, defaulting on and affecting only the 文本/子題 prompts, with CLI opt-out and exact preview parity.

**Architecture:** Thread one boolean through the existing shared generation-core prompt-building seam. The shared core resolves/truncates/pads `sq_plans` first, then passes `is_last` only to the resolved final slot; social-studies builders conditionally append additive prompt instructions, while samplers and verifiers remain untouched. The API model/route/subject adapter and web query builder forward the request field; other subjects accept the contract field but ignore it.

**Tech Stack:** Python 3, Pydantic/FastAPI, pytest, argparse, TypeScript/React generated request contract.

**Spec:** GitHub issue #433, `CONTEXT.md` glossary entry `回扣核心問題`, and the user request in this task.

## Global Constraints

- `core_question_callback` is a request-level boolean, default `True`, and is a 建議值 only.
- When on, only the final resolved 社會領域 子題 prompt gets the explicit callback instruction; the 文本生成器 user prompt also instructs the final planned 小題 to synthesize the 題組核心問題.
- When off, prompt bytes remain the pre-change bytes; no verifier rule, sampler draw, 題型/LC/LP change, or mechanical-draw change is allowed.
- Existing social-studies per-小題 configuration remains additive/supreme: its 題型, 出題指示, 學習內容, and 學習表現 text must remain present.
- Do not commit or branch; every test cycle is run in the current `staging` checkout.

---

### Task 1: Prompt-builder contract and byte-preserving opt-out

**Files:**
- Modify: `src/social_studies/context_builder.py`
- Test: `tests/test_social_studies_core_question_callback.py`

**Interfaces:**
- Produces `build_text_user_prompt(..., core_question_callback: bool = True)`.
- Produces `build_subquestion_user_prompt(..., core_question_callback: bool = True, is_last: bool = False)`.
- The off path must not append either callback block.

- [x] **Step 1: Write failing tests** for text on/off, subquestion last/non-last, and last-slot config composition. Use `disable_reference_fewshot=True` and fixed seeded params so prompt comparisons are deterministic.
- [x] **Step 2: Run** `uv run pytest -q tests/test_social_studies_core_question_callback.py` and confirm the new keyword arguments fail before implementation.
- [x] **Step 3: Add additive callback instruction constants and conditionally insert the text block and final-slot subquestion block; leave all existing assembly unchanged when false.
- [x] **Step 4: Run the focused test file and existing prompt tests; confirm green.

### Task 2: Resolved-last-slot threading through shared generation core

**Files:**
- Modify: `src/common/generation_core.py`, `src/common/subject_spec.py`
- Modify: `src/social_studies/cli.py`, `src/natural_sciences/cli.py`
- Test: `tests/test_enforced_subquestion_plan.py`, `tests/test_social_studies_core_question_callback.py`

**Interfaces:**
- Shared prompt builders receive `core_question_callback` and pass `is_last=(idx == len(resolved_plans))` for actual generation and preview generation.
- Social-studies `generate_one`, `generate_with_corrections`, `build_generation_prompts`, and `build_subquestion_prompt_previews` default the option on; natural sciences passes/retains false.

- [x] **Step 1: Add failing integration tests** capturing subquestion prompts for a truncation case and a padding case; assert only the resolved final index has the callback instruction. Add a seed-pinned sampler comparison showing the option does not alter sampled params.
- [x] **Step 2: Run the focused tests and confirm failure because the callback is not threaded/resolved yet.
- [x] **Step 3: Thread the boolean through `generate_one_core`, `generate_with_corrections_core`, prompt preview helpers, and both subject wrapper signatures; compute the last slot after existing truncation/padding logic.
- [x] **Step 4: Run the focused integration tests and existing enforced-plan/preview tests; confirm green.

### Task 3: Server request model, route, subject adapter, and prompt preview

**Files:**
- Modify: `server/generate/models.py`, `server/generate/routes.py`, `server/generate/service.py`, `server/generate/subjects.py`
- Modify: `tests/test_contract_forwarding_guard.py`, `tests/server/test_prompt_preview.py`, `tests/server/test_generate_routes.py`, `tests/server/test_per_question_params.py`

**Interfaces:**
- `GenerateParams.core_question_callback: bool = True` is request-level (not per-question), included in generated TypeScript contract.
- `/api/generate` explicitly accepts and forwards the query parameter; `/api/generate/preview` accepts it through `GenerateQuery` and returns exact on/off prompts.
- The social-studies adapter forwards the value to generation and both preview builders; math/NS accept the shared model field but ignore it.

- [x] **Step 1: Add failing tests** for model default/explicit false, route forwarding, preview on/off exact prompt content, and contract forwarding classification/proof.
- [x] **Step 2: Run the focused server/contract tests and confirm failure.
- [x] **Step 3: Add the model field to request-level classification, route parameter construction, worker kwargs, and SS subject adapter forwarding; pass the same value into service preview calls.
- [x] **Step 4: Run focused server/contract/preview tests; regenerate `web/src/api/generated/contract.ts` with `python scripts/generate_ts_contract.py` if drift requires it.

### Task 4: CLI opt-out flag

**Files:**
- Modify: `src/social_studies/cli.py`
- Test: `tests/test_social_studies_cli_coverage.py`, `tests/test_social_studies_core_question_callback.py`

**Interfaces:**
- `parse_args(["generate"])` yields `core_question_callback is True`.
- `--no-core-question-callback` stores `False` and is passed to the social-studies generation wrapper.

- [x] **Step 1: Add failing parser and dry-run/prompt-capture test for the flag.
- [x] **Step 2: Run the focused CLI tests and confirm failure.
- [x] **Step 3: Add `store_false` flag with default `True` and forward it through the CLI generation call.
- [x] **Step 4: Run focused CLI tests; confirm green.

### Task 5: Web wire forwarding and repository documentation

**Files:**
- Modify: `web/src/hooks/useGenerate.ts`, `web/src/components/ParamForm.tsx`, `web/src/components/ParamForm.request-level-fields.test.tsx`
- Modify: `CLAUDE.md`

**Interfaces:**
- The generated `GenerateParams` field is reachable by the web query builder when supplied, and request-level field filtering keeps it out of `per_question_params`.
- `CLAUDE.md` documents the default-on 建議值 semantics near 出題模式/request options, explicitly stating prompt-only behavior and no mechanical sampling/verifier effect.

- [x] **Step 1: Add/update failing contract-sync assertions for the new field and documentation anchor.
- [x] **Step 2: Run the focused frontend/Python documentation checks and confirm failure.
- [x] **Step 3: Append the field in the web query builder, update request-level strip-list fixtures, regenerate the TypeScript contract, and add the concise CLAUDE guidance.
- [x] **Step 4: Run focused frontend/Python checks; confirm green.

### Task 6: Full verification

**Files:**
- Test: all repository tests and lint configuration.

- [x] **Step 1: Run `uv run pytest -q`.
- [x] **Step 2: Run the repository ruff command from `pyproject.toml` (at minimum `uv run ruff check .`).
- [x] **Step 3: Inspect `git diff`, verify no commit/branch was created, and report files changed, red evidence per slice, final pytest summary, and ruff summary.

Repository-wide ruff remains red on the pre-existing baseline (209 findings across unrelated files); feature-specific new tests and the changed shared-core file pass targeted ruff checks.
