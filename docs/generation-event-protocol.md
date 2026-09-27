# Generation Event Protocol v2

Reference for the SSE event stream produced by `GET /api/generate` and
`POST /api/generate` when `stream_version=2`.

See also:
- `server/generate/event_protocol.py` — Pydantic contract types
- `src/common/generation_events.py` — immutable identity types
- `web/src/lib/generationStream.ts` — client decoder
- `web/src/lib/generationEvidence.ts` — evidence reducer
- `web/src/utils/exportSnapshot.ts` — snapshot export contract
- ADR 0032 — conditions under which per-question progress is authoritative
- DEPLOYMENT.md §"Generation admission gateway" and §"Drain telemetry and release control"

---

## 1. Transport admission

### 1.1 stream_version parameter

Every `GET /api/generate` and `POST /api/generate` request **must** include
`stream_version=2` (query-string or POST body).  The parameter is transport-only
and is excluded from `params_json` and from TypeScript generation types
(`SERVER_ONLY_GENERATE_FIELDS`).

When `stream_version` is absent or does not equal `2`, the server returns
**HTTP 426** before dispatching any work, calling any model, or emitting any
SSE event:

```json
{
  "detail": "介面版本已更新，請重新整理頁面後再生成。",
  "code": "CLIENT_UPDATE_REQUIRED",
  "supported_stream_versions": [2]
}
```

The `detail` field is always a plain string so that a C0 client that displays
raw `detail` values shows a human-readable message.  No `started` event or
worker activity precedes or follows the 426 response.

The independent 人工審題修正 stream retains its own admission rules and is
unaffected by this parameter.

### 1.2 Build admission (issue #771)

After the `stream_version` check, `X-Frontend-Build-ID` is checked against the
authority fixture at `RELEASE_AUTHORITY_URL` / `RELEASE_AUTHORITY_PATH`.  A
missing or outdated build ID returns HTTP 426 with `CLIENT_UPDATE_REQUIRED`; an
unreachable authority or a paused gate returns HTTP 503 with
`AUTHORITY_UNAVAILABLE` or `SERVICE_PAUSED`.  Both precede generation work.

---

## 2. Envelope

Every v2 SSE event carries a `data:` field whose value is a JSON object
shaped as:

```json
{
  "context": { ... },
  "payload": { ... }
}
```

The `event:` line (SSE event name) is also present for v1 backward
compatibility but **must not** be used for routing decisions.

### 2.1 EventContext fields

| Field | Type | Scope | Notes |
|---|---|---|---|
| `run_id` | string | all | UUID4 hex; equals `GenerationLog.id` when one exists |
| `event_seq` | integer ≥ 1 | all | Monotonic per-run, assigned at publish time |
| `question_id` | string \| null | question-scoped | Format `<prefix><run_id>_<NNN>` |
| `index` | integer \| null | question-scoped | 0-based position in manifest |
| `subquestion_index` | integer \| null | subquestion-scoped | 0-based |
| `operation_id` | string \| null | work-scoped | Opaque; unique per run |
| `call_id` | string \| null | call-scoped | Opaque; unique per run |
| `content_revision` | integer \| null | content-scoped | ≥ 1; on `question_update` and `result` |

Rules:
- `started` is always `event_seq=1`.
- `done` is always the last event.
- Resending an event preserves its original `event_seq`.
- SSE heartbeat comments (`:`-prefixed lines) do not consume seq numbers.
- Unknown event names in valid envelopes occupy their seq slot but produce no
  evidence.
- Question payload `id` **must** equal `context.question_id` when both are
  present.

Example — `started` envelope:

```json
{
  "context": {
    "run_id": "abcdef1234567890abcdef1234567890",
    "event_seq": 1
  },
  "payload": {
    "protocol_version": 2,
    "total": 2,
    "questions": [
      {"index": 0, "question_id": "q_abcdef1234567890abcdef1234567890_001"},
      {"index": 1, "question_id": "q_abcdef1234567890abcdef1234567890_002"}
    ]
  }
}
```

Example — `question_update` envelope (question-scoped, with content_revision):

```json
{
  "context": {
    "run_id": "abcdef1234567890abcdef1234567890",
    "event_seq": 5,
    "question_id": "q_abcdef1234567890abcdef1234567890_001",
    "index": 0,
    "content_revision": 1
  },
  "payload": {
    "id": "q_abcdef1234567890abcdef1234567890_001",
    "情境": ["個人"],
    "題型種類": "單一題",
    "題型": "選擇題"
  }
}
```

