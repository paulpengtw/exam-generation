# 2026-09-18 — Issue #776: Recovery Identity and Cross-Login Correctness

## Summary

Issue #776 hardens the recovery transaction from #772–#775 against three real
failure modes: credential expiry during an update, a different account signing
in on the same device, and a duplicated browser tab racing to hydrate the same
snapshot.  The envelope format and the save-and-update controller are
unchanged; the changes are entirely in the identity layer that sits between
storage and the recovery store.

## Threat model

### Credential expiry
A teacher starts an update, the reload triggers, and the new build's first API
call returns 401.  The session expired between the snapshot being saved and
the page reloading.  The snapshot is valid and belongs to this teacher; the
session is simply stale.  The teacher signs back in on the same tab, the
return destination is known, and the same tab that holds the pointer navigates
back to the generate page.

### Different-account login
A shared device or incognito-then-regular scenario: teacher A saved a snapshot,
signed out, and teacher B signed in on the same browser.  Teacher B must never
see or hydrate teacher A's snapshot.  The parser already enforces `account_id`
equality; the store must expose `blocked: "wrong_account"` without setting
`pending`, so the UI can show a generic notice without leaking contents.

### Tab duplication
`sessionStorage` is copied verbatim when a browser tab is duplicated (Ctrl+Drag
in many browsers, Chromium's "Duplicate tab").  The duplicate carries the same
`exam_tab_id`.  If both tabs reach `initRecoveryStoreAsync` concurrently, they
race to hydrate the same snapshot.  Only one should win.

## Design decisions

### Two kinds of 401: expiry vs. explicit logout

The key invariant: credential expiry (`apiFetch` 401, stream `onopen` 401) must
keep the recovery snapshot; explicit user logout must delete it.

**`authStore.logout()`** — the 401-path method.  Clears token and user from
localStorage/state.  Does NOT touch recovery snapshots or tab pointer.  Both
`apiFetch` and `useGenerate`'s `fetchEventSource.onopen` call this path.  Both
also call `saveSignoutReason("session_expired", userId)` and
`saveReturnDestination(pathname)` so the login page shows the correct banner and
can navigate back after sign-in.

**`authStore.logoutExplicit()`** — the UI-initiated method.  Calls
`deleteAllSnapshotsForAccount(user.id)` and `clearTabPointer()` before clearing
credentials.  A new account signing in next finds no stale snapshots.

`renewSessionIfNeeded` already saved the signout reason on 401; the new change
extends the same pattern to the direct `apiFetch` 401 path, which previously
only called `logout()`.

### Transactional restoration claim

Before hydrating a snapshot, `initRecoveryStoreAsync` writes a claim record:

```
localStorage  exam_recovery_claim_<snapshot_id>
  { tab_id, nonce (UUID), snapshot_id, claimed_at }
```

The claim is a write-then-read-back transaction matching the snapshot storage
pattern from #772.  The nonce is not a secret; it is structural — two tabs
writing concurrently produce different nonces.  The tab that wrote last is the
one whose nonce reads back; it wins.  The loser reads the winner's nonce, sees
a mismatch, and exits without hydrating.

The claim is held in state (`claimedTabId`, `claimedSnapshotId`) and released
by `acknowledgeRecovery` or `discardRecovery`.  A claim is never held past the
snapshot being consumed or discarded.

### BroadcastChannel collision detection

`detectTabCollision(tabId, timeoutMs)` broadcasts a `{type: "probe", tabId}`
message and waits for an `{type: "alive", tabId}` response.  Any tab running
`startTabCollisionListener(myTabId)` replies when probed for its own ID.

If the probe gets a response within the timeout, the caller knows a live tab
already owns that ID and should mint a new one.  If no response arrives, the
ID is free.

The synchronous `initRecoveryStore` (existing boot-time path) is unchanged for
backward compatibility.  The new `initRecoveryStoreAsync` uses the transactional
claim but does not itself run the BroadcastChannel probe; the app is expected
to call `detectTabCollision` + `startTabCollisionListener` at boot and replace
the tab ID in `sessionStorage` before calling `initRecoveryStoreAsync`.  This
keeps the async store init pure storage and avoids coupling it to a timing-
sensitive channel protocol.

### Snapshot lifetime (unchanged)

Successful visible restoration or explicit discard removes the snapshot; failed
hydration does not.  `acknowledgeRecovery()` now also releases the claim.
Unacknowledged update snapshots still have no automatic expiry.

### No telemetry of recovery contents

`deleteAllSnapshotsForAccount` enumerates key names only (structural prefixes),
not values.  `claimSnapshot` writes a claim record that contains only structural
fields (tab_id, nonce, snapshot_id, claimed_at).  Neither function logs or
passes account IDs or snapshot contents to any monitoring sink.

## Storage keys added (issue #776)

```
localStorage  exam_recovery_claim_<snapshot_id>  — transactional claim
```

All existing keys from #772 are unchanged.

## Changed files

| File | Change |
|------|--------|
| `web/src/lib/recovery/storage.ts` | Add `claimSnapshot`, `releaseSnapshotClaim`, `deleteAllSnapshotsForAccount`, `startTabCollisionListener`, `detectTabCollision` |
| `web/src/store/authStore.ts` | Add `logoutExplicit()`, document `logout()` as expiry-only |
| `web/src/api/client.ts` | On 401: save signout reason + return destination before calling `logout()` |
| `web/src/hooks/useGenerate.ts` | Stream 401: same signout reason + destination pattern |
| `web/src/lib/recovery/recoveryStore.ts` | Add `claimedTabId`/`claimedSnapshotId` state, `initRecoveryStoreAsync`, claim lifecycle in ack/discard |
| `web/src/i18n/messages.ts` | Add `recovery.identity.*` keys in both locales |
| `web/src/lib/recovery/recoveryIdentity.test.ts` | 31 new tests covering all required scenarios |

## Tests added

### Test type key
- **unit test** — calls library/store functions directly, no React render
- **router-driven test** — renders the real app router (`createMemoryRouter` + `renderApp`) and asserts on visible UI
- **real-hook test** — renders a hook with `renderHook`, mocks only the transport layer

### Identity a — Expired-session restore via same-tab sign-in
**Mixed: one router-driven test + one unit test**
- `recoveryFlow.test.tsx`: "recovery banner appears after the user re-signs-in on the same tab" — **router-driven** (renderApp, asserts on recovery banner text)
- `recoveryFlow.test.tsx`: "credential-clearing logout preserves snapshot in storage" — **unit test** (calls `logout()` directly, asserts on `loadSnapshot`)

### Identity b — Different-account login refused
**Unit test** (no React render)
- `recoveryFlow.test.tsx`: two tests calling `initRecoveryStore` / `initRecoveryStoreAsync` directly and asserting on store state (`blocked: "wrong_account"`).
- What is NOT tested here: the user-visible warning banner that appears in the UI when `blocked` is set.

### Identity c — Explicit logout invalidates recovery
**Mixed: one router-driven test + one unit test**
- `recoveryFlow.test.tsx`: "clicking logout in SubjectSelectPage deletes the snapshot" — **router-driven** (renders real router, fires logout button click)
- `recoveryFlow.test.tsx`: "logoutExplicit (the call behind the UI button) deletes snapshots" — **unit test** (calls `logoutExplicit()` directly)

### Identity d — Both 401 paths preserve snapshot
**Unit test** (no React render)
- `recoveryFlow.test.tsx`: "apiFetch 401 clears auth but leaves snapshot on disk" — **unit test** (spies on `globalThis.fetch`, calls `apiFetch` directly)
- `hooks/useGenerate.401.test.ts`: "onopen 401 saves session_expired reason, calls logout() but NOT logoutExplicit(), leaves snapshot intact" — **real-hook test** (imports real `useGenerate`, mocks only fetchEventSource transport, asserts snapshot intact + signout reason + logoutExplicit NOT called)

### Identity e — Two independent tabs each keep their own snapshot
**Unit test** (no React render)
- `recoveryFlow.test.tsx`: two tests calling `claimSnapshot`, `releaseSnapshotClaim`, `initRecoveryStore` directly and asserting on store state.
- What is NOT tested here: the user-visible form state in each tab (requires two concurrent browser tabs — not feasible in jsdom).

### Identity f — Duplicate-tab collision detection
**Unit test** (no React render)
- `recoveryFlow.test.tsx`: three tests calling `detectTabCollision`, `startTabCollisionListener`, `initRecoveryStoreAsync` directly.
- What is NOT tested here: real duplicate-tab browser behavior (Ctrl+Drag, copied sessionStorage) — requires E2E test.

### Identity g — Denied marker storage blocks save-and-update
**Router-driven test** (uses `renderApp`)
- `recoveryFlow.test.tsx`: "save-and-update returns snapshot_failed when localStorage.setItem is denied" — **router-driven** (renderApp, fills topic input, mocks localStorage)
- `recoveryFlow.test.tsx`: "claimSnapshot returns won:false when localStorage throws" — **unit test**

### Identity h — Telemetry exclusion
**Unit test** (no React render)
- `recoveryFlow.test.tsx`: three tests calling `logoutExplicit()`, `deleteAllSnapshotsForAccount()`, `apiFetch()` directly and spying on console methods.
- What is NOT tested here: browser DevTools console during a real UI logout session.

### Regression tests
- `lib/recovery/recoveryIdentity.test.ts`: 31 unit tests covering all required scenarios at the mechanism level (storage, store, claim lifecycle).
- `components/ParamForm.recovery.test.tsx`: "sparse snapshot crash regression (#776)" — **router-driven test** (renders ParamForm with `fields: { topic: "..." }` as never, asserts no crash and recovery banner appears). Covers the `passage.trim()` crash fixed in commit 39fe0a9.

## Ambiguities and conservative choices

- **`initRecoveryStore` kept synchronous** — existing callers (recoveryStore
  tests, recoveryFlow integration tests) call the synchronous variant.  The
  new async variant is additive.  App boot is expected to call the async
  variant; the sync variant is the fallback for environments without
  BroadcastChannel or when the app cannot await init.
- **Collision detection not integrated into `getOrCreateTabId`** — keeping
  `getOrCreateTabId` synchronous avoids breaking the many call sites that
  expect a synchronous result.  The probe is a separate async step.
- **Claim does not prevent duplicate tabs from loading the page** — it only
  prevents two tabs from both hydrating the same snapshot.  The duplicate tab
  gets an empty form, which is the correct no-snapshot behavior.
- **`deleteAllSnapshotsForAccount` also clears orphaned claims** — any stale
  `exam_recovery_claim_*` keys are swept on explicit logout to avoid leaving
  ghost entries that could block a future claim.

## Wiring (implemented post-mechanism)

The mechanism files were built first; the wiring into the real boot path and
router-driven acceptance tests were added in a follow-up pass on the same branch.

### Explicit-logout routing

`SubjectSelectPage.tsx` and `GeneratePage.tsx` both call
`useAuthStore((s) => s.logoutExplicit)` through the logout button / logout
confirmation flow.  Expiry paths (`apiFetch`, `useGenerate.ts`,
`sessionRenewal.ts`) keep `logout()`.  Both pages' unit-test mocks were
updated to expose `logoutExplicit` instead of the formerly stubbed `logout`.

### Two-phase boot pattern

React 18/19's `act()` in tests flushes microtasks but not macro-tasks
(setTimeout).  `detectTabCollision` uses a 100 ms `setTimeout` fence; running
it inside `useLayoutEffect` caused the form to appear as loading for the full
100 ms after each test render, timing out several integration tests.

The fix uses two effects per page:

**Phase 1 — `useLayoutEffect` (synchronous)**

```typescript
useLayoutEffect(() => {
  initRecoveryStore({ currentRoute, origin, environment });
  // eslint-disable-next-line react-hooks/set-state-in-effect
  setRecoveryBootedKey(recoveryBootKey);
}, [recoveryBootKey, ...]);
```

Sets `pending` optimistically so the form renders immediately on the first
paint, matching the behaviour before #776.

**Phase 2 — `useEffect` (async, runs after first render)**

Performs `detectTabCollision`, `initRecoveryStoreAsync`, and
`startTabCollisionListener`.  If the async claim is lost (another tab won),
Phase 2 clears the optimistic `pending` from Phase 1 so stale recovery content
is never surfaced.

This pattern was applied identically to both `GeneratePage.tsx` and
`HistoryDetail.tsx`.

### `ParamForm.tsx` — defensive recovery field initialisation

`ParamForm` initialises `formFields` from `recoveryForm.fields` when a recovered
form is present.  The original code spread `recoveryForm.fields` directly,
relying on every `FormFields` key being present.  A snapshot created with a
minimal field set (as done in `seedSnapshot()` test helpers) left `passage` and
other required fields as `undefined`, causing a `passage.trim()` crash at render
time.

The fix replaces the bare spread with an explicit per-field initialisation that
mirrors the non-recovery default path, falling back to the same defaults
(`TEXT_HINT`, `OPTION_HINT`, `DEFAULT_CONTENT_TYPE`, etc.) when a field is
absent or has the wrong type.

### Recovery identity acceptance tests

Eight `describe` blocks in `web/src/recoveryFlow.test.tsx` (identity a–h) plus
one real-hook test in `web/src/hooks/useGenerate.401.test.ts` cover all
acceptance criteria.  See the **Tests added** section above for the exact
test-type label of each describe block.

Key implementation notes:

- `beforeEach` calls `vi.restoreAllMocks()` before `vi.clearAllMocks()` to
  prevent `localStorage.setItem` spy from identity g leaking into identity h.
- Identity c's confirm button selector uses `/^Sign out$|^登出$/` (real i18n
  translation values) rather than a key-passthrough pattern, since
  `recoveryFlow.test.tsx` does not mock `useT`.
- Identity d's tautological stream-401 test was removed and replaced by
  `hooks/useGenerate.401.test.ts`, which imports the REAL `useGenerate` hook,
  mocks only the `fetchEventSource` transport, and asserts snapshot intact +
  `session_expired` reason + `logoutExplicit` NOT called.
- Identities b, d (remaining), e, f, h are unit-level (no `renderApp` call);
  their `(router-driven)` title suffix was removed and a comment was added
  explaining what level each test covers and what is out of scope for jsdom.
