# Issue #754 — Part A Verification

Date: 2026-09-27  
Branch: `feat/748-754-live-progress-export`

## Scope

Part A of issue #754: fixtures, cross-layer verification, compatibility matrix
backend, frontend fixture transport, and ODT browser test extensions.

Part B (ADR, protocol docs, CONTEXT.md glossary, acceptance pack) is out of
scope for this pass.

---

## Fixture Registry

### V2 fixtures (`tests/fixtures/generation_v2/`)

| File | Generator test | Variant |
|---|---|---|
| `math_single_interleaved.jsonl` | `test_742_fixture.py::test_interleaved_fixture` | B finishes before A, 2 questions |
| `math_groups_interleaved.jsonl` | `test_745_adapter_fixtures.py::test_fixed_adapter_fixture_and_terminal[math]` | math 題組, multiple revisions |
| `social_groups_interleaved.jsonl` | `test_744_social_fixture.py::test_social_fixed_slot_fixture_and_terminal` | social fixed slots |
| `natural_sciences_groups_interleaved.jsonl` | `test_745_adapter_fixtures.py::test_fixed_adapter_fixture_and_terminal[natural_sciences]` | NS fixed slots |
| `math_abcd_transport.jsonl` | `test_747_abcd_fixture.py::test_real_publisher_fixture_captures_transport_omitted_terminal` | q_RUN_004 terminal omitted (seq 19 absent — intentional gap) |

### Legacy fixtures (`tests/fixtures/generation_legacy/`)

| File | Notes |
|---|---|
| `math_single_legacy.jsonl` | S0 format: `{event, data}`, no `context`/`payload`, no `event_seq` |

### Regeneration command

```bash
bash scripts/generate_v2_fixtures.sh
```

No paid models required — all fixtures use `_FakeClient` stubs.

After regeneration, verify with:

```bash
choom -n 500 -- uv run pytest tests/server/test_754_fixture_drift.py -q
```

---

## Compatibility Matrix Results

### Matrix cells

| | S0 (old backend) | S1 (new backend, 426 gate) |
|---|---|---|
| **C0** (old frontend, no `stream_version`) | Documented defects only | 426 zero-dispatch |
| **C1** (new frontend, `stream_version=2`) | Legacy adapter: keeps content, 原題序未知, 請求總數, no placeholders | Full v2 contract |

### C0 × S0 — documented defects

Source: `math_single_legacy.jsonl`. Verified by `test_c0_s0_defects_documented`.

- No `context` key at top level
- No `protocol_version` field in started payload
- No `questions` manifest list in started payload
- No `question_terminal` events
- `started.data` = JSON string `{"generation_log_id": null}` (not empty)
- `result.data` = direct question JSON (no wrapper)

### C0 × S1 — 426 zero-dispatch

Verified by `test_c0_s1_get_returns_426_zero_dispatch`,
`test_c0_s1_post_returns_426_zero_dispatch`,
`test_c0_s1_wrong_version_returns_426`, and
`test_c0_s1_no_started_in_426_response`.

Key invariants:
- HTTP 426 returned before any generation starts (`generate_was_called == []`)
- Response body is `application/json`, not `text/event-stream`
- Body contains `code: "CLIENT_UPDATE_REQUIRED"` and `detail` string
- No `started` SSE event in the 426 body
- `stream_version=1` (wrong version) also returns 426

### C1 × S0 — legacy adapter

Frontend tests in `legacyAdapter.test.ts` (18 tests, existing) and
`GeneratePage.legacy-no-placeholders.test.tsx` (4 new tests). Key invariants:

- Items keyed by opaque id (not arrival order)
- `resolvedIndex` set only when explicit index↔id evidence arrives consistently
- No placeholder cards render without a manifest (`runEvidence === null`)
- `requestTotal` comes from params, not a manifest
- No per-question terminal evidence (only `done: true`)
- No auto-resubmit

### C1 × S1 — v2 contract

Verified by `test_c1_s1_ab_interleaved_v2_contract` (using `_run_ab_stream`
shared fixture, B finishes before A). Key invariants:

