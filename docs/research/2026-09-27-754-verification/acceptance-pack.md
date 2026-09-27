# Issue #754 — Acceptance Pack

Date: 2026-09-27  
Branch: `feat/748-754-live-progress-export`

This pack is organised for three audiences.  Gates marked **NOT YET PERFORMED**
require browser or environment access beyond what is available in this session.

---

## Part 1 — Teacher audience

### 1.1 What each status label means

| Label (zh-TW) | Meaning |
|---|---|
| 等待生成 | Placeholder card — question is in the manifest but generation has not started yet |
| 生成中 | Generation work is active for this question |
| 已結束 | Generation work has definitively ended (a `question_terminal` was received) |
| 草稿 | A provisional version is available; final result not yet received |
| 最終結果 | The server-confirmed final version has been received |
| 結果待接收 | Terminal evidence indicates a final exists but the content has not arrived yet |
| 結果未收到 | No content has been received for this question |
| 資訊不完整 | Some stream events were not received; content already received remains available |
| 原題序未知 | Legacy connection — original position in the batch cannot be determined |

### 1.2 Termination reason labels

| Label | Meaning |
|---|---|
| 正常結束 | Generation ended normally |
| 生成失敗 | Generation failed before producing a final result |
| 已取消 | Generation was explicitly cancelled |

### 1.3 Delivery status labels

| Label | Meaning |
|---|---|
| 完整 | All expected subquestions and required images were delivered |
| 部分 | Some expected parts are missing |
| 無結果 | No final content was produced |
| 未知 | Delivery outcome could not be determined |

### 1.4 Review (審題) result labels

| Label | Meaning |
|---|---|
| 審題通過 | The verification loop passed at the delivered content version |
| 審題未通過 | Verification failed (content delivered despite this) |
| 審題略過 | Verification was skipped (e.g. `skip_verify=true`) |
| 審題未知 | No verification evidence matching the delivered version |

### 1.5 Download behaviour for drafts

When a question card shows a 草稿 (draft) state:

- **JSON download**: available, file named `草稿_{questionId}.json`.  The `_export.is_draft` field is `true`.  The live question object is not modified.
- **ODT download**: available, file named `草稿_{questionId}.odt`.  Each draft is prefixed with `【草稿】` in the document.
- **Batch with any draft**: batch files named `含草稿_batch_{timestamp}.json/.odt`.

The downloaded copy contains an `_export` object with generation metadata.
Removing `_export` from the downloaded JSON restores the original question
structure.  External tools that do not expect unknown fields should strip
`_export` before processing.

Drafts are available for download from the browser tab that received them.
They are **not** saved to generation history — the download is the only copy.

### 1.6 ODT preview images

For questions that show a chart or diagram preview in the browser:

- If the preview was produced from a `chart_spec` (no backend PNG yet), the
  ODT export captures the live preview and converts it.
- If conversion fails for one image, a `【匯出缺圖／預覽轉換失敗】` marker
  appears at that position; all other content is preserved.
- If the entire ODT package cannot be assembled, an error notice appears and
  no broken file is produced.  JSON download remains available.

### 1.7 Pointers to UI and ODT evidence

The following test files cover teacher-visible behaviour:

| Evidence | File |
|---|---|
| Status bar counts (已結束, 收到最終結果) | `web/src/lib/generationEvidence.transport-statusbar.test.ts` |
| i18n parity (zh-TW / en-US) | `web/src/i18n/messages.754-branch-keys.test.ts` |
| Keyboard + reduced-motion accessibility | `web/src/motion/actionFeedback.754-a11y.test.tsx` |
| Sentry masking (question content not captured) | `web/src/sentry.754-masking.test.ts` |
| Modification eligibility preserved | `web/src/components/QuestionCard.754-modification-eligibility.test.tsx` |
| ODT draft labels, group structure, image sources | `web/src/utils/odt.snapshot.test.ts` |
| ODT browser rasterization (real browser) | `tests/test_753_odt_browser.py` |

Browser acceptance (real-page download of draft ODT/JSON): **NOT YET PERFORMED**
(see Part 3).

---

## Part 2 — Technical reviewer audience

### 2.1 Release gates

The v2 per-question live progress exception (ADR 0032) is conditional.  It
takes effect only when **all** of the following are satisfied:

| Gate | Status |
|---|---|
| Cross-layer fixture tests pass | PASSED (see §2.2) |
| Frontend vitest suite passes | PASSED (see §2.3) |
| Ruff lint passes | PASSED (see §2.4) |
| TypeScript + ESLint passes | PASSED (see §2.5) |
| Admission gateway open with quiescent drain evidence | NOT YET PERFORMED |
| Teacher browser acceptance | NOT YET PERFORMED |

### 2.2 Backend test commands and results

```bash
choom -n 500 -- uv run pytest \
  tests/server/test_754_fixture_drift.py \
  tests/server/test_754_compat_matrix.py \
  -v --tb=short
```

Result (2026-09-27): **18 passed, 3 warnings in 2.48s**  
Warnings: `PytestUnknownMarkWarning` for `@pytest.mark.timeout` (unflagged custom mark, not a failure).

```bash
choom -n 500 -- uv run pytest -q --ignore=tests/test_753_odt_browser.py
```

Result (2026-09-27): **2997 passed, 1 skipped, 47 warnings in 569.64s**

Doc-example validation:

```bash
choom -n 500 -- uv run pytest tests/server/test_754_doc_examples.py -q
```

(Run this after writing the protocol document.)

### 2.3 Frontend vitest commands and results

```bash
cd web && choom -n 500 -- npm test -- --reporter=verbose
```

Result (2026-09-27): **185 test files, 2013 tests passed in 66.85s**

New vitest for doc examples:

```bash
cd web && choom -n 500 -- npx vitest run \
  src/utils/exportSnapshot.docExamples.test.ts
```

### 2.4 Ruff lint

```bash
uv run ruff check src/ server/ tests/
```

Result (2026-09-27): **All checks passed** (zero violations).

### 2.5 TypeScript + ESLint

```bash
cd web && npx tsc -b --noEmit && npm run lint
```

Result (2026-09-27): **clean** (no errors or warnings).

### 2.6 Fixture regeneration command

```bash
bash scripts/generate_v2_fixtures.sh
```

Verify drift with:

```bash
choom -n 500 -- uv run pytest tests/server/test_754_fixture_drift.py -q
```

No paid models required — all fixtures use `_FakeClient` stubs.

### 2.7 Compatibility matrix

See `docs/generation-event-protocol.md` §10 for the full matrix and invariants.
Summary:

| | S0 (old backend) | S1 (new backend) |
|---|---|---|
| C0 (old frontend) | Documented defects (arrival-order indexing, no dedup) | HTTP 426, zero dispatch |
| C1 (new frontend) | Legacy adapter: content preserved, 原題序未知, 請求總數 | Full v2 contract |

**C0/S0 documented defects** (not fixed; old clients remain C0):
- Index by arrival order of `result` events
- No duplicate result deduplication
- No consistent index↔id tracking
- Later result may overwrite earlier draft at same position

Source: `tests/fixtures/generation_legacy/math_single_legacy.jsonl`, verified
by `test_c0_s0_defects_documented` in `tests/server/test_754_compat_matrix.py`.

### 2.8 Known limitations

1. `done` event arrival after buffer degradation: client enters degraded mode
   immediately (eof_gap) and does not wait for the 2-second timer.
2. `math_abcd_transport.jsonl` fixture has seq 18 → seq 20 (seq 19 absent
   intentionally) to exercise the eof_gap degradation path; q_RUN_004 therefore
   has `terminal=null` in the evidence after replay.
3. History detail view does not expose v2 evidence (processing/delivery/review)
   for stored records — it uses the legacy/history adapter with `processing:
   "ended"`, `termination_reason: "normal"`, `delivery_status: "complete"`.
4. The modification stream (`人工審題修正`) is unaffected by the v2 protocol;
   it retains its own admission and format.
5. Drain control scripts (`scripts/release_control.py`) have been unit-tested
   but not exercised against a live two-instance deployment in this session.

---

## Part 3 — Release operator audience

### 3.1 Entry inventory

All generation traffic passes through the **admission gateway** (DEPLOYMENT.md
§"Generation admission gateway").  Backend instances are reachable only via the
gateway's internal network after the gateway service is added.

The full entry inventory is configured in `inventory.json` (see DEPLOYMENT.md
for format).  Before any v2 release, run:

```bash
python scripts/release_control.py preflight --inventory inventory.json
```

This confirms every instance is reachable and drain endpoints respond.

### 3.2 Version/drain evidence requirements

Before opening the gate after deploying the v2 backend:

1. Every backend instance must report `supported_stream_versions: [2]` in its
   drain response.
2. All six drain gauges must be zero simultaneously on every instance
   (`quiescent: true`).

