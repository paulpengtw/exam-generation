# per-question live progress is a conditional exception to concurrent-batch unattributability

## Context

ADR 0009 established that concurrent-batch generation events carry no question
identity, so the browser cannot attribute them to individual questions and
displays aggregate counts instead.  Issues #748–#753 add a v2 event protocol
(`stream_version=2`) that stamps every server-side event with an immutable
`{context: {run_id, event_seq, question_id, index, …}}` envelope before
emission, making per-question attribution possible at the transport layer.

The exception is conditional: the v2 contract and the release acceptance gates
described below must both be satisfied before per-question live progress is
considered authoritative.  Until then ADR 0009's aggregate-only rule remains
in effect for any session that cannot demonstrate v2 compliance.

This ADR does not modify ADR 0016.  Question JSON remains separated from
verification/correction history (first-class sibling records); the
`verification_trail` column is never embedded in the exportable question
payload.  See ADR 0016 for the authoritative statement of that invariant.

## Decisions

**Condition 1 — v2 contract.**  The server must emit v2 envelopes and the
client must parse them.  Specifically:

- Every generation event carries a `{context, payload}` envelope.
- `context.run_id`, `context.event_seq` (monotonic from 1), `context.question_id`
  and `context.index` are present on every question-scoped event.
- `started` is `event_seq=1` and carries `protocol_version: 2`, `total` and
  `questions: [{index, question_id}]` (the pre-allocated manifest).
- Every question produces exactly one `question_terminal` with `termination_reason`,
  `has_final`, `final_revision`, `delivery_status`, `expected`/`delivered`/`missing`
  slots, and `review`.
- The client sends `stream_version=2` on every generation request; the server
  rejects absent or mismatched versions with HTTP 426 before dispatching work.

**Condition 2 — release acceptance gates.**  The v2 exception is not in effect
until all of the following are satisfied and documented:

1. The cross-layer fixture tests in `tests/server/test_754_compat_matrix.py`
   and `tests/server/test_754_fixture_drift.py` pass on the deployed build.
2. The frontend vitest suite (including `generationStream.*.test.ts`,
   `generationEvidence.*.test.ts`, `legacyAdapter.test.ts`) passes.
3. The generation admission gateway is in the `open` state with a positive
   `quiescent: true` observation from every backend instance after the
   gate opened (see DEPLOYMENT.md §"Drain telemetry and release control").
4. A teacher-visible browser acceptance has confirmed that per-question
   status labels (處理狀態, 終止原因, 交付完整性, 審題結果) and download
   actions (草稿/最終結果 JSON and ODT) behave as documented.

**OpenSpec sync is not a release gate.**  Merging or archiving the
`per-question-live-progress` OpenSpec change does not by itself satisfy either
condition.  The tasks in `openspec/changes/per-question-live-progress/tasks.md`
§9–§10 describe the evidence required; conditions are met only when that
evidence is collected, reviewed, and accepted.

**Fallback rule.**  Any session that cannot demonstrate v2 compliance — old
frontend (`C0`), old backend (`S0`), degraded stream, or missing manifest —
continues to follow ADR 0009: no per-question attribution, aggregate counts
only, legacy-adapter labels (原題序未知, 請求總數).  The compatibility matrix
(documented in `docs/generation-event-protocol.md`) governs which display mode
applies.

**ADR 0009 remains in force for legacy sessions.**  The legacy / unattributable
limitation text in ADR 0009 is preserved and must not be removed.  ADR 0009
now carries a link to this ADR so readers can find the conditional exception.

**ADR 0016 is explicitly preserved.**  The principle that question JSON is
separated from the verification trail (first-class sibling column) continues
unchanged.  The v2 event protocol adds a transport-layer `context.content_revision`
field to `question_update` and `result` events; this field identifies the immutable
snapshot revision but is never inserted into the stored question payload.

## Consequences

When both conditions above are met, the client may display per-question
processing status, termination reason, delivery completeness and review result
as authoritative data.  The status bar may show "已結束 X/N 題" and "收到最終
結果 Y 題" with X and Y derived from unique question-terminal and result
evidence respectively, not from arrival-order counts.

When either condition is not met, the client must display aggregate counts (or
legacy labels), and no per-question attribution may be claimed.

## See also

- ADR 0009 — concurrent batches are unattributable (legacy rule, still in force)
- ADR 0016 — verification trail is persisted first-class, sibling to the question
- `docs/generation-event-protocol.md` — full v2 protocol reference including
  compatibility matrix, buffer bounds, conflict classes, and `_export` schema
- `openspec/changes/per-question-live-progress/tasks.md` — acceptance task list