---

## 3. Event families

| Family | Example event names | Scope |
|---|---|---|
| Batch lifecycle | `started`, `done` | batch |
| Batch progress | `progress` (textual log string) | batch |
| Pipeline | `pipeline` (stage lifecycle) | batch / question |
| Plan | `plan` (subquestion manifest announcement) | question |
| Work | `stage` (operation start/end) | question / subquestion / operation |
| LLM call | `llm_request`, `llm_thinking`, `llm_content`, `llm_response`, `llm_error` | call |
| Content | `question_update` (draft), `result` (final) | question |
| Terminal | `question_terminal` | question |
| Error | `error` | question or batch |

`progress` carries a plain text string in `payload` and provides no phase
evidence.  Textual progress remains batch-scoped.

`stage` events carry `operation_id` in context; an operation start may carry
`supersedes_operation_id` to identify the work attempt it replaces.  A
`llm_request` within the operation carries `call_id`; a retry carries
`retry_of_call_id`.

Invisible SDK retries are never fabricated as application-level `llm_*` events.

---

## 4. Run identity and manifest

### 4.1 run_id

`run_id` equals `GenerationLog.id` (UUID4 hex) when a generation log exists;
for direct-seam calls without a log a fresh UUID4 hex is allocated.  All
question identities derive from this `run_id`.

### 4.2 Pre-allocated manifest

Before any worker or planner starts, the server allocates the full question
manifest: question IDs are `<prefix><run_id>_<NNN>` using prefixes `q_` (math),
`ss_` (social studies), `ns_` (natural sciences) and one-based ordinals padded
to at least three digits.  Two identical requests receive different run IDs and
question IDs.

All consumers treat question IDs as opaque strings.  Existing database records
and image files are never renamed.

### 4.3 Subquestion identity (題組)

For a 題組, the server announces a zero-based subquestion manifest via a
`plan` event before work starts.  Each slot has `subquestion_index`,
`id: <question_id>-sq<NNN>` (1-based ordinal), and `序號 = subquestion_index + 1`.
Model-supplied IDs never control routing.  Dropping a slot does not renumber
survivors.  Flat math questions carry no subquestion identity.

---

## 5. Content revisions

### 5.1 Revision assignment

Each question has a server-side `QuestionSnapshotLedger` that assigns integer
`content_revision` starting at 1 and incrementing only when the effective
content signature changes.  The signature covers question text, answers,
subquestions, visual specifications, and image file contents.  It excludes
transport metadata, export annotations, and verification operational metadata.

### 5.2 What does and does not advance revision

Advances: changes to `題目`, `答案`, `答案解析`, `subquestions`, `chart_spec`,
or rendered image files.

Does not advance: transport `event_seq`, export `_export` field, review verdicts,
progress state, or re-encoding of existing `image_base64`.

### 5.3 Promoting draft to final

Unchanged content promoted from draft to final reuses the same revision; no new
revision is created.

---

## 6. question_terminal schema

One `question_terminal` per question is published at every worker exit.

```json
{
  "context": {
    "run_id": "abcdef1234567890abcdef1234567890",
    "event_seq": 18,
    "question_id": "q_abcdef1234567890abcdef1234567890_001",
    "index": 0
  },
  "payload": {
    "termination_reason": "normal",
    "has_final": true,
    "final_revision": 2,
    "delivery_status": "complete",
    "expected": [
      {"kind": "subquestion", "question_id": "q_abcdef1234567890abcdef1234567890_001",
       "subquestion_id": "q_abcdef1234567890abcdef1234567890_001-sq001",
       "subquestion_index": 0}
    ],
    "delivered": [
      {"kind": "subquestion", "question_id": "q_abcdef1234567890abcdef1234567890_001",
       "subquestion_id": "q_abcdef1234567890abcdef1234567890_001-sq001",
       "subquestion_index": 0}
    ],
    "missing": [],
    "review": {
      "status": "passed",
      "content_revision": 2
    }
  }
}
```

### 6.1 Field rules

