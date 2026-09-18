# 2026-09-17 — Issue #773: Preserve Confirmation Across Update

## Summary

Issue #773 extends the issue #772 "Save Draft & Update" transaction so an
update can be accepted while a settled 發送前確認 is open. After the target
build loads, the teacher must see the same confirmation payload, per-題組 and
per-小題 values, random-draw provenance, pins, and draft/History choice that
were visible before navigation. The ordinary form snapshot and the confirmed
payload are separate workspaces: confirmation-page edits must never be folded
back into the form or reconstructed from form defaults.

This note records the preservation boundary and implementation seams. It is a
research/design note for the completed change; the implementation keeps the
existing `exam-generation.recovery/1` reader compatible with snapshots
produced by #772.

## Baseline

### Existing recovery envelope

Before #773, `web/src/lib/recovery/format.ts` defined `RecoverySnapshotV1`
with a required `form: FormWorkspaceSnapshot` and no confirmation member. The
implemented parser still validates the schema discriminator, account, origin,
environment, and form kind/version, and now validates the optional
`confirmation` member before exposing a snapshot.
`web/src/lib/recovery/storage.ts` persists the envelope transactionally in
`localStorage` and keeps a small tab pointer in `sessionStorage`; its comments
explicitly prohibit logging or unmasking recovery contents.

The #772 snapshot is therefore form-only. A snapshot without a confirmation
member remains a valid old snapshot after #773.

### Existing confirmation state

The #769 workspace adapter already provides the natural serialization seam in
`web/src/lib/workspace/adapters/types.ts` and
`web/src/lib/workspace/adapters/confirmationWorkspace.ts`. Its current live
shape contains:

- `pendingParams`, the resolver-completed request payload;
- `pendingPerQuestionParams`, including the per-題組 rows and nested
  `subquestion_configs` when present;
- `clearedPaths` and `redraws`, using canonical resolver field paths;
- `hasPendingConfirmationEdits`;
- `coreQuestionResolution`; and
- `historyDraftChoice` (`draft`, `history`, `defaults`, or `null`).

`ParamForm.tsx` holds these values separately from `formFields`. Its
`exportConfirmation` seam reads live state from `pendingParams`, the
per-question rows, the cleared paths, the redraw counter ref, and the
resolution/history state. The display and edit handlers also make the
separation explicit: parent changes clear drawn descendants, subquestion
changes affect only the pending row, and returning to the form discards
confirmation-page edits.

### Existing eligibility and observable work

Before #773, `evaluateSaveAndUpdate` in
`web/src/lib/recovery/saveAndUpdate.ts` rejected every registered
`generate.confirmation` surface with `confirmation_open`. The implemented
evaluator now permits only an exportable, settled confirmation and retains the
same refusal for non-ready surfaces, active operations, received results,
modification drafts, unsigned users, unsupported target readers, and non-update
states.

`web/src/lib/workspace/workspaceStore.ts` increments
`workspace_revision` on surface and operation changes. `ParamForm.tsx` exposes
`generate.form` and, while confirmation is displayed,
`generate.confirmation`, through `useSurfaceParticipation`. Resolver,
planner, and prompt-preview work are registered as explicit operations with
the kinds `resolve`, `core_question_planning`, and `prompt_preview`
(`ParamForm.tsx:1638-1769`, `ParamForm.tsx:2452-2495`). These seams are the
authoritative way to decide whether a snapshot is settled and to detect a
change during the asynchronous release recheck.

## Intended preservation contract

### Envelope (S1)

Keep `schema: "exam-generation.recovery/1"`. Add an optional confirmation
workspace member to the existing envelope rather than changing the schema
string or making old fields conditional:

```text
RecoverySnapshotV1
├── existing release/account/route metadata
├── form: FormWorkspaceSnapshot                 # ordinary form state
└── confirmation?: ConfirmationWorkspaceSnapshot # settled pending send state
```

The optional member is absent for a form-only #772 save. It is present only
when the save began with a settled 發送前確認 and its export passed validation.
The parser must accept both shapes. If the optional member exists, it must be
validated by the confirmation adapter; malformed confirmation content must not
be hydrated as a form or silently regenerated.

The confirmation workspace must preserve the exact JSON-safe values that the
teacher could submit:

- the full `pendingParams`, including the resolved subject, request-level
  settings, `seed`, `per_question_params` wire value, and `drawn` paths;
- the independent `pendingPerQuestionParams` rows, including multiple 題組,
  each row's curriculum selections, text 出題指示, models/efforts, media
  settings, and nested 各小題配置;
- every `clearedPaths` entry and every `redraws` counter, without normalizing
  away paths that are no longer currently drawn;
- the value/pin state exactly as displayed. In the current design, a pinned
  value is the value in `pendingParams` or its row after an explicit edit,
  while its path is removed from `drawn`; the implementation must preserve
  both sides of that representation rather than infer pins from the ordinary
  form;
- `hasPendingConfirmationEdits` and `coreQuestionResolution`; and
- `historyDraftChoice`, plus an optional `pendingPrefill` JSON object carrying
  the raw pending prefill source when the form came from a draft or History
  record.

`pendingPrefill` is provenance, not a second source from which to rebuild
`formFields`. It exists so the restored confirmation can retain the same
draft-versus-History context without allowing a later hydration effect to
replace the already-resolved payload.

### Capture boundary (S2)

`runSaveAndUpdate` should capture the form and confirmation exports in one
synchronous pre-await section:

1. Evaluate the current workspace, release, and auth state.
2. Allow a `generate.confirmation` surface only when its export is present,
   its pending payload is valid, and no resolver/planner/preview operation is
   active. A confirmation with `coreQuestionResolution: "loading"`, active
   `resolve`, or active `core_question_planning`/`prompt_preview` is not
   settled; the button stays disabled (or the save returns the existing
   non-retryable refusal) until it settles.
3. Export `generate.form` and, if registered, `generate.confirmation` before
   awaiting `checkNow()`. Deep-copy the JSON-safe exports at this boundary so
   a late React/API callback cannot mutate the object that will be stored.
4. Freeze input, perform the existing bounded release recheck, and compare
   target build, target release support, account, and `workspace_revision`.
5. If any operation starts or ends, a surface changes, or a late callback
   changes registered state while the recheck/storage transaction is pending,
   fail safely, clear the freeze/approval state, and do not navigate. A
   revision change must not result in saving the earlier captured state as if
   it were current.
6. Write the one envelope transactionally, persist the existing pointer, then
   approve the navigation and navigate. No recovery content is emitted to
   telemetry or error messages.

The snapshot is a point-in-time pair: `form` is the ordinary editable form at
the capture instant, and `confirmation` is the exact pending send state at
that same instant. The latter is never rebuilt by calling `resolveGenerate`,
planning a core question, running a prompt preview, or drawing defaults.

### Restore boundary (S3)

`initRecoveryStore` remains responsible for pointer lookup, auth/route/origin/
environment checks, and parsing (`web/src/lib/recovery/recoveryStore.ts`). A
successful result exposes the complete envelope as `pending`; the page passes
both `pending.form` and `pending.confirmation` to `ParamForm` through the
existing recovery seam in `GeneratePage.tsx`.

When a confirmation member exists, `ParamForm` must initialize the confirmed
state and its refs from that member before schema/model/default hydration can
run. A mount-latched recovery input is required: clearing the recovery-store
banner after acknowledgement must not make a late prop change cause the form
or confirmation to fall back to `initialParams`, `loadDraft`, History, or
schema defaults.

Restore precedence is therefore:

```text
recovered form + recovered confirmation
        ↓
ordinary initialParams / History and local draft are metadata only
        ↓
schema/model discovery supplies labels and validation only
        ↓
no resolver, redraw, planner, prompt preview, or generation side effect
```

The restored confirmation is rendered immediately from its captured values.
It must remain visible while schemas or allowed-model data arrive. Delayed
discovery may add labels/options and validation markers but may not overwrite
the values, counts, seeds, models, efforts, media settings, curriculum codes,
per-題組 text instructions, or nested subquestion rows.

If a value is no longer admitted by the current schema, keep the original
value visible, mark that field invalid, and disable 確定發送 until the teacher
explicitly corrects it. Do not silently filter it out, redraw it, or replace it
with a default. The same rule applies to parent/child curriculum selections
and to values in `各小題配置`.