- `started` has `protocol_version=2`, `questions` manifest, contiguous seqs from 1
- B's result/terminal arrive before A's (interleaved confirmed)
- Each `question_update`/`result` has `content_revision >= 1`
- Each `question_terminal` has required fields
- `question_terminal` arrives after its question's `result`
- `done` is last event
- All per-question events use the manifest question ids

---

## Test Run Results

### Backend pytest

Commands run:

```bash
choom -n 500 -- uv run pytest \
  tests/server/test_754_fixture_drift.py \
  tests/server/test_754_compat_matrix.py \
  -v --tb=short
```

Result summary (2026-09-27):

```
18 passed, 3 warnings in 2.48s
```

Warnings are `PytestUnknownMarkWarning` for `@pytest.mark.timeout` (unflagged
custom mark, not a test failure).

### Backend pytest — full suite (2026-09-27)

```bash
choom -n 500 -- uv run pytest -q --ignore=tests/test_753_odt_browser.py
```

Result:

```
2997 passed, 1 skipped, 47 warnings in 569.64s (0:09:29)
```

### Ruff lint

```bash
uv run ruff check src/ server/ tests/
```

Result: **All checks passed** (zero violations in new files).

### Frontend TypeScript + ESLint

```bash
cd web && npx tsc -b --noEmit && npm run lint
```

Result: **clean** (no errors or warnings).

### Frontend vitest — full suite (2026-09-27, second run)

```bash
cd web && choom -n 500 -- npm test -- --reporter=verbose
```

Result:

```
Test Files  185 passed (185)
Tests  2013 passed (2013)
Duration  66.85s
```

### Frontend vitest (new tests only, first run)

```bash
cd web && choom -n 500 -- npx vitest run \
  src/lib/generationStream.fixtureTransport.test.ts \
  src/pages/GeneratePage.legacy-no-placeholders.test.tsx
```

Result:

```
Test Files  2 passed (2)
Tests  14 passed (14)
```

---

## Fixture Transport Tests

New tests in `web/src/lib/generationStream.fixtureTransport.test.ts`
(added to existing 5 tests, now 14 total):

- **Terminal arrives before result (reversed wire order)** — swaps wire bytes of
  seq 22 (q_RUN_001 terminal) and seq 21 (q_RUN_001 result); decoder buffers the
  terminal until result fills seq 21; final state still has 2 finals, 2 terminals,
  no degradation.

- **Legacy fixture replay through adapter** — loads `math_single_legacy.jsonl`,
  replays all events through `applyLegacyEvent`; verifies 2 finals, `done: true`,
  stable unique ids (`legacy_001`, `legacy_002`), `resolvedIndex` set from
  explicit index evidence.

- **Conflict: duplicate seq with different data** — injects a duplicate of
  the result event at seq 18 (q_RUN_002) with a mutated payload; verifies
  `selectConflictCount(state) > 0` and `degraded === false` (conflict does not
  degrade the stream).

---

## UI / No-Placeholder Evidence

New tests in `web/src/pages/GeneratePage.legacy-no-placeholders.test.tsx`:

- Zero placeholder cards render when `runEvidence === null` and `displayResults`
  is empty.
- Zero placeholder cards render when `runEvidence === null` and 2 legacy
  `GeneratedQuestion` items are in `displayResults`.
- Placeholder cards DO appear when `runEvidence` provides a manifest (v2 mode),
  confirming the conditional is correctly wired.

---

## ODT Browser Test Extensions

New tests in `tests/test_753_odt_browser.py` (t7–t9):

- **t7 (image-swap race)** — verifies that `buildOdtFromSnapshots` captures
  `imageSources` before its first async yield. A post-yield mutation of
  `snap.imageSources` must not corrupt the ODT.

- **t8 (whole-ZIP failure)** — a rasterizer that throws (not just returns
  `{ok:false}`) causes `buildOdtFromSnapshots` to propagate the error; no Blob
  is resolved (test passes when an error is thrown).

