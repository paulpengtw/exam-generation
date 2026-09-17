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

1. **Expired-session restore via same-tab sign-in** — pointer preserved through
   credential-clearing logout; snapshot restored after re-login.
2. **Different-account login refused** — `wrong_account` blocked without
   exposing `pending` contents; both sync and async variants.
3. **Explicit logout** — `logoutExplicit` deletes snapshots for current account,
   preserves other accounts, clears pointer; subsequent init finds nothing.
4. **Both 401 paths** — `apiFetch` 401 saves `session_expired` reason + return
   destination; snapshot preserved; non-401 errors leave auth intact.
5. **Two independent tabs** — simultaneous claims on distinct snapshot IDs both
   win; simulated concurrent overwrite causes the earlier tab to lose.
6. **Duplicate-tab collision** — `detectTabCollision` returns true when
   `startTabCollisionListener` is active; returns false otherwise; different tab
   IDs do not interfere.
7. **Denied marker storage** — `claimSnapshot` returns `won:false` on
   `setItem` throw or null read-back; `persistTabPointer` failure leaves
   snapshot intact but no pointer.
8. **Telemetry exclusion** — console calls, signout reason payload, and claim
   record contain no snapshot fields or content values.

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
