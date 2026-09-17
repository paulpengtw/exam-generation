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

| File | Type | Description |
|------|------|-------------|
| `web/src/lib/recovery/queuedIntent.test.ts` | unit | Five tests for queue/cancel/transition semantics |
| `web/src/lib/recovery/autoRefresh.test.ts` | unit | Eight tests for eligibility check + marker |
| `web/src/lib/recovery/chunkErrorGuard.test.ts` | unit | Nine tests for classify + decide |
| `web/src/lib/recovery/scheduledUpdate.test.tsx` | unit | Combined unit tests for chunk routing, marker deduplication, queued intent |