- **t9 (batch + legacy/history exports)** — builds a 3-snapshot batch ODT
  (flat legacy, 題組, history-shaped with png_base64); verifies `content.xml`
  contains text from all three questions.

Vite fixture updated to pick a free port (`_find_free_port()`) instead of the
hardcoded 5173, avoiding conflicts with running dev servers.

---

## Part A — 6.3 / 6.4 / 10.1 / 10.2 Tests (second commit)

Added on 2026-09-27 to complete the remaining Part A deliverables.

### (b) i18n parity: `web/src/i18n/messages.754-branch-keys.test.ts`

19 tests (one per key + count check). All 18 branch keys verified present and
non-empty in both `en-US` and `zh-TW`. Result: **19 passed**.

Keys covered: `odt.preview_conversion_failed`, `history.download_odt_error`,
`history.btn_download_odt`, `stream.information_incomplete`,
`stream.batch_conflict`, `stream.legacy_mixed`, `card.content_conflict`,
`card.conflict_reason_seq_data`,
`card.conflict_reason_same_revision_different_content`,
`card.conflict_reason_identity_mismatch`,
`card.conflict_reason_terminal_contradiction`,
`card.conflict_reason_terminal_invalid`,
`card.conflict_reason_review_contradiction`, `card.position_unknown`,
`stream.legacy_no_per_question_progress`, `statusbar.legacy_request_total`,
`card.download_json_draft`, `card.download_odt_draft`.

### (g) Status bar counts: `web/src/lib/generationEvidence.transport-statusbar.test.ts`

9 tests replaying `math_abcd_transport.jsonl`. Verified:
- manifest total = 4
- `selectEndedCount` = 3 (A complete, B partial, C failed draft)
- `selectFinalReceivedCount` = 3 (A, B, D)
- Resend of D's result (dup seq 18) does not inflate count to 4
- No batch conflict in clean replay
- D (q_RUN_004): `receipt="final"`, `terminal=null`
- C (q_RUN_003): `terminal.has_final=false`, `receipt≠"final"`

Result: **9 passed**.

### (c)/(d) Keyboard + reduced-motion: `web/src/motion/actionFeedback.754-a11y.test.tsx`

12 tests:
- `ActionButton` renders as native `<button>` (keyboard-operable by default)
- `InlineFailureNotice` retry/dismiss render as native `<button>` elements
- `InlineFailureNotice` uses `role=alert`, no `autofocus`/`tabindex`
- `role=status` notices have no `autofocus`/`tabindex` (no focus steal)
- `@media (prefers-reduced-motion: reduce)` block present in `index.css`
- Block suppresses `transition-duration: 1ms !important` and `transform: none !important`
- `.streaming-caret` override (`animation: none !important`) inside block
- `motion-opacity-pulse` shimmer covered

Result: **12 passed**.

### (e) Masking: `web/src/sentry.754-masking.test.ts`

9 tests extending existing sentry coverage:
- `genAI: { inputs: false, outputs: false }` — question content not captured
- HTTP bodies empty — no request/response capture
- Query params empty — no URL-embedded content
- `maskAllText: true, blockAllMedia: true` — replay masks all content
- `unmask: [".sentry-unmask"]` only — conflict reason codes not in unmask list
- Console limited to `["warn", "error"]` — no info/debug leakage
- HTTP headers empty; userInfo disabled
- Breadcrumb hook passes ordinary navigation breadcrumbs unchanged

Result: **9 passed**.

### (a) Modification eligibility: `web/src/components/QuestionCard.754-modification-eligibility.test.tsx`

6 tests:
- Legacy (C1/S0) final card: annotation section appears (`isFinal=true`, `passed=true`, `recordId` set)
- Legacy card: `[data-selection-field]` elements present (no generation manifest required)
- Independent error attribution: failed ODT export in one card does not affect another
- v2-origin card saved to history: annotation section appears (same gate: `isFinal && passed`)
- Legacy adapter item (`positionUnknown=true`): selection fields still present
- `passed=false` card: annotation section absent (eligibility correctly gated)

Result: **6 passed**.

