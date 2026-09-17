# Build Admission Gate (issue #771) — Research & Design Notes

**Date:** 2026-09-17
**Issue:** paulpengtw/exam-generation#771
**OpenSpec change:** `frontend-build-update-flow` (second user-visible slice)

---

## What was built

A teacher submitting a generation request with an outdated front-end build now
receives a clear rejection before any work is dispatched.

**Server**: `server/generate/release_authority.py` — the backend selects an
`HttpAuthoritySource` from `RELEASE_AUTHORITY_URL` when present, otherwise a
`FileAuthoritySource` from `RELEASE_AUTHORITY_PATH`.  The HTTP source reads the
frontend's `release/policy.json` with a bounded two-second timeout and creates a
fresh async client for every request, so a changed policy is visible on the next
admission check. Invalid URLs, non-2xx responses, invalid JSON, and timeouts are
treated as unavailable. `check_build_admission(header, source)` returns
`JSONResponse|None`:
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

The source is constructed once by `create_app()` and stored in FastAPI app
state, while the check remains injectable for issue #778. Configuration follows
this order:

1. `RELEASE_AUTHORITY_URL` — recommended when frontend and backend are separate
   services (for example, Railway's frontend `/release/policy.json`).
2. `RELEASE_AUTHORITY_PATH` — an optional local fixture path for a deployment
   that intentionally shares the policy file with the backend.
3. No source — generation fails closed with retryable `503 AUTHORITY_UNAVAILABLE`.

If both variables are set, the URL wins. Deployments must set at least one;
the backend no longer assumes that `web/dist` exists in its image. Neither
source caches a positive policy between requests. File reads run off the event
loop, and HTTP reads use an async client with a maximum two-second timeout.

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

- `GET` and `POST /api/generate/preview`
- `POST /api/generate/resolve`
- `GET /api/history`, `/api/history/{record_id}`, and the history download route
- `POST /api/plan-core-questions`
- The 人工審題修正 routes under `/api/generation-records/{record_id}/modifications`
- CLI pipeline calls

---

## Ambiguities / choices made

- **`checking` status after preflight**: treated as pass (proceed). Server's 426 is the backstop.
- **`preparing` state**: treated as 503 `SERVICE_PAUSED`, consistent with `paused`.
- **`required_build_id` in 426 body**: included for client confirmation.