| Field | Values | Rule |
|---|---|---|
| `termination_reason` | `normal` \| `failed` \| `cancelled` | `cancelled` requires `has_final=false` |
| `has_final` | boolean | true = a final `result` was published |
| `final_revision` | integer ≥ 1 \| null | non-null iff `has_final=true` |
| `delivery_status` | `complete` \| `partial` \| `none` \| `unknown` | See below |
| `expected` | SlotRef[] | Fixed-identity slots (subquestions + required images) |
| `delivered` | SlotRef[] | Subset of expected, disjoint from missing |
| `missing` | SlotRef[] | Subset of expected, disjoint from delivered |

> **Order non-normative.** The array order of `expected`, `delivered`, and `missing` is
> not significant.  Producers currently emit slots in manifest (slot_index) order, but
> consumers **must** compare these arrays as multisets by slot identity, not by position
> or JSON serialization order.  A resend that merely reorders slots must not be treated
> as a terminal contradiction.
| `review.status` | `passed` \| `failed` \| `skipped` \| `unknown` | Requires reason when unknown+has_final |
| `review.content_revision` | integer \| null | Must equal `final_revision` for definitive verdicts |

`delivery_status` rules:
- `complete`: `has_final=true` and `missing=[]`
- `partial`: `has_final=true` and `missing` non-empty
- `none`: `has_final=false` and all expected slots are missing
- `unknown`: `has_final=false` with an explicit `unknown_reason`

### 6.2 Review binding

A definitive review verdict (`passed`, `failed`, `skipped`) identifies the
specific `content_revision` it examined.  A verdict from revision 3 does not
carry to revision 4.  `question_terminal` may arrive before the matching
`result` on the wire; the client must handle both orderings.

### 6.3 Post-terminal sealing

After a `question_terminal` is sealed, the publisher rejects new work events
for that question and rejects new content except an idempotent resend of the
already-declared final at `final_revision`.

---

## 7. Buffer bounds and degraded mode

### 7.1 Out-of-order buffer

The client decoder (`createGenerationStreamDecoder`) maintains a bounded
out-of-order buffer for v2 events.  Events are held when `event_seq` is ahead
of the expected next seq.

### 7.2 Bounds (any one triggers degradation)

| Bound | Value | Trigger |
|---|---|---|
| Time since first gap | 2 seconds | Gap timer fires |
| Pending event count | 256 | Buffer count limit |
| Pending data size | 4 MiB (UTF-8 bytes) | Buffer byte limit |
| EOF / done with gap | immediate | Stream ends with open gap |

The timing clock starts at the **first gap event** (not at stream start).
Known duplicate events (same seq, same data) are deduplicated and do not
inflate the pending byte count.  Large in-order result events are not buffered
and cannot trigger size degradation.

After a non-degrading `checkDeadline()`, if a gap is still open the timer
re-arms for the remaining time.

### 7.3 Degraded mode behaviour

On degradation:
1. Decoder emits `{ kind: "degraded", reason: "timeout" | "count" | "size" | "eof_gap" }`.
2. Buffered `question_update`, `result`, and `question_terminal` events are
   flushed in seq order.
3. Activity-only events (`stage`, `llm_*`, `pipeline`) in the buffer are
   silently dropped.
4. After degradation, the decoder continues accepting `result` and
   `question_terminal` events for independent verification — it does not stop
   consuming the stream.

No auto-resubmit is triggered on degradation.

### 7.4 Degraded mode display

`RunEvidenceState.degraded = true` suppresses activity-only evidence updates.
`GenerationV2StatusLine` renders a `data-testid="statusbar-v2-degraded"` amber
notice.  Content already received remains available.

---

## 8. Conflict classes and reason codes

The decoder emits `{ kind: "conflict" }` events rather than silently discarding
conflicting data.  These are handled by `applyConflictEvent` before the v2-only
gate.

### 8.1 Conflict types

| `conflictType` | Trigger | Effect on evidence |
|---|---|---|
| `seq_data` | Duplicate seq with different raw data | Routes to `terminalConflict` (for `question_terminal`) or `contentConflict` (for `result`/`question_update`) when `questionId` known; otherwise `batchConflict` |
| `legacy_in_v2` | Raw legacy event (no `context` key) in v2 stream | Sets `legacyMixed` only; no evidence change |

### 8.2 Content conflict reason codes

Displayed via `card.conflict_reason_<code>` i18n keys (both `en-US` and
`zh-TW`):

