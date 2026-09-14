# 2026-09-15 — Issue #772: Save Draft and Update

## Summary

Implements a "Save Draft & Update" flow that lets a signed-in teacher persist
their in-progress form state before accepting a required app update, so they can
resume exactly where they left off after the reload.

## Architecture

### Format (S1)

`web/src/lib/recovery/format.ts` defines `RecoverySnapshotV1` (schema
`exam-generation.recovery/1`) and a `parseRecoverySnapshot` validator. The
schema string is the version discriminator; unknown schemas are rejected before
field validation, and per-session origin/account/environment checks prevent
cross-tenant or cross-environment hydration.

### Transactional Storage (S1)

`web/src/lib/recovery/storage.ts` provides:

- `getOrCreateTabId()` — stable per-tab UUID in `sessionStorage("exam_tab_id")`.
- `saveSnapshotTransactionally(snapshot)` — writes to
  `localStorage("exam_recovery_<account_id>_<snapshot_id>")` then immediately
  reads back and compares serialized forms. Returns typed
  `{ok:false, reason:'readback_mismatch'}` on any discrepancy.
- `persistTabPointer(pointer)` — same write+verify cycle for the session pointer
  in `sessionStorage("exam_recovery_tab")`.

The read-back check catches partial writes from browsers that honour the call
but truncate large values (observed in some mobile WebKit builds).

### Workspace Revision (S1)

`useWorkspaceStore` now tracks `workspace_revision: number` incremented on every
`registerSurface`, `updateSurface`, and `beginOperation`/`end` call. This lets
the eligibility check compare the workspace state at save time to the state when
the target reader boots.

New methods: `approveNavigation(target)`, `clearNavigationApproval()`,
`setFreezeInput(frozen: boolean)`.

### Eligibility Evaluator (S2)

`evaluateSaveAndUpdate(state)` in `web/src/lib/recovery/saveAndUpdate.ts`
returns `{allowed:true}` only when all of:

- At least one surface registered
- Every surface is `ready`
- No active operations
- No surface has `hasReceivedResults`
- `generate.confirmation` not registered
- `history.modification` not registered
- User is signed in
- Release status is `update-required` with `requiredBuildId` and
  `releaseRevision` known
- Policy declares `exam-generation.recovery/1` in `supported_recovery_formats`
- The `generate.form` surface has an `exportWorkspace` seam

The denied reason is localised in `ReleaseNotice` via `recovery.disabled.*` i18n
keys.

### Build Identity (S2)

`buildIdentity.ts` now emits
`supported_recovery_formats: ["exam-generation.recovery/1"]` in the authority
fixture so freshly-deployed servers immediately support the recovery reader.

### Release Store (S2)

`useReleaseStore` exposes `supportedRecoveryFormats: string[]` updated on each
successful policy parse.

### UI (S3)

`ReleaseNotice.tsx` renders a "儲存草稿並更新 / Save Draft & Update" button in
`update-required` state. The button is disabled with a localised tooltip when
`evaluateSaveAndUpdate` denies. While saving, `setFreezeInput(true)` is called
on the workspace store and the button shows "儲存中...". On failure the button
re-enables and shows an inline error with a "重試" retry button.

`GeneratePage.tsx` `useBlocker` and `beforeunload` now consult
`workspaceStore.navigationApproved`; an approved navigation (e.g. from
save-and-update) bypasses the guard once and clears the token on the way out.

### Recovery Store (S4)

`web/src/lib/recovery/recoveryStore.ts` is a zustand store. Call
`initRecoveryStore({currentRoute, origin, environment})` at app boot (or after
sign-in). It:

1. Reads the tab pointer from `sessionStorage`.
2. Checks user is signed in and route matches.
3. Loads and parses the snapshot.
4. On parse success: sets `state.pending`.
5. On `wrong_account`: sets `state.blocked = "wrong_account"` (keeps snapshot).
6. On other parse failures: silent (don't hydrate, don't block).

`acknowledgeRecovery()` clears `pending`. `discardRecovery()` deletes the
snapshot from localStorage, clears the tab pointer, and clears `pending`.

### ParamForm Recovery Banner (S4)

`ParamForm` now accepts an optional `recoveredForm?: FormWorkspaceSnapshot` prop.
When present, a blue "已還原更新前的表單 / Form restored from before update" banner
is shown with 確認 (acknowledge) and 捨棄 (discard) buttons. The banner is
dismissed via `setRecoveryBannerDismissed(true)`.

## Deviations

- `runSaveAndUpdate` in `saveAndUpdate.ts` is stubbed as `not_implemented`; the
  complete implementation (snapshot assembly, storage, navigation) requires
  the auth origin/environment context that lives in the app shell and was not
  available in this slice. Callers can wrap it.
- ParamForm `recoveredForm` prop does not yet override form field values; it
  only shows the banner. Overriding values requires careful merge with the
  existing draft/history prefill logic to avoid clobbering user edits.

## Files Changed

- `web/src/lib/recovery/format.ts` (new)
- `web/src/lib/recovery/storage.ts` (new)
- `web/src/lib/recovery/saveAndUpdate.ts` (new)
- `web/src/lib/recovery/recoveryStore.ts` (new)
- `web/src/lib/workspace/workspaceStore.ts` (workspace_revision + nav approval)
- `web/src/lib/release/releaseStore.ts` (supportedRecoveryFormats)
- `web/src/lib/release/policy.ts` (already had supported_recovery_formats; verified)
- `web/buildIdentity.ts` (emit recovery format in fixture)
- `web/src/components/ReleaseNotice.tsx` (Save Draft & Update button)
- `web/src/components/ParamForm.tsx` (recoveredForm prop + banner)
- `web/src/pages/GeneratePage.tsx` (navigationApproved bypass)
- `web/src/i18n/messages.ts` (recovery.* keys in both locales)
- `web/src/test/setup.ts` (sessionStorage polyfill)