### (f) Navigation/clear/resubmit guards: `web/src/pages/GeneratePage.754-guards.test.tsx`

6 tests:
- Page renders without crash during v2 stream (`status="generating"`, evidence active)
- `generate()` NOT called automatically when evidence degrades (no auto-resubmit)
- Page renders without crash during legacy stream (legacyAdapter active)
- `generate()` NOT called automatically during legacy stream
- `generate()` not auto-called at idle (guard released)
- Switching from non-degraded→degraded does NOT trigger `generate()`

Result: **6 passed**.

---

## Notes for Part B Agent

Evidence gathered for ADR, protocol docs, CONTEXT.md glossary:

1. **426 gate behavior**: `server/generate/routes.py` lines 403-404 (GET) and
   436-437 (POST). Response body is `{"detail": "<string>", "code": "CLIENT_UPDATE_REQUIRED", "supported_stream_versions": [2]}`. `detail` must be a string (not object) because C0 can display strings.

2. **v2 protocol invariants** (verified by fixture tests):
   - `started` is always seq=1; `done` is always last.
   - All events carry `context.event_seq`; contiguous 1..N except transport fixtures.
   - `question_update`/`result` carry `content_revision >= 1`.
   - `question_terminal` follows its question's `result` (not before).

3. **Transport fixture gap**: `math_abcd_transport.jsonl` has seq 18 → seq 20 (seq 19 absent). The omitted seq 19 would have been `question_terminal` for q_RUN_004. The fixture demonstrates the decoder's bounded-buffer + eof_gap degradation path.

4. **Legacy format**: `math_single_legacy.jsonl` — `{event, data}` wire format. `started.data = '{"generation_log_id": null}'`. `result.data` = direct question JSON string.

5. **C1×S0 adapter architecture**: `web/src/lib/legacyAdapter.ts`. Items keyed by opaque id. `resolvedIndex = null` → 原題序未知. `requestTotal` from params. No placeholder cards. `done` sets `done: true` only.

---

## Task 5.1 Evidence Map (Issue #895)

Branch: `wt/895`  
Date: 2026-09-27

### Scope

Issue #895 requires every sub-item of task 5.1 to have a named test before the
checkbox can be ticked.  Sub-items 1–3 and 7 were already covered by existing
tests; sub-items 4, 5, 6, 8, and 9 needed new tests or extensions.

### Finding: leftover mutation in generationStream.ts

During the audit, `git diff` revealed that `web/src/lib/generationStream.ts`
had an uncommitted mutation (`if (false && seqSeen.has(eventSeq))`) left over
from a prior mutation-check experiment.  This disabled the duplicate-seq guard
and was the root cause of the apparent sub-item 5 integration-test failure
observed before the revert.  After reverting to HEAD all 91 useGenerate tests
and all 21 generationStream tests pass.

### Sub-item → test mapping