| Code | Trigger |
|---|---|
| `seq_data` | `seq_data` conflict on a content event |
| `same_revision_different_content` | Same `content_revision`, different normalised content |
| `identity_mismatch` | `payload.id` ≠ `context.question_id` |
| `terminal_contradiction` | Contradictory `question_terminal` after seal |
| `terminal_invalid` | Malformed `question_terminal` payload |
| `review_contradiction` | Contradictory review evidence |

### 8.3 Isolation rules

- Only terminal disputes (type `terminal_contradiction`, `terminal_invalid`)
  set `processing = "unknown"` and reduce `endedCount` (X).
- Content conflicts do not affect X.
- `batchConflict` does not erase already-confirmed terminals.
- `legacyMixed` does not affect any evidence conclusions.
- After permanent degradation, `result` and `question_terminal` events are
  still accepted.

---

## 9. Legacy adapter (C1 × S0)

When a v2-capable client (`C1`) connects to an old server (`S0`) that does not
emit v2 envelopes, the decoder enters `legacy` mode.  All events route through
`LegacyAdapterState` (`web/src/lib/legacyAdapter.ts`).

### 9.1 Legacy wire format

The S0 wire format is `{event, data}` with no `context` or `payload` wrapper:
- `started.data` = `{"generation_log_id": null}` (JSON object string)
- `question_update.data` = `{"index": int, "phase": str, "question": {...}}`
- `result.data` = direct question JSON string
- `done.data` = `""`

### 9.2 Adapter rules

- Items keyed by opaque ID (`stable_id` → `question_id` → `question.id` → synthetic).
- `resolvedIndex: number | null` — `null` (原題序未知) until consistent explicit
  `index↔id` evidence arrives.
- Inconsistent mapping (same id → different index, or vice versa) is silently
  rejected; item stays at 原題序未知.
- Duplicate final (same id, already `isFinal`) is silently ignored.
- `done` sets `done: true` only — not per-question terminal evidence.
- No placeholder cards (no pre-allocated manifest).
- `requestTotal` comes from submitted params, not a manifest.

### 9.3 Display treatment

- Status bar shows "此批無每題即時進度" and "請求總數 N".
- Cards with `positionUnknown: true` show "原題序未知".
- No per-question processing/delivery/review labels.

### 9.4 C0 × S0 documented defects (unfixed)

These defects exist in old clients (`C0`) against old servers (`S0`) and are
documented for transparency.  They are not fixed in this change; old clients
remain C0:

- Index assignment by arrival order (`nextFinalIndexRef++`).
- No duplicate result deduplication.
- No consistent `index↔id` tracking.
- A later result may overwrite an earlier draft at the same position.

---

## 10. Compatibility matrix

| | S0 (old backend, no 426 gate) | S1 (new backend, 426 gate) |
|---|---|---|
| **C0** (old frontend, no `stream_version`) | Documented C0/S0 defects (see §9.4) | HTTP 426, zero dispatch, zero worker/model calls |
| **C1** (new frontend, `stream_version=2`) | Legacy adapter: content preserved, 原題序未知, 請求總數, no placeholders | Full v2 contract |

### C0 × S1 invariants (verified in `test_754_compat_matrix.py`)

- HTTP 426 before any generation.
- Body: `application/json` with `code: "CLIENT_UPDATE_REQUIRED"`.
- No `started` SSE event in the body.
- `stream_version=1` (wrong version) also returns 426.

### C1 × S1 invariants (verified in `test_754_compat_matrix.py`)

- `started` at `event_seq=1` with `protocol_version=2` and `questions` manifest.
- B's result/terminal may arrive before A's (interleaved confirmed).
- Each `question_update`/`result` has `content_revision >= 1`.
- Each `question_terminal` has all required fields.
- `question_terminal` arrives after its question's `result` in the normal path
  (client must handle both orderings).
- `done` is last.

### Fixture regeneration

```bash
bash scripts/generate_v2_fixtures.sh
# Verify drift:
choom -n 500 -- uv run pytest tests/server/test_754_fixture_drift.py -q
```

---

## 11. _export schema v1

The `_export` field is appended to the downloaded JSON copy only.  Live and
stored question objects are never modified.  Removing `_export` restores the
original captured question.

