# 2026-09-17 — Issue #774: Preserve Received Results Across Update

## Summary

Issue #774 extends the existing `exam-generation.recovery/1` save-and-update
transaction from #772/#773 to the received-results workspace. A teacher may
have final questions, visible drafts, generated figures, progress, and review
evidence that have not been written to History yet. The update snapshot keeps
that exact browser-visible state without treating a History record as the
source of truth.

The envelope remains version `exam-generation.recovery/1`. A new optional
`results` member keeps form-only snapshots written by #772 and
form-plus-confirmation snapshots written by #773 readable.

## Preservation boundary

`generate.results` is the authoritative capture seam. Its adapter copies:

- final `results` used by the existing batch JSON/ODT exports;
- `displayResults`, including visible draft/partial cards and their fixed
  positions;
- requested and announced subquestion totals;
- visible progress lines, error text, and timestamps;
- stable question IDs or deterministic local IDs when no server ID exists;
- known content revisions, represented as `null` when the current stream did
  not provide one;
- the verification, figure-policy, and reference-example evidence already
  rendered by `QuestionCard`; and
- explicit processing/terminal evidence, including `unknown` when no
  question-level terminal evidence was observed.

The adapter deliberately does not copy `llmCalls`, request messages, model
payloads, credentials, abort controllers, callbacks, or other provider
diagnostics. The question-shaped copy uses the fields consumed by the current
result cards and exports. This keeps recovery content useful while preventing
the expanded UI trace from becoming durable user data.

## Image strategy

Images are persisted as raw base64 bytes in an explicit durable-image map,
keyed by stable question/subquestion identity. The normalized question copy
also carries the existing `image_base64` fields so the current renderer,
single-card PNG download, and ODT builder continue to work without a new
rendering path. Import validates and rehydrates those fields from the durable
map when necessary. `blob:` and other object URLs are rejected before the
transaction; no object URL is ever written to localStorage.

There is no byte-size truncation or result-count truncation. The existing
write-then-read-back transaction serializes the complete snapshot. Quota,
storage-denied, serialization, and read-back mismatch failures are surfaced
to the existing Save Draft & Update error UI, and a newly allocated partial
snapshot key is removed when possible. The live result cards and their
existing permitted exports remain untouched. A pointer failure leaves the
verified snapshot available but does not approve navigation.

## Restore and acknowledgement

`useGenerate.restoreResults()` only imports the normalized workspace and sets
React state. It never opens an SSE connection, calls `/api/generate`, reruns a
resolver/planner/preview, or infers a successful generation. Final content
and visible partial content remain separate; an interrupted stream remains
interrupted, and missing terminal evidence remains unknown even when a final
question body is present. A legacy result envelope that says `settled` without
the explicit terminal-evidence member is conservatively downgraded to
`unknown` during restore.

GeneratePage restores results once by snapshot identity before allowing the
recovery banner to delete the stored copy. If import or hydration fails, the
banner remains, an inline localized error is shown, and a later acknowledgement
attempt retries without deleting the snapshot. Form-only and confirmation-only
snapshots retain their #772/#773 acknowledgement behavior.

Restored images use the same base64-backed card renderer and downloads as the
live page. The existing final-only JSON/ODT controls remain unchanged for
partial content, and restored generated cards do not receive a History
`recordId`; therefore 人工審題修正 eligibility is unchanged. This issue does
not add draft-export capabilities.

## Eligibility

Save-and-update still refuses when any observed workspace operation is active,
including generation, export, resolver/planner work, or 人工審題修正. A
settled results surface is now preservable when its export is valid. The
release/account/target/workspace revision checks from #772/#773 remain
mandatory, and captured form, confirmation, and results exports must match
again after the release recheck.

## Verification scope

The adapter tests cover normalization, durable image maps, evidence, unknown
completion, rejected object URLs, and preservation of final versus partial
content. The real GeneratePage/router recovery flow is covered by
`web/src/pages/GeneratePage.results-recovery.test.tsx`; it uses the real
`useGenerate`, `GeneratePage`, `QuestionCard`, `ReleaseNotice`, recovery
storage, and save-and-update controller. Its five scenarios assert that:

- restored final results remain available to batch JSON and ODT exports, with
  restored image bytes passed to the ODT builder; final-card PNG download
  remains enabled while the partial-card PNG remains disabled;
- restored generated cards have no `history.modification` surface and expose
  no History-only instruction or submit controls, while the same real
  `QuestionCard` still exposes those controls when a History `recordId` is
  supplied;
- a quota failure on an image-bearing mixed final/partial batch leaves the
  live cards and images rendered, leaves JSON/ODT exports usable, retains the
  previously saved pointer and complete stored `results`/`displayResults`/
  `images` content, and does not navigate;
- a batch with no History IDs is still persisted and restored with both cards,
  images, and export controls intact; and
- an active generation operation disables Save Draft & Update in the rendered
  page and prevents navigation.

The implementation also fixes a preexisting boundary leak found by this
real-flow coverage: `QuestionCard` now gates History-only annotation deletion,
instruction, submit, and submit-error controls on `recordId`, while retaining
the existing non-History selection capture behavior. The focused regression
run for this change passed 3 files / 42 tests.

Final web verification from `web/`:

- `npx tsc -b --noEmit`: passed, 0 TypeScript errors.
- `npm run lint`: passed, 0 ESLint errors and 0 warnings.
- `npm test`: 132/132 test files passed; 1,310/1,310 tests passed.
- `npm run build`: passed; Vite transformed 446 modules. The command emitted
  only the existing Node deprecation and chunk-size warnings.