| # | Sub-item | File | Test name | Status |
|---|---|---|---|---|
| 1a | Decoder starts in `awaiting-start` | `web/src/lib/generationStream.test.ts` | `starts in awaiting-start mode with null run` | existing |
| 1b | Decoder transitions to `v2` | `web/src/lib/generationStream.test.ts` | `transitions to v2 on a valid manifest and sets run` | existing |
| 1c | Decoder transitions to `legacy` | `web/src/lib/generationStream.test.ts` | `transitions to legacy on a started event with generation_log_id (no context)` | existing |
| 1d | Decoder reaches `unsupported` state | `web/src/lib/generationStream.test.ts` | `is unsupported with unknown_protocol when protocol_version is not 2` | existing |
| 2a | useGenerate POST body carries `stream_version: 2` | `web/src/hooks/useGenerate.test.ts` | `F3: stream_version 2 in POST body > sends stream_version 2 in the POST body` | existing |
| 3 | Complete manifest → creates N waiting slots | `web/src/lib/generationEvidence.test.ts` | `createRunEvidence > creates N waiting placeholders in manifest order` | existing |
| 4a | Invalid manifest (total mismatch) → no slots, status error | `web/src/hooks/useGenerate.test.ts` | `F3: invalid manifest in started → no v2 slots, status error > sets status error and no evidence when started carries an invalid manifest (total mismatch)` | NEW (hook) |
| 4b | Invalid manifest (missing `questions`) → decoder `unsupported` | `web/src/lib/generationStream.test.ts` | `is unsupported with invalid_manifest when questions array is absent from payload` | NEW (decoder) |
| 4c | Missing started then done → no placeholders, error | `web/src/hooks/useGenerate.test.ts` | `F3: missing started then done → no placeholders, error > ...` | existing |
| 5a | Duplicate `question_id` in manifest → decoder `unsupported` | `web/src/lib/generationStream.test.ts` | `is unsupported with invalid_manifest on duplicate question_id` | existing |
| 5b | Duplicate `index` in manifest → decoder `unsupported` | `web/src/lib/generationStream.test.ts` | `is unsupported with invalid_manifest on duplicate question index` | NEW (decoder) |
| 5c | Duplicate seq at decoder level → `duplicate_seq` ignore | `web/src/lib/generationStream.test.ts` | `ignores a second started with same seq in v2 mode (duplicate_seq) and stays in v2` | NEW |
| 5d | Second identical `started` in hook integration → evidence not reset | `web/src/hooks/useGenerate.test.ts` | `F3: second started in active v2 run does not overwrite slots > ignores a second identical started (same payload, same seq 1) and preserves accumulated evidence content` | NEW |
| 6 | HTTP 426 → stops, no resubmit | `web/src/hooks/useGenerate.test.ts` | `F3: HTTP 426 → stops, no resubmit > sets status error on HTTP 426 and does not issue a second generate call` | NEW |
| 7a | Unknown protocol version → decoder `unsupported` | `web/src/lib/generationStream.test.ts` | `is unsupported with unknown_protocol when protocol_version is not 2` | existing |
| 7b | Unknown protocol → hook sets error, no resubmit | `web/src/hooks/useGenerate.test.ts` | `F3: unknown protocol → abort and error > sets status error on unknown_protocol and does not call generate a second time` | existing; explicitly asserts `fetchEventSourceMock.toHaveBeenCalledTimes(1)` (no resubmit) |
| 8 | Stale events from old connection do not affect new connection | `web/src/hooks/useGenerate.test.ts` | `F3: stale events from previous connection do not affect new connection > stale done from old connection does not corrupt the new connection's evidence or status` | NEW (rewritten — see note) |
| 9 | Pre-started events do not create v2 slots; only valid `started` creates them | `web/src/hooks/useGenerate.test.ts` | `F3: only valid started creates v2 evidence slots > pre-started question_update does not create v2 evidence; valid started creates the manifest slots` | NEW |

**Sub-item 8 note (non-vacuous design):** The test establishes run "RUN" (old
connection) with a draft for `q_RUN_001`, calls `reset()`, starts a new
connection for run "RUN2" with its own `started` and a draft for `q_RUN2_001`,
then fires a stale `done` (seq 3) on the old stream.  Without the
`controllerRef.current !== controller` guard, `handleV2Event("done")` would
call `setStatus("idle")` on the new connection — corrupting its status.  The
test asserts `status === "generating"` and `evidence.runId === "RUN2"` after
the stale event, which fails when the guard is removed, making the test
genuinely mutation-sensitive.

### Mutation checks

Each new test was verified by a targeted mutation that disables the production
guard, confirming the test goes red, then restored.  All production files were
confirmed clean (`git diff HEAD -- <file>` showed zero diff) after each revert.

