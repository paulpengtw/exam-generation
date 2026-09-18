# 2026-09-18 — Issue #777: Safe Scheduled Update and Blank-Page Prevention

## Summary

Issue #777 builds three cooperating safety layers on top of the save-and-update
flow from #772–#776:

1. **Queued update intent** — lets a user schedule a save-and-update while
   an operation (generation, export, etc.) is still running; the update fires
   automatically when the last operation settles.

2. **Automatic-refresh eligibility** — when the page is fully empty and
   update-required, a single automatic reload is allowed, gated by a
   per-tab/per-revision sessionStorage marker that prevents reload loops.

3. **Chunk/preload error routing** — `ChunkErrorBoundary` catches Vite chunk-load
   and preload failures, routes them through the same eligibility check, and
   stops the old-HTML reload loop by detecting a build-ID mismatch before
   attempting any navigation.

## Design decisions

### Queued update intent

`updateIntent: { kind: "queued" } | { kind: "active" } | null` is a new field
on `WorkspaceState`.  It is deliberately NOT a workspace revision increment
(intent is not workspace state; incrementing would invalidate `evaluateSaveAndUpdate`
snapshot checks).

`queueUpdateIntent()` is a no-op when `operations.length === 0` — the user can
just click the save button directly.  `cancelUpdateIntent()` clears intent
without touching `operations`, `surfaces`, or `freezeInput`.

The `kind: "queued" → "active"` transition fires inside `beginOperation`'s
`end()` closure: after the filtered `newOperations` array is computed, if it
is empty and intent is `{ kind: "queued" }`, the state update atomically sets
`{ kind: "active" }`.  `useQueuedUpdateIntent` (a React hook) subscribes to
the store and fires `runSaveAndUpdate` on that transition.  It clears the intent
before firing to prevent double-fire on re-render.

### Auto-refresh eligibility

`checkAutoRefreshEligible` enforces seven preconditions before allowing an
automatic reload.  The preconditions are checked in the order that short-circuits
fastest (no_update → not_visible → not_safe → pending_recovery → already_reloaded).

The per-tab marker is in `sessionStorage` (NOT `localStorage`), so it is
tab-scoped and reset when the tab closes.  `markAutoReloadAttempted` returns
`false` on any storage exception; callers must check the return value and skip
the reload if marking fails.

### Chunk error routing

`classifyChunkError` identifies Vite/Rollup chunk-load and preload errors by
name and message pattern.  `decideOnChunkError` applies old-HTML detection
first: if `currentBuildId !== releasedBuildId`, it immediately returns
`{ action: "show_error", kind: "old_html" }` regardless of eligibility, because
reloading would serve the same stale HTML again.

`ChunkErrorBoundary` is a class component (required for `getDerivedStateFromError`).
It reads store state directly (no hooks, which are forbidden in class components)
via `.getState()`.  Non-chunk errors are re-thrown in `componentDidCatch` so
outer error boundaries handle them.

### Moving-target protection

The existing `evaluateSaveAndUpdate` already refuses saves when the target or
account changes between snapshot-time and save-time.  The queued intent adds no
new bypass for that check; if the target changes while intent is queued, the
subsequent `runSaveAndUpdate` call will return `ok: false, reason: "target_changed"`.
The caller (ReleaseNotice via `useQueuedUpdateIntent`) does not auto-retry on
that failure.

## Storage keys added

| Key | Storage | Purpose |
|-----|---------|---------|
| `exam_auto_reload_{targetBuildId}_{releaseRevision}` | sessionStorage | Per-tab, per-revision auto-reload marker |

## Changed files

| File | Change |
|------|--------|
| `web/src/lib/workspace/workspaceStore.ts` | Add `updateIntent`, `queueUpdateIntent`, `cancelUpdateIntent`; update `end()` transition; update `resetWorkspaceStoreForTests` |
| `web/src/lib/recovery/useQueuedUpdateIntent.ts` | New: hook that fires `runSaveAndUpdate` on `active` intent |
| `web/src/lib/recovery/autoRefresh.ts` | New: eligibility check + sessionStorage marker |
| `web/src/lib/recovery/chunkErrorGuard.ts` | New: chunk error classifier + reload decision |
| `web/src/components/ChunkErrorBoundary.tsx` | New: React error boundary for chunk/preload errors |
| `web/src/components/ReleaseNotice.tsx` | Add queue/cancel buttons, auto-refresh useEffect |
| `web/src/App.tsx` | Wrap RouterProvider with ChunkErrorBoundary |
| `web/src/i18n/messages.ts` | Add `recovery.queueUpdate`, `recovery.cancelQueuedUpdate`, `recovery.queuedUpdatePending`, `chunk_error.*` keys (EN + ZH) |

