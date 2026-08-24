# Retire Social-Studies PISA Axes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire `閱讀歷程` and `文本形式` from all new social-studies generation paths while preserving tolerant deserialization and faithful rendering of legacy records.

**Architecture:** Keep one `ExamQuestion` model with optional string-typed legacy fields. The presence of `認知歷程` identifies ICCS-era records; sampler parameters, schema categories, prompts, and request overrides contain only the live ICCS axes and the standalone six-value `題目內容類型` axis. The web layer conditionally renders each record's own era and keeps the request contract free of retired fields.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, pytest, React/TypeScript, Vitest, generated TypeScript contract.

**Spec:** User issue #498 brief in the conversation.

## Global Constraints

- New social-studies records must not populate `閱讀歷程` or `文本形式`.
- Legacy records must deserialize arbitrary string values for those fields.
- Natural-sciences schema categories and API output must remain unchanged.
- `per_question_params` must reject retired-axis keys as unknown parameters.
- Every commit message is conventional and ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Do not push.

### Task 1: Model, sampler, and schema retirement

**Files:**
- Modify: `src/social_studies/schemas.py`
- Modify: `src/social_studies/sampler.py`
- Modify: `src/social_studies/schema_loader.py`
- Modify: `src/common/subject_spec.py`
- Modify: `data/social_studies/curriculum/schema_parameters.csv`
- Test: `tests/test_retire_old_axes.py`

- [ ] Write tests proving the retired enums/categories disappear, legacy arbitrary strings load, and the sampler returns no retired fields.
- [ ] Run the focused test file and observe the expected failures against the current enum-backed sampler.
- [ ] Remove enum construction/exports and sampler draws; make `ExamQuestion` legacy fields optional strings with empty/`None` defaults.
- [ ] Remove the two CSV categories and update the social-studies category tuple.
- [ ] Run focused tests and the existing ICCS sampler/schema tests.
- [ ] Commit test and implementation slices separately when the repository permits commits.

### Task 2: Generation, prompts, request validation, and contract

**Files:**
- Modify: `src/social_studies/cli.py`
- Modify: `server/generate/models.py`
- Regenerate: `web/src/api/generated/contract.ts`
- Modify: affected Python tests and fixtures under `tests/`
- Test: `tests/test_retire_old_axes.py`

- [ ] Add a stubbed generation assertion that serialized new social-studies output has no populated retired tags and prompt sources contain no retired-axis path.
- [ ] Run it red before changing generation code.
- [ ] Delete CLI forcing/printing of sampled retired values and update sampler-dependent fixtures.
- [ ] Confirm request fields were response-only; retain no request fields and add unknown-key validation coverage for `per_question_params`.
- [ ] Regenerate the TypeScript contract and run server contract tests.
- [ ] Run the focused backend generation/prompt/verifier gates.
- [ ] Commit the test and implementation halves separately when possible.

### Task 3: Legacy/new rendering and final verification

**Files:**
- Modify: `web/src/hooks/useGenerate.ts`
- Modify: `web/src/utils/odt.ts`
- Modify: `web/src/components/QuestionCard.tsx`
- Modify: affected web tests and Python fixtures under `tests/`
- Test: `web/src/utils/odt.test.ts`, `web/src/components/QuestionCard.test.tsx`, `tests/test_retire_old_axes.py`

- [ ] Add legacy and ICCS-era fixtures covering ODT metadata and history-card tags.
- [ ] Run the rendering tests red if the current renderer drops legacy social-studies tags.
- [ ] Conditionally render legacy tags only for records without ICCS cognitive tags; render ICCS tags for new records.
- [ ] Keep `HistoryDetail` as the record pass-through and verify it with the existing card tests.
- [ ] Run all requested Python, server, Vitest, and TypeScript gates.
- [ ] Review the diff, list fixture judgment calls, and make the final paired commits if possible.