| Test | Production file | Line | Mutation applied | RED observed |
|---|---|---|---|---|
| 4b (missing questions — decoder) | `web/src/lib/generationStream.ts` | 137 | `if (false && (!Array.isArray(questions) \|\| questions.length !== total))` | yes — decoder stayed in v2 instead of unsupported |
| 5b (duplicate index — decoder) | `web/src/lib/generationStream.ts` | 143 | `if (false && q.index !== i)` | yes — decoder accepted the non-contiguous manifest |
| 5c (decoder duplicate_seq) | `web/src/lib/generationStream.ts` | 260 | `if (false && seqSeen.has(eventSeq))` | yes — returned `{kind:"v2",...}` instead of `{kind:"ignore",reason:"duplicate_seq"}` |
| 5d (hook duplicate_seq) | `web/src/lib/generationStream.ts` | 260 | same as 5c | yes — evidence reset after second `started` |
| 4a / 6 (invalid manifest / HTTP 426 hook) | `web/src/hooks/useGenerate.ts` | unsupported handler | `if (false && d.kind === "mode" && d.mode === "unsupported")` | yes — error not set |
| 8 (stale guard) | `web/src/hooks/useGenerate.ts` | 1411 | `if (false && controllerRef.current !== controller)` in `onmessage` | yes — stale `done` set status to "idle" on the new connection |
| 9 (pre-started slots) | `web/src/hooks/useGenerate.ts` | unsupported handler | same as 4a/6 | yes — evidence appeared before `started` |

### Test run results (2026-09-27)

```
web/src/lib/generationStream.test.ts   23 passed (23)  [+2 new: 4b, 5b]
web/src/hooks/useGenerate.test.ts      91 passed (91)  [+5 new describe blocks]
```

TypeScript (`npx tsc -b --noEmit`): clean  
ESLint (`npm run lint`): clean

---

## Task 10.3 Verification Record (Issue #895)

Date: 2026-09-27  
Branch: `feat/895-897-evidence-terminal-order`  
Commit: `9fed1b82a62b3e53b258f0176295028bf7e72bb6`

### Environment note

All commands run on the integrated branch (`feat/895-897-evidence-terminal-order`)
which incorporates PR #894 plus fixes for #897 and the #895 task-5.1 tests.
Memory discipline: at most one heavy lane at a time; every heavy command
prefixed with `choom -n 500 --`.

### Command and result table

| Step | Command | Result | Duration |
|---|---|---|---|
| 1 Ruff | `uv run ruff check src/ server/ tests/` | **All checks passed** (0 violations) | < 5 s |
| 2 Backend full suite | `choom -n 500 -- uv run pytest -q -rs` | **3017 passed, 1 skipped, 44 warnings** | 596 s |
| 3a Guard — RNG allowlist | `choom -n 500 -- uv run pytest -v tests/test_generation_sampler_allowlist.py` | **6 passed** | 2 s |
| 3b Guard — forwarding/PIN-ONLY | `choom -n 500 -- uv run pytest -v tests/test_contract_forwarding_guard.py` | **151 passed** | 2 s |
| 3c Guard — runtime completeness gate | `choom -n 500 -- uv run pytest -v tests/server/test_generate_routes.py::test_generate_route_rejects_unresolved_top_level_field tests/server/test_generate_routes.py::test_generate_route_rejects_unresolved_per_question_field tests/server/test_generate_routes.py::test_generate_route_rejects_unresolved_subquestion_field tests/server/test_generate_routes.py::test_preview_route_rejects_unresolved_top_level_field tests/server/test_generate_routes.py::test_generate_route_reports_incompatible_parent_with_resolver_shape` | **5 passed** | 8 s |
| 4a Web vitest | `cd web && choom -n 500 -- npm test -- --reporter=verbose` | **187 files, 2049 tests passed** | 69 s |
| 4b Web ESLint | `cd web && npm run lint` | **clean** (exit 0) | < 5 s |
| 4c Web tsc | `cd web && npx tsc -b` | **clean** (exit 0) | < 5 s |
| 4d Web build | `cd web && choom -n 500 -- npm run build` | **904 modules, built in 668 ms** | 7 s |
| 5 ODT browser harness | `choom -n 500 -- uv run pytest tests/test_753_odt_browser.py -q -rs` | **12 passed** | 13.73 s |

### Skipped test identification

**Node ID:** `tests/test_social_studies_creative_planning_smoke.py::test_five_briefs_have_at_least_three_distinct_題材_keywords`

