# 情境子類別 admitted_by Schema Payload Implementation Plan

> **For agentic workers:** This plan is executed inline in the current worktree under the user's strict TDD and verification constraints.

**Goal:** Make each natural-sciences 情境子類別 declare its admitting 情境 in the schema payload, then have server validation and web 預抽 use that same declaration.

**Architecture:** The natural-sciences schema loader will preserve the legacy `parent` field and add `admitted_by: {"情境": [parent]}` to each child entry. The server will validate explicit pairs against that shipped tag, while the web will expose one parent-keyed generic filter and resolve each batch 題組's 情境 before drawing its 情境子類別.

**Tech Stack:** Python 3.11+, Pydantic/FastAPI, React/TypeScript, Vitest, pytest.

**Spec:** GitHub issue #595 and ADR 0020, with ADR 0003 and ADR 0018 governing validation and 全量預抽.

## Global Constraints

- Work only in `/workspace/eg-wt/issue-595`.
- Use strict red→green TDD; expected values are independent literals.
- Prefix every test run with `choom -n 500 --`; targeted tests while iterating; full pytest at most once at the end with `-x -q -p no:cacheprovider`; never use xdist.
- Keep `parent` working for existing consumers and do not add an ADR.

---

### Task 1: Schema payload contract

**Files:**
- Modify: `tests/server/test_utility_routes.py`
- Modify: `src/natural_sciences/schema_loader.py`
- Modify: `src/common/schema_loader.py` only if the loader primitive needs the tag support

- [ ] Write a failing `/api/schemas?subject=natural_sciences` assertion that every 情境子類別 has the literal `admitted_by: {"情境": [parent]}` and retains `parent`.
- [ ] Run the targeted pytest and confirm it fails because `admitted_by` is absent.
- [ ] Add the minimal loader transformation and keep the legacy field intact.
- [ ] Run the targeted pytest and confirm it passes.

### Task 2: Server validation and backend sampling

**Files:**
- Modify: `tests/server/test_generate_params_validation.py` or a focused natural-sciences server test module
- Modify: `tests/test_natural_sciences_sampler.py` if sampler behavior needs a seam assertion
- Modify: `server/generate/subjects.py`
- Modify: `src/natural_sciences/sampler.py`

- [ ] Add independent compatible and incompatible `GenerateParams` validation cases, asserting incompatible pairs still produce the ADR 0003 message and compatible pairs pass.
- [ ] Run the targeted pytest red and verify the failure is caused by validation not reading the new tag.
- [ ] Read `admitted_by["情境"]` for validation and sampler parent matching, without constructing a separate parent map from `parent`.
- [ ] Run the targeted pytest green.

### Task 3: Generic web filter and #583 regression

**Files:**
- Create or modify: `web/src/lib/` generic admitted-parent filter and its Vitest test
- Modify: `web/src/api/client.ts`
- Modify: `web/src/components/ParamForm.tsx`
- Modify: `web/src/components/ParamForm.subquestion-predraw.test.tsx` or the closest ParamForm submit-seam test

- [ ] Add a failing ParamForm count=2 fixture with Personal/Global and one admitted child each; assert each submitted pair is compatible, with the avoid-previous rule forcing distinct contexts.
- [ ] Run the single Vitest file red and confirm the second pair is incompatible before the fix.
- [ ] Implement the generic filter and use it for the form child selector and every per-題組 child draw after resolving that 題組's own context.
- [ ] Add focused generic-filter coverage for scalar and multi-parent resolved values; run the Vitest tests green.
- [ ] Add/retain coverage that an explicitly pinned context suppresses per-題組 context drawing and only admits a compatible child.

### Task 4: Generated contract and documentation

**Files:**
- Modify: generated `web/src/api/generated/contract.ts` only by regeneration if the backend wire model changes
- Modify: `CLAUDE.md` under Script-side randomness and Web confirmation dialog pre-draw

- [ ] Run the contract drift guard and regenerate only if needed.
- [ ] Add 2–4 sentences documenting the shipped `admitted_by` tag and the generic filter/per-題組 resolution.

### Task 5: Verification and handoff

- [ ] Run the required lint, typecheck, targeted tests, and one final full pytest command exactly as requested.
- [ ] Review the diff for unrelated changes and preserve the pre-existing `.venv` symlink.
- [ ] Commit with `feat: 情境子類別 declares admitting 情境 in schema payload (#595)` and do not push.