```json
{
  "_export": {
    "format_version": 1,
    "exported_at": "2026-09-27T10:00:00.000Z",
    "is_draft": false,
    "run_id": "abcdef1234567890abcdef1234567890",
    "index": 0,
    "content_revision": 2,
    "processing": "ended",
    "termination_reason": "normal",
    "delivery_status": "complete",
    "missing": [],
    "review": {
      "status": "passed",
      "content_revision": 2
    }
  }
}
```

### 11.1 Field definitions

| Field | Type | Notes |
|---|---|---|
| `format_version` | `1` (literal) | Always 1 for this revision |
| `exported_at` | ISO 8601 UTC string | Frozen at click time; shared per batch |
| `is_draft` | boolean | `true` when `receipt === "draft"` |
| `run_id` | string \| null | v2 run id; null for legacy/history |
| `index` | integer \| null | 0-based batch position; null = unknown order (legacy) |
| `content_revision` | integer \| null | From evidence; null for legacy/history |
| `processing` | `"waiting"` \| `"running"` \| `"ended"` \| `"unknown"` | |
| `termination_reason` | `"normal"` \| `"failed"` \| `"cancelled"` \| null | null = no terminal received |
| `delivery_status` | `"complete"` \| `"partial"` \| `"none"` \| `"unknown"` \| null | null = no terminal received |
| `missing` | SlotReference[] | From `terminal.missing`; empty when unknown |
| `review.status` | `"passed"` \| `"failed"` \| `"skipped"` \| `"unknown"` | |
| `review.content_revision` | integer \| null | Revision-matched review |

### 11.2 Compatibility note

`_export` is additive metadata.  External tools that reject unknown fields in
question objects are **not** guaranteed compatible and must strip `_export`
before processing.

---

## 12. ODT and preview rasterization contract

### 12.1 Image source priority

For each image slot in a frozen `QuestionSnapshot`:

1. `image_base64` present → `"png_base64"` kind → embedded directly.
2. `chart_spec` present (no `image_base64`) → `"chart_spec_preview"` kind →
   rasterization attempted via `defaultRasterizer`.
3. Slot in `terminal.missing` for `kind="image"` → `"known_missing"` kind →
   text marker `【圖片缺項】` at slot position.
4. None of the above → slot absent from `imageSources`.

Image sources are captured **at click time** from the frozen `QuestionSnapshot`,
not from live DOM updates.  A later image revision does not affect an
in-progress export.

### 12.2 Rasterization

- Uses same-source DOM capture (`previewMarkup` from live `FigureRenderer`).
- Does not call any LLM or image-generation provider.
- Per-image conversion failure → `匯出缺圖／預覽轉換失敗` marker at the
  affected slot; other content is preserved.
- Whole-ZIP failure → `OdtBuildError`; no corrupt file is produced; JSON
  download remains available.

### 12.3 Draft and partial content

- Draft questions are prefixed with `【草稿】` in the ODT heading.
- A 題組 with shared 文本 but no surviving 小題 remains a 題組 structure —
  it is not converted to an empty flat question.
- Final with unknown processing is `is_draft: false` — not relabelled as draft
  solely for missing terminal evidence.

---

## 13. FLOW.md and DEPLOYMENT.md references

FLOW.md covers the pre-v2 single-question lifecycle.  For v2:

- The `event_generator` in `routes.py` opens the SSE response after auth,
  `stream_version` check, and build-admission check.
- `GenerationPublisher` assigns monotonic `event_seq` thread-safely.
- `done` is emitted only after all workers finish and recorders flush.

DEPLOYMENT.md §"Generation admission gateway" covers:
- `scripts/admission_gate.py pause/open/status`
- Gateway Compose and Railway setup.

DEPLOYMENT.md §"Drain telemetry and release control" covers:
- `GET /internal/drain` endpoint and six gauges.
- `scripts/release_control.py` subcommands and inventory file.
- Recommended release runbook (pause-and-drain → deploy → verify → reopen).

For the compatibility matrix, buffer bounds, and 426 behaviour documented here,
the release runbook applies: **pause → drain (all six gauges zero on every
instance) → deploy → compat-check (`--require-version 2`) → verify → reopen**.

---

## 14. Document example validation

JSON examples in this document are validated by:

```bash
choom -n 500 -- uv run pytest tests/server/test_754_doc_examples.py -q
```

TypeScript `_export` examples are validated by:

```bash
cd web && choom -n 500 -- npx vitest run src/utils/exportSnapshot.docExamples.test.ts
```
