# Build Admission Gate (issue #771) — Research & Design Notes

**Date:** 2026-09-17
**Issue:** paulpengtw/exam-generation#771
**OpenSpec change:** `frontend-build-update-flow` (second user-visible slice)

---

## What was built

A teacher submitting a generation request with an outdated front-end build now
receives a clear rejection before any work is dispatched.

**Server**: `server/generate/release_authority.py` — `FileAuthoritySource` reads
`web/dist/release/policy.json` (the deterministic fixture emitted by `buildIdentityPlugin`
at `npm run build`).  `check_build_admission(header, source)` returns `JSONResponse|None`:
- Missing or outdated `X-Frontend-Build-ID` → **426** `CLIENT_UPDATE_REQUIRED` + `required_build_id`
- Authority file unavailable or unknown schema → **503** `AUTHORITY_UNAVAILABLE`
- Authority in `paused`/`preparing` state → **503** `SERVICE_PAUSED`
- Matching header → `None` (pass)

**Frontend**: `useGenerate.ts` runs `await useReleaseStore.getState().checkNow()` before
every `fetchEventSource` call.  If status is `update-required`, `paused`, or `unavailable`,
the admission is immediately rejected with a localized message and **no HTTP request** is
sent.  The `X-Frontend-Build-ID: __BUILD_ID__` header is attached to the stream request.

---

## Admission check order

```
1. FastAPI `get_current_user` dependency   — authentication (always first)
2. `stream_version` 426 gate              — existing, from #742
3. `X-Frontend-Build-ID` header check     — 426 (missing/outdated) | 503 (authority)
4. `_check_generation_admission`          — model, effort, image, provider
5. `_require_complete_generate_params`    — full resolve + 全量預抽 validation
```

**Why auth first?** The `get_current_user` FastAPI dependency runs before any route body
code, so it cannot be bypassed.

**Why build-ID before model/provider checks?** The issue requires "zero work dispatched"
on rejection.

---

## Authority source

`FileAuthoritySource` reads `ServerConfig.release_authority_path` (env:
`RELEASE_AUTHORITY_PATH`), defaulting to `web/dist/release/policy.json`.

Issue #778 swaps in a live controller by implementing `AuthoritySource` (a `Protocol`)
and wiring it in without changing `check_build_admission`.

---

## Frontend results preservation

`setResults([])`, `setDisplayResults([])`, `setEvidence(null)` were moved from the
beginning of `generate()` to the `started` event handlers.  This ensures:
- Preflight failures leave existing output intact (issue requirement).
- 426/503 pre-stream errors leave existing output intact.
- Results are cleared only when the server confirms admission (`started` event).

---

## Excluded endpoints

Build-ID check is NOT required for:
- `GET /api/generate/preview` and `POST /api/generate/preview`
- `GET /api/resolve` and `POST /api/resolve`
- `GET /api/generations` (History reads)
- `POST /api/generate/plan-core-questions`
- All modification API routes (`/api/generate/modification/*`)
- CLI pipeline calls

---

## Ambiguities / choices made

- **`checking` status after preflight**: treated as pass (proceed). Server's 426 is the backstop.
- **`preparing` state**: treated as 503 `SERVICE_PAUSED`, consistent with `paused`.
- **`required_build_id` in 426 body**: included for client confirmation.