```bash
python scripts/release_control.py compat-check \
  --inventory inventory.json --require-version 2

python scripts/release_control.py drain-check \
  --inventory inventory.json --timeout 120
```

### 3.3 pause → drain → switch → verify → reopen runbook

Reference: DEPLOYMENT.md §"Drain telemetry and release control" (full
recommended release runbook, steps 1–8).

Summary of the switch procedure:

1. **pause**: `python scripts/release_control.py pause-and-drain --inventory inventory.json --timeout 120 --reason "v2 rollout"`
2. **verify drain**: all instances must report `quiescent: true`.  Do not proceed if any instance shows non-zero gauges or is unreachable.
3. **deploy new backend**: replace backend instances without exposing a public backend domain.
4. **compat-check**: `python scripts/release_control.py compat-check --inventory inventory.json --require-version 2`
5. **verify (readiness)**: `python scripts/release_control.py readiness --inventory inventory.json --require-version 2`
6. **reopen**: `python scripts/release_control.py reopen --inventory inventory.json`

**NOT YET PERFORMED** in this session — requires a real deployment environment.

### 3.4 Two rollback drills

**Drill A — frontend-only (C1 → C0) rollback:**
1. Pause the gateway.
2. Drain (all instances `quiescent: true`).
3. Roll back the frontend to the old build.
4. Verify: old frontend sends no `stream_version` → receives HTTP 426 from S1 backend.
5. Gate stays paused until a compatible combination (C1+S1) is restored.

**NOT YET PERFORMED.**

**Drill B — backend-only (S1 → S0) rollback:**
1. Pause the gateway.
2. Drain (all instances `quiescent: true`).
3. Roll back the backend to the old build (S0).
4. Verify: new frontend (C1) against old backend (S0) → legacy adapter active;
   status bar shows "請求總數 N" and "原題序未知" labels; no placeholders.
5. Gate stays paused until a compatible combination (C1+S1) is restored or
   C1+S0 legacy mode is acceptable.

**NOT YET PERFORMED.**

### 3.5 What is not covered here

The following acceptance items are handed to the next ticket / assistant:

- **Final ego-browser real-page acceptance**: a teacher confirming that draft
  download, ODT content, status labels, and the statusbar counts are correct
  in the real deployed UI.
- **Real-environment drain drills**: executing the pause→drain→switch→verify→reopen
  procedure against a live deployment with two backend instances.
- **Release drill evidence collection**: operator logging entry inventory,
  version responses, and drain evidence before and after the switch.

These items must be completed and their evidence collected before the v2
exception (ADR 0032) is considered in effect.

---

## Appendix — Document and test file index

| Document | Purpose |
|---|---|
| `docs/generation-event-protocol.md` | Full v2 protocol reference |
| `docs/adr/0032-per-question-live-progress-is-a-conditional-exception-to-unattributability.md` | Conditional ADR |
| `docs/adr/0009-concurrent-batches-are-unattributable.md` | Updated with link to ADR 0032 |
| `CONTEXT.md` | Teacher-facing glossary (已結束, 收到最終結果, 資訊不完整, 原題序未知, 請求總數, 匯出缺圖 added) |
| `FLOW.md` | Updated with v2 protocol additions section |
| `DEPLOYMENT.md` | Pre-existing drain/gateway runbook (referenced, not modified) |

| Test file | Audience | Gate |
|---|---|---|
| `tests/server/test_754_doc_examples.py` | Technical | Protocol doc examples validated |
| `web/src/utils/exportSnapshot.docExamples.test.ts` | Technical | _export TS schema validated |
| `tests/server/test_754_compat_matrix.py` | Technical | Compat matrix (all 4 cells) |
| `tests/server/test_754_fixture_drift.py` | Technical | Fixture drift guard |
| `web/src/lib/generationEvidence.transport-statusbar.test.ts` | Technical/Teacher | Status bar counts |
| `web/src/i18n/messages.754-branch-keys.test.ts` | Technical/Teacher | i18n parity |
| `web/src/motion/actionFeedback.754-a11y.test.tsx` | Teacher (a11y) | Keyboard + reduced-motion |
| `web/src/sentry.754-masking.test.ts` | Technical | Masking |
| `web/src/components/QuestionCard.754-modification-eligibility.test.tsx` | Technical/Teacher | Modification eligibility |
| `web/src/pages/GeneratePage.754-guards.test.tsx` | Technical | Navigation guards |
