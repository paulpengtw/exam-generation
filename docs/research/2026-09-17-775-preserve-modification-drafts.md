# 2026-09-17 — Issue #775: Preserve Manual-Review Modification Drafts

## Summary

Issue #775 extends the existing `exam-generation.recovery/1` transaction so a
teacher can keep an unfinished 人工審題修正 workspace across an update. The
optional `modification` member carries the exact unsent 圈選 segments and
修改指示, the History route and immutable record/question identity, the known
content revision, eligibility evidence, and the latest settled replacement
question. Form, confirmation, and received-results members remain unchanged;
an older snapshot without `modification` still parses as before.

The recovery path is deliberately separate from the modification protocol.
Restore seeds the card and its settled result only. It never posts a new
modification batch, reconnects an old SSE stream, or recreates an old run.

## Capture boundary

`history.modification.exportWorkspace()` is the authoritative capture seam.
The adapter validates the JSON-safe workspace before the save transaction
accepts it. The saved evidence includes:

- the exact browser pathname and subject;
- the current History record ID and question ID;
- a deterministic canonical question-content identity, retaining question
  text, answers, curriculum fields, chart data, and normalized image bytes;
- an optional positive `contentRevision` when the question exposes one;
- completed/verified/eligible evidence used by the card's modification gate;
- every annotation and its UTF-16 selection offsets, including multiple
  segments and an unfinished instruction; and
- the latest `ModificationRunResult`, including its replacement question,
  ripple report, verification, and failure details, when a run has settled.

The existing v1 envelope still requires `form`. A History-only save supplies a
valid empty form snapshot as an envelope sentinel; it does not pretend that a
History page contains an ordinary generation form. Save is allowed only when
the modification surface has editable annotations or a received settled
result and its adapter evidence is eligible. Empty History pages, malformed
exports, and any active workspace operation remain refused.

The controller deep-clones the modification export before awaiting the release
recheck, then compares the fresh workspace export and revision before writing.
Thus a late callback cannot turn the captured point-in-time draft into an
apparently current one. A storage failure clears only the transaction's
freeze/approval state and leaves the live card untouched; no recovery content
is sent to telemetry.

## Exact base-version check on restore

`HistoryDetail` boots the recovery store before mounting the card. When a
modification member is present for the current pathname, it fetches the
requested History record through the existing authenticated History API and
holds the card's submit gate closed until that check settles.

The check is intentionally conservative:

1. The response `id` must equal the saved `recordId`. The History endpoint
   follows a user's version chain to the newest descendant, so a different
   response ID means the requested route now resolves to another version and
   is blocked rather than silently retargeted.
2. The route, subject, `question_id`, canonical content identity, and known
   content revision must match. A known-vs-unknown revision is also a mismatch.
3. The current record must be `completed`, have a question payload, and retain
   the saved eligibility evidence. An original base still needs a passed
   verification; a settled replacement follows the existing card rule that a
   returned attempt can be reviewed again even when its verification failed.

Changed record/version, question, subject, content, revision, status, failed
verification, and ineligible evidence keep the captured controls visible but
disable selection mutation, deletion, instruction editing, and submission.
HTTP 401/403/404 and transient fetch failures keep the snapshot and show a
localized explanation. Retry re-fetches the current base; it does not replay
the modification run. A valid check enables the existing independent submit
path. Acknowledge/discard removes the persisted copy through the recovery
store while the already rendered card state remains mount-latched.

## Active runs and UI invariants

The existing `modification` operation remains registered from admission through
the SSE terminal event. Release detection does not cancel it, and
Save Draft & Update is refused while it is active. After a terminal result,
the card exports the newest effective child record and replacement content for
a later save. Existing field qualification, frozen-field handling, masking,
selection serialization, keyboard behavior, and final-only download paths are
not replaced by the recovery adapter.

## Behavioral test evidence

The acceptance behavior is exercised through the real History detail and
QuestionCard, not only through serializer tests, in
`web/src/pages/HistoryDetail.recovery.test.tsx`:

- multiple unsent selections and their separate instructions are captured;
- a settled replacement is captured and restored without admission or SSE
  activity;
- an active modification stream keeps the Save Draft & Update control
  disabled while its workspace operation remains registered;
- a matching base restores an unfinished draft, enables it only after the
  re-fetch, and leaves the card state after explicit acknowledgement;
- changed record ID, changed content, and changed content revision block
  submission while retaining the snapshot;
- each of HTTP 401, 403, and 404 is treated as an authorization/unavailable
  block while retaining the snapshot;
- a localStorage quota failure leaves the live instruction in the card and
  does not create a pointer; and
- a transient restore failure keeps the pointer/snapshot, then retries the
  History check without any modification POST or SSE connection.

Supporting tests cover the exact base comparison in
`web/src/lib/recovery/modificationValidation.test.ts`, v1 optional-member and
backward-compatible parsing in `web/src/lib/recovery/format.test.ts`, strict
annotation/replacement validation and canonical identity in
`web/src/lib/workspace/adapters/modificationWorkspace.test.ts`, settled-result
hydration without network work in `web/src/hooks/useModificationRun.test.ts`,
card-level multi-selection/latching and blocked-control behavior in
`web/src/components/QuestionCard.workspace.test.tsx`, and both-locale message
coverage in `web/src/i18n/messages.coverage-mode.test.ts`.

## Verification

The final counts below are recorded after the complete web verification run:

- `npx tsc -b --noEmit`: passed; 0 TypeScript errors.
- `npm run lint`: passed; 0 ESLint errors and 0 warnings.
- `npm test`: passed; 134/134 test files and 1,361/1,361 tests passed in
  49.11s. The suite emitted existing React
  `act(...)` notices and jsdom navigation notices, but no test failures.
- `npm run build`: passed; Vite transformed 447 modules in 481ms. It emitted
  the existing Node `module.register()` deprecation warning and the existing
  >500 kB chunk-size warning; there were no build errors.