Acknowledging the recovery notice clears the stored snapshot/pointer through
the existing recovery-store action but leaves the in-memory confirmation
untouched. Discarding the notice removes the stored snapshot and likewise must
not mutate the already-rendered confirmation. The later explicit
`確定發送` action submits the captured current `pendingParams` plus the live
per-question rows exactly once. This is the proof that the same payload remains
available after update; it is not a new resolve request.

## Settled and refused states

The exception to #772's `confirmation_open` refusal is deliberately narrow:

| State at save request | Result |
|---|---|
| Form only, ready, no active operation | Existing #772 form-only save |
| Confirmation open, exportable, resolver settled, no active operation | Save form plus exact confirmation workspace |
| Resolver pending or error retry in progress | Refuse or wait; never capture a partial confirmation |
| Core-question planner active | Refuse or wait |
| Prompt preview/refetch active | Refuse or wait |
| Any `resolve` operation active | Refuse or wait |
| Results present | Continue refusing; #774 owns result preservation |
| Modification draft present | Continue refusing; #775 owns modification preservation |
| Any other workspace operation active | Continue refusing; #777 owns active-operation/scheduling behavior |
| Hydrating/restoring form or confirmation | Refuse until settled |

An already completed preview is display-only. Its text need not be part of the
recovery envelope; after restore it must be absent or explicitly marked stale
without automatically starting `prompt_preview`. This avoids a hidden network
operation and keeps the authoritative submitted payload in the snapshot. A
teacher may explicitly request a preview later.

The existing operation registry is not a cancellation mechanism. It only
observes admission and completion. A save must not abort planner, resolver, or
preview work; it must wait/refuse and use the revision check to protect the
captured settled state from late callbacks.

## Confirmation edits and provenance

The current confirmation handlers are the model for restored behavior:

- Parent edits remove the selected parent and its drawn descendants from the
  `drawn` list, record the canonical parent redraw path when required, and
  resubmit only because the teacher explicitly changed the parent.
- Child edits update only the addressed `per_question_params[i]` or nested
  `subquestion_configs[j]` row. Untouched 題組 and 小題 rows remain byte-equivalent
  in the submitted payload.
- An explicit 重抽 clears only the requested field, increments its canonical
  path in `redraws`, and resubmits with the seed and sibling fields unchanged.
- A non-blank confirmation-page 文本出題指示 is a per-row override; it does
  not mutate the form-level `text_instruction` or its draft.
- 返回修改 continues to discard confirmation-only edits and reveal the
  ordinary form snapshot. `確定發送` consumes the pending confirmation instead
  of rebuilding it from the form.

The recovery adapter should preserve these facts as data, not replay the edit
handlers on restore. Replaying them would consume new random draws, alter
redraw counters, or re-run the resolver.

## Backward compatibility and privacy

- Keep the format discriminator at `exam-generation.recovery/1` and make
  `confirmation` optional. A #772 form-only snapshot parses and restores
  exactly as before.
- Keep existing `TabPointer` optional fields and storage keys unchanged.
  Older pointers must continue to resolve to form-only snapshots.
- The target policy's existing `supported_recovery_formats` entry still gates
  the transaction. A target that advertises v1 must understand the optional
  confirmation member; otherwise the save is refused before navigation.
- Confirmation values must be JSON-serializable. Storage errors still use the
  #772 transactional read-back and cleanup behavior.
- The envelope contains generation parameters and curriculum/content values,
  not auth tokens, API keys, credentials, or request headers. No snapshot
  content, token, or credential may be sent to telemetry, included in a
  localized error, or logged while validating, saving, restoring, or rejecting
  a late callback.

## Test plan and authoritative seams

The current unit and integration tests establish the seams to extend:

| Requirement | Existing source / intended extension |
|---|---|
| Optional v1 confirmation round-trip and malformed input | `web/src/lib/recovery/format.test.ts`, `web/src/lib/workspace/adapters/confirmationWorkspace.test.ts` |
| Form and confirmed payload remain distinct | `web/src/components/ParamForm.confirmation-text-instruction.test.tsx`, `web/src/components/ParamForm.confirmation-display.test.tsx` |
| Multiple 題組, seeds, random badges, parent/child edits, redraws | `web/src/components/ParamForm.confirmation-display.test.tsx`, `web/src/components/ParamForm.workspace.test.tsx` |
| Per-小題 curriculum/configuration and History-carried rows | `web/src/components/ParamForm.prefill-live-subq-edits.test.tsx`, `web/src/components/ParamForm.workspace.test.tsx` |
| Planner/resolve/preview operation observation | `web/src/components/ParamForm.workspace.test.tsx` |
| Delayed schemas/models and invalid values | `web/src/components/ParamForm.recovery.test.tsx`, extended for restored confirmation |
| Real save → reload → restore flow | `web/src/recoveryFlow.test.tsx`, extended to drive the visible confirmation and Save Draft & Update controls |
| Target/release change during saving and late callback isolation | `web/src/lib/recovery/saveAndUpdate.test.ts`, `web/src/recoveryFlow.test.tsx` |

The issue-level flow tests should exercise all three subjects (`math`,
`social_studies`, `natural_sciences`) with more than one 題組 and actual
displayed controls. The fixture must include 文本出題指示, curriculum values,
models/efforts, image/media settings, random values, `各小題配置`, parent and
child edits, explicit 重抽, and a History-carried configuration. The test
should save through the real ReleaseNotice button, simulate navigation, delay
schema/model discovery, verify no resolver/planner/preview/generation call is
made by restore, then click the visible confirmation controls and assert that
the submitted payload equals the restored pending payload. A release target
change during the awaited save must leave navigation unapproved and storage
unchanged.

## Source references

- `docs/research/2026-09-15-772-save-draft-and-update.md` — recovery v1,
  transaction, eligibility, and form restore contract.
- `docs/research/2026-09-15-770-release-detection.md` — build/policy identity,
  release polling, and target-reader compatibility boundary.
- `web/src/lib/recovery/format.ts` — v1 envelope and parser.
- `web/src/lib/recovery/storage.ts` — transactional snapshot/pointer storage
  and privacy boundary.
- `web/src/lib/recovery/saveAndUpdate.ts` — eligibility and ten-step save
  controller; the confirmation exception belongs here.
- `web/src/lib/recovery/recoveryStore.ts` — authenticated, route-scoped
  restore store.
- `web/src/lib/workspace/adapters/types.ts` — form/confirmation snapshot
  contracts.
- `web/src/lib/workspace/adapters/formWorkspace.ts` and
  `web/src/lib/workspace/adapters/confirmationWorkspace.ts` — serialization
  seams and validation.
- `web/src/lib/workspace/workspaceStore.ts` and
  `web/src/lib/workspace/useSurfaceParticipation.ts` — readiness, operation,
  revision, and export observations.
- `web/src/components/ParamForm.tsx` — form/confirmation state boundary,
  explicit edit/redraw behavior, and confirmation rendering.
- `web/src/pages/GeneratePage.tsx` and `web/src/components/ReleaseNotice.tsx` —
  route/recovery consumption and visible save action.
- `web/src/i18n/messages.ts` — both locale dictionaries for any new recovery
  or invalid-restored-value strings.

## Verification evidence

Final verification was run from `web/` after the implementation and test
stability fix:

- `npx tsc -b --noEmit`: passed; 0 TypeScript errors.
- `npm run lint`: passed; 0 lint errors.
- `npm run build`: passed; Vite transformed 446 modules. The command emitted
  only existing Node deprecation and chunk-size warnings.
- `npm test`: 131/131 test files passed; 1,288/1,288 tests passed.
- `npm test -- src/components/ParamForm.workspace.test.tsx --run`, run three
  separate times: each run passed 1/1 file and 29/29 tests.
- The final working tree was clean after the two implementation/documentation
  commits.

An earlier isolated workspace run exposed a timing-sensitive assertion while
waiting for the planner operation to register. The test now waits for that
observable operation before asserting its state; all three required repeats
pass with the counts above.

## Explicit limits

This issue preserves only the settled generation form and 發送前確認. It does
not persist generation results, history modification drafts, or active
operations. Those remain the separate #774, #775, and #777 boundaries named by
the issue. It also does not introduce automatic preview regeneration, new
random draws, or a second recovery schema version.