**Skip reason:** `Set RUN_CREATIVE_PLANNING_SMOKE=1 to run this smoke test.`
(Guarded by `pytest.mark.skipif(os.environ.get("RUN_CREATIVE_PLANNING_SMOKE") != "1", ...)`)

**Disposition — NOT a required acceptance item.** The file's module docstring
says explicitly "Not run in CI." The test issues one live Opus planning call to
check diversity across 5 briefs — it requires `LLM_API_KEY` and real model
access. It exercises issue #114 (batch-level prompt dedup), not any code changed
on this branch. No production guard relies on it, and it is not listed in any
ADR 0022 guard suite. Correctly skipped.

### Full-預抽 guard suites

| Suite | Test file | Scope | Result |
|---|---|---|---|
| Runtime completeness gate (ADR 0022 §1) | `tests/server/test_generate_routes.py` (5 targeted tests) | `/generate` returns HTTP 422 for non-empty `drawn` set; incompatible pinned 從屬參數 returns 422 | **5 passed** |
| Static RNG/`sample_params` allowlist (ADR 0022 §2) | `tests/test_generation_sampler_allowlist.py` | Every `random.`/`rng.` use under `src/` and `server/` outside resolver modules matches allowlist; `sample_params` only called from resolver | **6 passed** |
| Forwarding RESOLVED/PIN-ONLY classification guard (ADR 0022 §3) | `tests/test_contract_forwarding_guard.py` | Every `GenerateParams` field × subject classified FORWARDED/REJECTED/INAPPLICABLE; FORWARDED fields are RESOLVED or PIN-ONLY | **151 passed** |

### Memory discipline

- Lane cap: 1 heavy lane at a time throughout (backend suite → guard suites →
  web suite → web build; no overlap).
- `choom -n 500 --` applied to: backend pytest, web vitest, web build.
- Ruff, ESLint, tsc are lightweight and run without `choom`.

### ODT browser harness record

Command run on branch `feat/895-897-evidence-terminal-order` (2026-09-27):

```bash
choom -n 500 -- uv run pytest tests/test_753_odt_browser.py -q -rs
```

Result: **12 passed in 13.73 s**

Playwright Chromium is installed (`~/.cache/ms-playwright/chromium-1208`). The
harness ran in full on this branch with 12 tests passing. The 12 tests include
the 3 raw SVG foreignObject tests and 9 harness tests (t1–t9, driven by a live
`npx vite` dev server via Playwright).

### Historical record note

**Full-suite test_753 inclusion:** The 10.3 full-suite command
(`choom -n 500 -- uv run pytest -q -rs`, row 2 above) carried no `--ignore`
flag. `tests/test_753_odt_browser.py` collects 12 tests (verified with
`uv run pytest --collect-only -q tests/test_753_odt_browser.py`) and was
therefore included in the 3017-test total.

**Baseline reconciliation (resolved):** The 2997 figure in "Test Run Results"
was an intermediate run on `feat/748-754-live-progress-export` with
`--ignore=tests/test_753_odt_browser.py` (12 tests excluded) and recorded
before commit 76f64e8 added `tests/server/test_754_doc_examples.py` to that
branch. Commit 76f64e8 contributed 7 collected tests on staging (confirmed:
8 collected on this branch minus the 1 new test from #897). Adding both
back: 2997 + 12 + 7 = 3016, which matches #894's reported "3016 passed,
1 skipped" exactly. There is no discrepancy.

**Backend test delta (#895 / #897):** #895 added no backend tests.
`git diff staging --stat -- tests/ server/ src/` shows this branch touches
only `tests/server/test_754_doc_examples.py` (+13 lines), adding exactly
1 collected test (`test_doc_states_slot_array_order_non_normative`, #897).
Staging (post-#894) therefore collects 3017 = 3016 passed + 1 skipped (the
`RUN_CREATIVE_PLANNING_SMOKE` test). This branch collects 3018: 3017 passed
(3016 from staging + 1 from #897) and 1 skipped.

Web tests grew from 2037 to 2049 (+12 new tests on this branch). Both backend
and frontend numbers are preserved in their respective sections above.