## Tests added

All tests pass in three consecutive runs (1445 total).  Tests labeled **unit** are
pure function/store calls with no rendered UI; tests labeled **router-driven** render
real React components (within a `MemoryRouter`), drive visible controls, and assert
what the user sees — they follow the style of `recoveryFlow.test.tsx` and
`GeneratePage.results-recovery.test.tsx`.

| File | Type | Scenarios covered |
|------|------|-------------------|
| `web/src/lib/recovery/queuedIntent.test.ts` | unit | Five tests: queue/cancel/transition store semantics |
| `web/src/lib/recovery/autoRefresh.test.ts` | unit | Eight tests: eligibility check + marker + all denial reasons |
| `web/src/lib/recovery/chunkErrorGuard.test.ts` | unit | Nine tests: classify + decide, including preload errors |
| `web/src/lib/recovery/scheduledUpdate.test.tsx` | unit (4) + router-driven (11) | See table below |

### `scheduledUpdate.test.tsx` scenarios

| Test name | Type | Scenario |
|-----------|------|----------|
| unit: old HTML: decideOnChunkError returns show_error | unit | `currentBuildId ≠ releasedBuildId` → `show_error` / `old_html` |
| unit: missing assets on eligible empty page: decideOnChunkError returns reload | unit | matching build IDs, eligible page → `reload` |
| unit: empty-page auto-reload fires only once per target/revision per tab | unit | marker prevents second `checkAutoRefreshEligible` from returning eligible |
| unit: late result callback: queued intent captures latest workspace after callback settles | unit | `queued → active` store transition when last operation ends |
| router: queue 工作完成後儲存並更新 on busy page, then cancel | router-driven | click queue button, click cancel, end operation → no save, no reload |
| router: late planner and result callbacks after queuing | router-driven | two operations; queue via UI; planner settles (still queued); generation settles → reload |
| router: active ODT export and image conversion delay the update | router-driven | export_odt + export_image; queue; odt settles (still queued); image settles → reload |
| router: target change during read-back | router-driven | `checkNow` changes `requiredBuildId`; `runSaveAndUpdate` returns `target_changed`; no navigation; no localStorage entry |
| router: incompatible recovery reader on target | router-driven | `supportedRecoveryFormats: []`; `runSaveAndUpdate` returns `unsupported_target_reader`; no localStorage entry |
| router: old HTML after a reload — loop stops | router-driven | `ChunkErrorBoundary` with `__BUILD_ID__ ≠ requiredBuildId`; shows error; no reload |
| router: chunk error on eligible empty page — reload triggered once | router-driven | `ChunkErrorBoundary` with matching build IDs, empty page; reload called once |
| router: chunk error on a non-empty page — error shown | router-driven | `ChunkErrorBoundary` with editable surface; shows error; no reload |
| router: empty-page automatic reload fires at most once per target/revision per tab | router-driven | `ReleaseNotice` on eligible empty page; reload once; remount; marker prevents second reload |
| router: automatic reload disabled when marker cannot be stored | router-driven | `sessionStorage.setItem` throws; `markAutoReloadAttempted` returns false; no reload |
| router: no restored flow automatically submits generation or modification | router-driven | `useRecoveryStore.pending` set; `updateIntent` stays null; auto-refresh blocked by `pending_recovery`; no reload |

## Test isolation fix (Problem 2)

`web/src/recoveryFlow.test.tsx` lacked `cleanup()` in its `afterEach` and did not
reset `useReleaseStore` in its `beforeEach`.  Without `cleanup()`, a test that fails
before its own `unmount()` leaves stale React trees mounted across test boundaries.
Those stale `ReleaseNotice` components hold live Zustand subscriptions and can
duplicate DOM elements visible to `screen` queries in subsequent tests — causing the
order-dependent "recovery flow — scenario 2: quota failure > reload not called"
failure observed in full runs.

**Fix applied:**
- Added `cleanup` to the import from `@testing-library/react` in `recoveryFlow.test.tsx`.
- Added `cleanup()` as the first statement of `afterEach` (unmounts all components
  rendered by the test, even if the test asserted early).
- Added an explicit `useReleaseStore.setState({...initial state...})` call in
  `beforeEach` after `resetReleaseDetector()`, so no test inherits
  `status: "update-required"` or other release state from a previous test.

**Product verdict: no product bug.**  In production there is exactly one
`ReleaseNotice` mounted for the lifetime of the tab (in `RootLayout`).  The
auto-refresh effect's deps `[status, requiredBuildId, releaseRevision]` and the
per-revision sessionStorage marker fully prevent reload loops.  The stale-component
hazard is test-specific and is resolved entirely by the isolation fix above.
