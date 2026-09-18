# Release Version Detection (issue #770) — Research & Design Notes

**Date:** 2026-09-15
**Issue:** paulpengtw/exam-generation#770
**OpenSpec change:** `frontend-build-update-flow` (first user-visible slice)
**Implemented by:** Claude Fable 5.1 (codex-unavailable fallback)

---

## Build-ID derivation

The build ID is a SHA-256 hex string (64 chars) computed over:

```
commit_sha + '\0' + JSON.stringify({
  VITE_ENVIRONMENT,
  VITE_IS_STAGING,
  VITE_SENTRY_DSN,
  VITE_SENTRY_RELEASE
})
```

Keys are sorted alphabetically and `undefined` values are preserved as-is in the canonical JSON, so different public configurations (e.g. staging vs. production) always produce different IDs even when the commit SHA is identical.

In non-production (`mode !== 'production'`) mode a `dev-<uuid-prefix>` string is returned — stable within a process, different across restarts.

In production mode, a missing or placeholder commit (`unknown`, `dev`, `local`, `HEAD`, empty) throws a descriptive error naming the fix (`RAILWAY_GIT_COMMIT_SHA`, `RENDER_GIT_COMMIT`, `GIT_COMMIT_SHA`, or `BUILD_ID`). If `BUILD_ID` env is supplied it is used verbatim after the same placeholder check.

Commit SHA sources (priority order):
1. `RAILWAY_GIT_COMMIT_SHA`
2. `RENDER_GIT_COMMIT`
3. `GIT_COMMIT_SHA`
4. `git rev-parse HEAD` (if available)
5. `"unknown"` (causes a throw in production mode)

---

## Fixture route

The `buildIdentityPlugin()` emits two static assets at build time:

| File | Schema | Purpose |
|---|---|---|
| `dist/build-meta.json` | `exam-generation.build-meta/1` | Build provenance: build_id, environment, commit, built_at |
| `dist/release/policy.json` | `exam-generation.release-policy/1` | Deterministic authority fixture: maps released_build_id to this artifact |

The fixture `dist/release/policy.json` starts with `admission: 'open'` and `release_revision: Number(RELEASE_REVISION ?? 1)`, matching the running artifact. A real release controller (future #778) would update this file after performing a rolling deploy; until then, a freshly deployed artifact always considers itself "current".

---

## Trigger matrix

| Event | Trigger |
|---|---|
| Component mount (initial load) | `useEffect` on empty deps — `checkNow()` immediately |
| Browser history restoration (`pageshow`) | `window 'pageshow'` listener |
| History navigation (`popstate`) | `window 'popstate'` listener |
| Network reconnection | `window 'online'` listener |
| Return to visibility | `document 'visibilitychange'` → visible |
| Periodic poll | `setInterval(60_000)` gated by `document.visibilityState === 'visible'` |

All triggers call `checkNow()` which coalesces concurrent calls. The 60 s interval does **not** fire while the document is hidden (sleeping tab).

---

## Cache-header table (both nginx configs)

| Path | Cache-Control | Fallback |
|---|---|---|
| `/release/policy.json` | `no-store` | `try_files $uri =404` |
| `/build-meta.json` | `no-store` | `try_files $uri =404` |
| `/assets/` | `public, max-age=31536000, immutable` | `try_files $uri =404` (NO index.html fallback) |
| `/index.html` | `no-cache` | `try_files $uri =404` |
| `/` (SPA fallback) | `no-cache` | `try_files $uri $uri/ /index.html` |
| `/auth/`, `/api/`, `/health` | (proxy, no header change) | proxy_pass |

---

## Test names proving each acceptance item

| Acceptance item | Test file | Test name / description |
|---|---|---|
| (1) Immutable build ID per artifact | `buildIdentity.test.ts` | "same commit + different public config -> different ids" |
| (1) Placeholder throws in production | `buildIdentity.test.ts` | "production + placeholder commit throws with a message naming the fix" |
| (1) BUILD_ID override | `buildIdentity.test.ts` | "explicit BUILD_ID env wins over commit computation" |
| (1) Plugin emits matching build_id | `buildIdentity.test.ts` | "generateBundle emits build-meta.json and release/policy.json with matching build_id" |
| (2) Policy schema + reader | `policy.test.ts` | "parses a valid policy document", "rejects an unknown schema", "rejects a document with missing required fields" |
| (3) Equality-only comparison | `policy.test.ts` | "commit-hash ordering is never consulted — only equality", "never treats a Sentry-release-looking string as equal to a different build ID" |
| (3) Rollback | `policy.test.ts` | "rollback: higher release_revision but same (earlier) build ID compares current for A" |
| (4) Coalescing | `useReleaseStatus.test.tsx` | "coalesces concurrent triggers — two triggers produce exactly one fetch" |
| (4) 5 s timeout | `useReleaseStatus.test.tsx` | "5 s timeout -> unavailable with lastFailure=timeout" |
| (4) Reversed responses | `useReleaseStatus.test.tsx` | "reversed responses — second request wins when first resolves later" |
| (4) Visibility gating | `useReleaseStatus.test.tsx` | "visibility gating — 60s interval only fires while document is hidden" |
| (5) Persistent localized states | `ReleaseNotice.test.tsx` | all state-specific tests + locale switch |
| (5) Keyboard accessible | `ReleaseNotice.test.tsx` | "check-again button is keyboard operable (click)" |
| (5) Focus preserved | `ReleaseNotice.test.tsx` | "focus is not moved by state changes" |
| (5) Reduced-motion | `ReleaseNotice.test.tsx` | "reduced-motion: no animation classes when prefers-reduced-motion matches" |
| (6) Sticky requirement | `useReleaseStatus.test.tsx` | "sticky requirement — known update-required is retained after a later failure" |
| (6) No reload | `useReleaseStatus.test.tsx` | "location.reload is never called" |
| (7) Cache headers static assertion | `nginxCachePolicy.test.ts` | all 26 per-config tests |
| (8) A -> B -> rollback | `releaseFlow.demo.test.tsx` | "Scenario 1: A -> B -> rollback A" |
| (8) Sleeping tab | `releaseFlow.demo.test.tsx` | "Scenario 2: sleeping tab — 2 h hidden" |
| (8) Reversed responses demo | `releaseFlow.demo.test.tsx` | "Scenario 3: reversed responses" |
| (8) Work is kept, no reload | `releaseFlow.demo.test.tsx` | "update-required notice names that work is kept (not a reload)" |
| (8) Paused state | `releaseFlow.demo.test.tsx` | "paused state is served only when metadata and notice agree" |

---

## Explicit limits

These items are explicitly **not** implemented by this ticket:

- **No live release controller** — `dist/release/policy.json` is a static fixture emitted at build time. The live controller is #778.
- **No generation enforcement** — #771 (enforcement by build ID).
- **No save-and-update** — #772+.
- **No scheduling / auto-reload** — #777.
- **No independent production pause switch** — the fixture always emits `admission: 'open'`.
- **nginx headers asserted statically** — nginx and Docker are not available in this container; assertions run as string checks on the config files.
- **No service worker** — background sync is out of scope.
