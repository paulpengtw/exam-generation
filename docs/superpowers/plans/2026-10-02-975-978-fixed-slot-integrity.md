# Fixed-slot Generation Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fixed Social Studies and Natural Sciences slots honor submitted pins, recover safe rubric-shape mismatches, and retain a bounded actionable failure reason through terminal, History, and teacher UI evidence.

**Architecture:** Subject parsers perform narrow scalar normalization and domain-pin stamping; the shared generation core owns fixed-slot admission, retry feedback, and pure-text visual suppression. Exhaustion is emitted as an existing structured stage event, captured by the server worker as a per-position sidecar, and carried through the existing optional `SlotRef`/History JSON path to one localized frontend projection.

**Tech Stack:** Python 3.11, Pydantic 2, pytest, FastAPI/SQLAlchemy test fixtures, TypeScript 6, React 19, Vitest/Testing Library, Ruff, ESLint.

**Spec:** `docs/superpowers/specs/2026-10-02-975-978-fixed-slot-integrity-design.md` ([approved design](https://github.com/paulpengtw/exam-generation/blob/fix/ready-for-agent-batch/docs/superpowers/specs/2026-10-02-975-978-fixed-slot-integrity-design.md))

## Global Constraints

- Use deterministic fake provider, renderer, database, and authenticated HTTP fixtures only. Never read or use a live LLM/image API key.
- Keep the configured subquestion retry count unchanged and create a fresh sub-client per attempt.
- Resolver/slot pins outrank model output; fixed identity remains `<question_id>-sqNNN` plus zero-based transport `subquestion_index`.
- Safe scalar normalization applies only to string `學生作答實例`; do not admit arbitrary malformed rubric data.
- Failure detail is one line, at most 240 Unicode code points; exception class names use identifier characters only and at most 64 code points.
- Never persist or display prompts, complete responses, provider messages, reasoning, credentials, request IDs, or arbitrary exception text.
- Preserve sibling independence, save-before-result ordering, terminal sealing, confirmed cancellation, and ordinary client-disconnect semantics.
- Optional evidence fields must remain backward-compatible with existing stream fixtures and History rows.
- Use `choom -n 500 --` for memory-heavy test commands and no more than three concurrent lanes.

## Review Focus

- A scalar student example normalizes, but a number/object/list member of the wrong type still fails safely; Task 1 tests all three classes.
- Normalization must not admit duplicate/missing rubric codes, wrong example counts, or a missing fixed `[2]` sentence; Task 2 tests the exact observed duplicate-code retry.
- A pure-text slot carrying both a model `chart_spec` and `gpt_image` mode must remain image-free before and after correction while visual siblings render; Task 3 tests both passes.
- Newlines, overlength diagnostic strings, invalid failure codes, and private exception/provider text must never reach persistence/UI; Tasks 2, 4, and 5 test each boundary.
- Reordered terminal slots, old History rows, confirmed cancellation, and transient disconnect must retain existing identity/conflict/outcome behavior; Tasks 4 and 5 add compatibility tests.

---

### Task 1: Normalize scalar rubric examples and stamp domain pins

**Files:**
- Create: `src/common/subquestion_contract.py`
- Create: `tests/test_subquestion_contract.py`
- Modify: `src/natural_sciences/cli.py:383-503`
- Modify: `src/social_studies/cli.py:467-595`
- Modify: `tests/test_ns_grade_forced.py`
- Modify: `tests/test_ss_grade_forced.py`

**Interfaces:**
- Consumes: raw `評分規準` rows from both subject parsers and their resolved `SampledParams`.
- Produces: `normalize_rubric_student_examples(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]`; parsed NS rows whose `科學能力` equals the resolved pool; parsed SS rows whose `核心素養` equals the resolved pool.

- [ ] **Step 1: Write failing pure-helper tests**

  In `tests/test_subquestion_contract.py`, add tests asserting the helper copies rows, converts only a scalar string to `[string]`, preserves valid lists, and leaves number/object values unnormalized so Pydantic still rejects them.

- [ ] **Step 2: Run the helper test and verify RED**

  Run: `choom -n 500 -- uv run pytest tests/test_subquestion_contract.py -q`

  Expected: collection/import failure because `normalize_rubric_student_examples` does not exist.

- [ ] **Step 3: Implement the narrow copy-and-normalize helper**

  Add exactly this public signature in `src/common/subquestion_contract.py`:

  ```python
  def normalize_rubric_student_examples(
      rows: Sequence[Mapping[str, Any]],
  ) -> list[dict[str, Any]]:
  ```

  Return copied dictionaries; convert only `isinstance(value, str)` to `[value]`.

- [ ] **Step 4: Write failing subject-parser tests**

  Extend the NS/SS grade-forcing test files with direct `_parse_subquestion` cases asserting scalar examples become one-entry lists, numeric/object examples raise `SubquestionParseError`, model-emitted grade is ignored, NS `科學能力` is exactly the resolved value, SS `核心素養` is exactly the resolved value, and configured LC/LP pins remain exact.

- [ ] **Step 5: Run the parser tests and verify RED**

  Run: `choom -n 500 -- uv run pytest tests/test_subquestion_contract.py tests/test_ns_grade_forced.py tests/test_ss_grade_forced.py -q`

  Expected: scalar examples fail list validation and model-emitted competency values survive.

- [ ] **Step 6: Wire both parsers and stamp competencies**

  Normalize copied rubric rows before `RubricEntry` construction. Preserve the current grade, subject, LC/LP, reporting-scale, instruction, and cognitive-process rules; additionally force NS `科學能力` from `params.科學能力` and SS `核心素養` from `params.核心素養`.

- [ ] **Step 7: Run focused tests and lint**

  Run:

  ```bash
  choom -n 500 -- uv run pytest tests/test_subquestion_contract.py tests/test_ns_grade_forced.py tests/test_ss_grade_forced.py -q
  uv run ruff check src/common/subquestion_contract.py src/natural_sciences/cli.py src/social_studies/cli.py tests/test_subquestion_contract.py tests/test_ns_grade_forced.py tests/test_ss_grade_forced.py
  ```

  Expected: PASS.

- [ ] **Step 8: Commit**

  ```bash
  git add src/common/subquestion_contract.py src/natural_sciences/cli.py src/social_studies/cli.py tests/test_subquestion_contract.py tests/test_ns_grade_forced.py tests/test_ss_grade_forced.py
  git commit -m "fix: normalize fixed-slot rubric examples" -m "Implements parser and pin requirements from https://github.com/paulpengtw/exam-generation/issues/977."
  ```

### Task 2: Admit fixed slots once and provide safe retry feedback

**Files:**
- Create: `src/common/subquestion_failure.py`
- Modify: `src/common/subquestion_contract.py`
- Modify: `src/common/generation_core.py:164-240,580-780`
- Modify: `tests/test_subquestion_contract.py`
- Modify: `tests/test_subgen_failure_diagnostics.py`
- Modify: `tests/test_subgen_retry_natural_sciences.py`
- Modify: `tests/test_subgen_retry_social_studies.py`

**Interfaces:**
- Consumes: parsed subquestion, question id, zero-based plan position, fixed-identity flag, and the matching `SubQuestionConfig`.
- Produces: `apply_fixed_subquestion_contract(...) -> str | None`; `SubquestionFailureCode = Literal["validation_exhausted", "parser_failure", "provider_failure", "unknown"]`; `sanitize_failure_detail(value: str | None) -> str | None`; exhausted stage fields `code`, `failure_code`, and optional `failure_detail`.

- [ ] **Step 1: Write failing slot-contract unit tests**

  Assert `apply_fixed_subquestion_contract` restores id/sequence/private plan index, coerces configured question type, forces configured content type, and returns the first safe open-response rubric-shape issue for duplicate/missing codes, wrong counts, blank examples, and missing fixed `[2]` sentence. Valid rubrics return `None`.

- [ ] **Step 2: Run unit tests and verify RED**

  Run: `choom -n 500 -- uv run pytest tests/test_subquestion_contract.py -q`

  Expected: failures because the admission function is absent.

- [ ] **Step 3: Implement the shared admission and diagnostic primitives**

  Add:

  ```python
  def apply_fixed_subquestion_contract(
      subquestion: Any,
      *,
      question_id: str,
      plan_position: int,
      slot_config: Any | None,
      fixed_identity: bool,
  ) -> str | None:
  ```

  Reuse `is_open_response` and `check_open_response_rubric_shape`; return a safe reason instead of importing/raising `SubquestionParseError`. In `subquestion_failure.py`, define the literal type, 240/64 bounds, newline collapse, and identifier-only exception-class sanitizer.

- [ ] **Step 4: Write failing public-pipeline tests for observed response shapes**

  Extend `tests/test_subgen_failure_diagnostics.py` with fake clients that record each user prompt and reproduce both subjects plus the exact NS sequence: scalar examples on attempt one; scalar examples, grade drift, and `2 / 1 / 1 / 0` on attempt two. Assert scalar-only rows recover, the invalid duplicate-code row is dropped without changing siblings, the second prompt names only the safe prior shape error, submitted pins never drift, and the error event has the structured exhaustion fields with no fixture-private text.

- [ ] **Step 5: Run pipeline tests and verify RED**

  Run:

  ```bash
  choom -n 500 -- uv run pytest tests/test_subgen_failure_diagnostics.py tests/test_subgen_retry_natural_sciences.py tests/test_subgen_retry_social_studies.py -q
  ```

  Expected: retry prompts are identical, duplicate rubric shape is admitted until later verification, and structured fields are absent.

- [ ] **Step 6: Apply the contract inside the retry decision**

  Replace `_apply_fixed_subquestion_identity` calls with `apply_fixed_subquestion_contract`. Convert a returned reason into `SubquestionParseError` before accepting the attempt. For retry attempts, append only the immediately preceding safe `SubquestionParseError.reason` to a per-attempt prompt value; never mutate/accumulate the base prompt. Track the failure code separately and emit it only after exhaustion.

- [ ] **Step 7: Prove recovery stays silent and exhaustion stays bounded**

  Add assertions that recovered slots emit no error/failure sidecar, provider exceptions retain only sanitized class names, unexpected parser exceptions retain no exception message, details collapse newlines and truncate to 240 code points, retry counts/fresh-client counts are unchanged, and sibling call counts remain one.

- [ ] **Step 8: Run focused tests and lint**

  Run:

  ```bash
  choom -n 500 -- uv run pytest tests/test_subquestion_contract.py tests/test_subgen_failure_diagnostics.py tests/test_subgen_retry_natural_sciences.py tests/test_subgen_retry_social_studies.py -q
  uv run ruff check src/common/subquestion_contract.py src/common/subquestion_failure.py src/common/generation_core.py tests/test_subquestion_contract.py tests/test_subgen_failure_diagnostics.py
  ```

  Expected: PASS.

- [ ] **Step 9: Commit**

  ```bash
  git add src/common/subquestion_contract.py src/common/subquestion_failure.py src/common/generation_core.py tests/test_subquestion_contract.py tests/test_subgen_failure_diagnostics.py tests/test_subgen_retry_natural_sciences.py tests/test_subgen_retry_social_studies.py
  git commit -m "fix: enforce the fixed-slot retry contract" -m "Implements https://github.com/paulpengtw/exam-generation/issues/976 and https://github.com/paulpengtw/exam-generation/issues/977."
  ```

### Task 3: Suppress pure-text visuals before every figure-policy pass

**Files:**
- Modify: `src/common/subquestion_contract.py`
- Modify: `src/common/generation_core.py:780-940,1080-1245`
- Modify: `tests/test_ns_subq_image_contract.py`
- Modify: `tests/test_ns_subq_chart_spec_repair.py`
- Modify: `tests/test_correction_visual_pins.py`
- Modify: `tests/server/test_question_terminal.py`

**Interfaces:**
- Consumes: Task 2's `apply_fixed_subquestion_contract` and fixed `_plan_index`.
- Produces: pure-text rows with `題目內容類型="純文字"`, `chart_spec=None`, optional `image_spec=None`, and `圖片=None` before initial/correction figure policy; visual siblings remain unchanged.

- [ ] **Step 1: Write the failing six-slot regression**

  Add a deterministic NS case with two explicit visual slots followed by four explicit pure-text slots. Every fake sub-generator response includes a valid `chart_spec` and `gpt_image` mode. Assert exactly two repair/render calls, slots 3–6 have no visual fields/files, and terminal expected image slots contain positions 0 and 1 only.

- [ ] **Step 2: Run the mixed-slot tests and verify RED**

  Run:

  ```bash
  choom -n 500 -- uv run pytest tests/test_ns_subq_image_contract.py tests/test_ns_subq_chart_spec_repair.py tests/server/test_question_terminal.py -q
  ```

  Expected: model visuals survive in slots 3–6 and create render/terminal obligations.

- [ ] **Step 3: Clear visuals in the shared contract before assembly**

  When and only when `slot_config.content_type == "純文字"`, force the content type and clear `chart_spec`, `image_spec` if present, and `圖片`. Do not treat request/model `image_generation_mode` as a visual obligation. Leave `含圖片` and `graphs/charts/tables` rows untouched.

- [ ] **Step 4: Write the failing correction regression**

  Extend `tests/test_correction_visual_pins.py` so an accepted correction tries to attach a visual to a pure-text slot while also changing identity/type. Assert the second contract application restores all pins before visual-change detection, does not render that slot, and still rerenders the explicit visual siblings as required.

- [ ] **Step 5: Reapply the contract after accepted correction**

  Before assigning the returned candidate to `question`, run a small shared-core loop keyed by each row's fixed `_plan_index`. If every row returns `None`, adopt the candidate before `visual_specs_changed`/post-correction policy. If a row returns a reason, retain the entering question and replace the local decision with `CorrectionDecision(outcome="rejected", reason=CorrectionRejection(code="fixed_slot_contract", path="subquestions[N]", message=reason))`, so the existing rejection event/trail path publishes no rejected content.

- [ ] **Step 6: Run focused tests and lint**

  Run:

  ```bash
  choom -n 500 -- uv run pytest tests/test_ns_subq_image_contract.py tests/test_ns_subq_chart_spec_repair.py tests/test_correction_visual_pins.py tests/server/test_question_terminal.py -q
  uv run ruff check src/common/subquestion_contract.py src/common/generation_core.py tests/test_ns_subq_image_contract.py tests/test_ns_subq_chart_spec_repair.py tests/test_correction_visual_pins.py
  ```

  Expected: PASS with only two visual obligations in the six-slot case.

- [ ] **Step 7: Commit**

  ```bash
  git add src/common/subquestion_contract.py src/common/generation_core.py tests/test_ns_subq_image_contract.py tests/test_ns_subq_chart_spec_repair.py tests/test_correction_visual_pins.py tests/server/test_question_terminal.py
  git commit -m "fix: suppress visuals for pinned pure-text slots" -m "Implements https://github.com/paulpengtw/exam-generation/issues/975."
  ```

### Task 4: Carry exhausted-slot evidence through terminal and History

**Files:**
- Modify: `server/generate/event_protocol.py:47-75`
- Modify: `server/generate/question_terminal.py:40-365`
- Modify: `server/generate/service.py:480-680,715-985`
- Modify: `server/history/routes.py:186-210` only if typing/normalization requires it
- Modify: `tests/server/test_question_terminal.py`
- Modify: `tests/server/test_858_worker_split_units.py`
- Modify: `tests/server/test_937_service_partial_delivery.py`
- Create: `tests/server/test_subquestion_failure_history.py`

**Interfaces:**
- Consumes: Task 2's `subquestion_exhausted` stage event keyed by zero-based `subquestion_index`.
- Produces: `_WorkerRecorderSetup.subquestion_failures: dict[int, dict[str, str]]`; `_QuestionPositionResolution.subquestion_failures`; optional `SlotRef.failure_code` and `SlotRef.failure_detail`; identical live and persisted missing-slot evidence.

- [ ] **Step 1: Write failing protocol and pure-terminal tests**

  Assert optional fields validate only the four allowed codes, reject multiline/over-240 details, remain excluded from `SlotRef` identity, map evidence only to the exact missing manifest position, prefer concrete evidence over generic fallback, leave image reasons unchanged, and accept old payloads with only `reason`.

- [ ] **Step 2: Run terminal tests and verify RED**

  Run: `choom -n 500 -- uv run pytest tests/server/test_question_terminal.py -q`

  Expected: optional fields are dropped/rejected as extras and resolution cannot receive the map.

- [ ] **Step 3: Extend protocol and pure terminal composition**

  Add the optional Pydantic fields and validators. Extend `_QuestionPositionResolution` with an immutable mapping. For a missing subquestion use the exact-position structured record; otherwise retain `reason="subquestion not delivered"` and classify no more specifically than the terminal-level outcome permits. Keep identity and partition validation unchanged.

- [ ] **Step 4: Write failing worker-capture tests**

  In `test_858_worker_split_units.py`, feed `_setup_worker_recorders` unrelated errors, malformed indices/codes, a valid exhaustion event, then a newer valid event for the same slot. Assert only the valid last record is captured and publishing still receives every original event.

- [ ] **Step 5: Capture and thread the private sidecar**

  Extend `observe_worker_event` to record only `stage/llm_generate/error` events with `code="subquestion_exhausted"`, a valid zero-based index, allowed code, and bounded optional detail. Pass the map to both the save-before-result terminal-delivery computation and `_finalize_worker_terminal`; do not add another callback to subject wrappers.

- [ ] **Step 6: Write failing live/History round-trip tests**

  Drive a deterministic authenticated detached generation whose middle slot exhausts validation. Assert the live `question_terminal.missing` record and `GET /api/history/{id}.terminal_delivery.missing` record are equal, bounded, sanitized, and attached to the original fixed id/index; slots 1 and 3 are delivered. Add provider-failure, unknown-fallback, confirmed-cancel, and client-disconnect cases proving their existing outcomes are not relabeled.

- [ ] **Step 7: Run backend integration tests and lint**

  Run:

  ```bash
  choom -n 500 -- uv run pytest tests/server/test_question_terminal.py tests/server/test_858_worker_split_units.py tests/server/test_937_service_partial_delivery.py tests/server/test_subquestion_failure_history.py -q
  uv run ruff check server/generate/event_protocol.py server/generate/question_terminal.py server/generate/service.py server/history/routes.py tests/server/test_question_terminal.py tests/server/test_858_worker_split_units.py tests/server/test_937_service_partial_delivery.py tests/server/test_subquestion_failure_history.py
  ```

  Expected: PASS.

- [ ] **Step 8: Commit**

  ```bash
  git add server/generate/event_protocol.py server/generate/question_terminal.py server/generate/service.py server/history/routes.py tests/server/test_question_terminal.py tests/server/test_858_worker_split_units.py tests/server/test_937_service_partial_delivery.py tests/server/test_subquestion_failure_history.py
  git commit -m "fix: persist exhausted-slot failure evidence" -m "Implements backend evidence requirements from https://github.com/paulpengtw/exam-generation/issues/978."
  ```

### Task 5: Localize structured missing-slot reasons in live and History UI

**Files:**
- Modify: `web/src/lib/generationEvidence.ts:20-250,340-375`
- Modify: `web/src/lib/generationEvidence.test.ts`
- Modify: `web/src/components/QuestionCard.tsx:500-530`
- Modify: `web/src/components/QuestionCard.test.tsx`
- Modify: `web/src/i18n/messages.ts`
- Modify: `web/src/api/client.ts:355-390`
- Modify: `web/src/utils/exportSnapshot.test.ts`
- Modify: `web/src/pages/HistoryDetail.card-state.test.tsx`

**Interfaces:**
- Consumes: Task 4's optional `failure_code` and `failure_detail` fields on `GenerationSlotReference`.
- Produces: strict live/History parsing and one localized `MissingSubQuestionBlock` projection for validation, parser, provider, unknown, and legacy reasons.

- [ ] **Step 1: Write failing evidence-parser tests**

  Assert all four codes plus a 240-character one-line detail survive parsing and terminal comparison; an unknown code, newline, 241-character detail, non-string detail, or changed evidence on a resent terminal is rejected/flagged using existing terminal-conflict semantics. Old `reason`-only and image slots still parse.

- [ ] **Step 2: Run evidence tests and verify RED**

  Run: `choom -n 500 -- npm test -- src/lib/generationEvidence.test.ts`

  Expected: fields are not represented/validated and terminal equality ignores the intended type contract.

- [ ] **Step 3: Extend the TypeScript contract and parser**

  Add `SubquestionFailureCode`, optional fields to `GenerationSlotReference`, a closed-set guard, and detail-bound validation in `parseSlotReferences`. Keep `slotKey` identity unchanged; allow `slotMultisetKey` to retain explanatory evidence so contradictory resends remain detectable.

- [ ] **Step 4: Write failing component and History tests**

  Add table-driven QuestionCard assertions for localized validation/parser/provider/unknown summaries, optional safe detail, and the existing legacy `reason`. Extend HistoryDetail/export tests to prove the same structured object survives typed read-back. Assert confirmed cancellation still renders cancellation and transport disconnect does not render a fabricated slot cause.

- [ ] **Step 5: Add localization and one rendering helper**

  Add matching en-US/zh-TW keys under `card.missing_failure_*`. In `QuestionCard.tsx`, map recognized codes to localized summaries, append safe detail, and use the old reason renderer only when structured fields are absent.

- [ ] **Step 6: Run frontend checks**

  Run:

  ```bash
  choom -n 500 -- npm test -- src/lib/generationEvidence.test.ts src/components/QuestionCard.test.tsx src/utils/exportSnapshot.test.ts src/pages/HistoryDetail.card-state.test.tsx
  npx tsc -b --noEmit
  npm run lint
  ```

  Working directory: `web/`.

  Expected: PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add web/src/lib/generationEvidence.ts web/src/lib/generationEvidence.test.ts web/src/components/QuestionCard.tsx web/src/components/QuestionCard.test.tsx web/src/i18n/messages.ts web/src/api/client.ts web/src/utils/exportSnapshot.test.ts web/src/pages/HistoryDetail.card-state.test.tsx
  git commit -m "fix: explain exhausted slots in generation evidence" -m "Implements teacher-facing evidence requirements from https://github.com/paulpengtw/exam-generation/issues/978."
  ```

### Task 6: Document contracts, verify the branch, and review against the issues

**Files:**
- Modify: `CLAUDE.md:1-25,238-259,350-365`
- Modify: `MEMORY.md`
- Modify: implementation/test files only if verification or review finds a demonstrated defect

**Interfaces:**
- Consumes: all prior task contracts and commits.
- Produces: durable repository guidance, full-suite evidence, and parallel Standards/Spec review against `origin/staging`.

- [ ] **Step 1: Update durable documentation**

  Record the fixed-slot admission order, scalar-only normalization, pure-text visual suppression, structured failure bounds/codes, observer capture seam, existing JSON persistence path, and legacy compatibility in `CLAUDE.md`. Add a concise dated `MEMORY.md` entry describing the authoritative seam and the rule that client disconnect is not cancellation.

- [ ] **Step 2: Run focused cross-layer acceptance**

  Run the two commands below as the only two active lanes:

  ```bash
  choom -n 500 -- uv run pytest tests/test_subquestion_contract.py tests/test_ns_grade_forced.py tests/test_ss_grade_forced.py tests/test_subgen_failure_diagnostics.py tests/test_subgen_retry_natural_sciences.py tests/test_subgen_retry_social_studies.py tests/test_ns_subq_image_contract.py tests/test_ns_subq_chart_spec_repair.py tests/test_correction_visual_pins.py tests/server/test_question_terminal.py tests/server/test_858_worker_split_units.py tests/server/test_937_service_partial_delivery.py tests/server/test_subquestion_failure_history.py -q
  choom -n 500 -- npm --prefix web test -- src/lib/generationEvidence.test.ts src/components/QuestionCard.test.tsx src/utils/exportSnapshot.test.ts src/pages/HistoryDetail.card-state.test.tsx
  ```

  Expected: every focused test passes with no provider credential configured.

- [ ] **Step 3: Run repository checks**

  Run:

  ```bash
  uv run ruff check src/ server/ tests/
  choom -n 500 -- uv run pytest -q
  npm --prefix web exec -- tsc -b --noEmit
  npm --prefix web run lint
  choom -n 500 -- npm --prefix web test
  ```

  Expected: Python equals or exceeds the 3,494-pass/1-skip baseline; frontend equals or exceeds the 2,316-test/209-file baseline; lint/typecheck pass.

- [ ] **Step 4: Commit documentation**

  ```bash
  git add CLAUDE.md MEMORY.md
  git commit -m "docs: record fixed-slot evidence invariants" -m "Documents https://github.com/paulpengtw/exam-generation/issues/975, https://github.com/paulpengtw/exam-generation/issues/976, https://github.com/paulpengtw/exam-generation/issues/977, and https://github.com/paulpengtw/exam-generation/issues/978."
  ```

- [ ] **Step 5: Run the required parallel code review**

  Apply `mattpocock-skills:code-review` with fixed point `origin/staging`: one pinned `gpt-5.6-luna`/`max` subagent reviews repository standards and one reviews issue/spec conformance. Verify both reports directly with `git diff origin/staging...HEAD`, rerun every cited test, and fix only evidenced findings through a new red/green cycle.

- [ ] **Step 6: Re-run fresh verification after review fixes**

  Re-run the affected focused tests plus all five repository checks from Step 3. Do not claim completion from earlier output.

- [ ] **Step 7: Inspect final branch state**

  Run:

  ```bash
  git status --short --branch
  git log --oneline origin/staging..HEAD
  git diff --check origin/staging...HEAD
  git diff --stat origin/staging...HEAD
  ```

  Expected: clean worktree; only approved design/plan/docs and #975–#978 implementation changes; no API-key artifacts, generated images, database files, or unrelated edits.

The issues remain open until their pull request is merged into `staging`, per the repository's issue-tracker policy. After this subproject is verified, begin the separately approved spec/plan cycle for #962, #965, and #972–#974.
