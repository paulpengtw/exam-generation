# Research: "Stream open failed: HTTP 422" — Terse UI Message and Missing Sentry Alert

**Date:** 2026-07-30
**Branch:** staging

---

## TL;DR (two sentences)

The frontend `onopen` callback hard-codes the string `"Stream open failed: HTTP ${res.status}"` and throws without ever reading the FastAPI response body, so the rich Pydantic `detail` field (`per_question_params[0] has unknown parameter(s): count`) is silently discarded before it can reach the UI.
The resulting `FatalStreamError` is caught by the app's own `.catch(() => {})` handler — a _handled_ rejection — so no `unhandledrejection` fires, no `Sentry.captureException` is called anywhere in the codebase, and the error is invisible to both the frontend and backend Sentry projects.

---

## Question 1 — Why the UI shows only "HTTP 422" and not the Pydantic detail

### 1a. The server sends a rich body

`server/generate/routes.py:172-173` — when `GenerateParams(...)` raises a Pydantic `ValidationError`, the route raises:

```python
raise HTTPException(status_code=422, detail=str(exc)) from exc
```

`str(exc)` for a Pydantic v2 error is a multi-line human-readable string, e.g.:

```
1 validation error for GenerateParams
per_question_params
  Value error, per_question_params[0] has unknown parameter(s): count [type=value_error, ...]
```

FastAPI serialises this as `{"detail": "<that string>"}` in the HTTP response body with `Content-Type: application/json`.

### 1b. The `onopen` callback never reads the body

`web/src/hooks/useGenerate.ts:353-364` — the `fetchEventSource` call passes:

```ts
async onopen(res) {
  if (!res.ok) {
    if (res.status === 401) {
      useAuthStore.getState().logout();
    }
    const msg = res.status === 401
      ? "Session expired — please sign in again"
      : `Stream open failed: HTTP ${res.status}`;   // <-- hardcoded template, no body read
    setErrorMessage(msg);
    setFinishedAt(Date.now());
    throw new FatalStreamError(msg);                 // body never touched
  }
},
```

`res.text()` and `res.json()` are never called. The `{"detail": "..."}` JSON body is available on `res` — the `@microsoft/fetch-event-source` library passes the raw `Response` object — but `onopen` ignores it completely.

### 1c. The library confirms `onopen` may read the body

`web/node_modules/@microsoft/fetch-event-source/lib/esm/fetch.js:51`:

```js
await onopen(response);  // onopen is awaited — async body reads are allowed here
```

The library's own README documents this explicitly in its error-handling example:

> "You have access to the response object if you want to do some custom validation/processing before parsing the event source."
> — `@microsoft/fetch-event-source` README (repo: https://github.com/Azure/fetch-event-source)

The library version pinned in `web/package.json` is `"^2.0.1"`, resolved to `2.0.1` (confirmed in `web/node_modules/@microsoft/fetch-event-source/package.json`).

### 1d. The existing `parseErrorEventData` helper is bypassed

`web/src/hooks/useGenerate.ts:159-176` — `parseErrorEventData` already knows how to parse structured `{"code", "message"}` JSON from SSE error _events_. That helper is used at line 464 (`case "error": setErrorMessage(parseErrorEventData(ev.data ?? ""))`), but the `onopen` non-2xx path at line 353 is entirely separate and never calls it. The `detail` body from the HTTP 422 response is a different channel (HTTP response body vs. SSE event data), and neither `parseErrorEventData` nor any other body-reading code is invoked from `onopen`.

### 1e. Error display path in the UI

The string `msg = "Stream open failed: HTTP 422"` is passed to `setErrorMessage` (line 361), which updates the `errorMessage` state in `useGenerate`. `GeneratePage.tsx:52` reads `errorMessage` from the hook and passes it to `<ProgressLog>` as a prop. `web/src/components/ProgressLog.tsx:80-84` renders it verbatim in a `<pre>` block when `status === "error"`. No further processing or enrichment occurs between `setErrorMessage` and the `<pre>`.

---

## Question 2 — Why Sentry never saw the 422

### 2a. Frontend Sentry configuration

`web/src/sentry.ts:43-56` — `Sentry.init` registers these integrations:

| Integration | Purpose | Relevant here? |
|---|---|---|
| `browserTracingIntegration()` | Performance traces | No |
| `replayIntegration(...)` | Session replay on error | No |
| `consoleLoggingIntegration({ levels: ["warn", "error"] })` | Forward console.error/warn | No — catch block is silent |
| `feedbackIntegration(...)` | User-feedback widget | No |

The `GlobalHandlers` integration is part of `@sentry/react`'s default `defaultIntegrations` and is included automatically. It hooks `window.onerror` and `window.onunhandledrejection`. However, the 422 error never reaches either hook — see 2b.

### 2b. The Promise rejection is caught — it is not "unhandled"

`web/node_modules/@microsoft/fetch-event-source/lib/esm/fetch.js:65-78` — when `onopen` throws, the library's `create()` function catches the error (line 66), calls `onerror?.(err)` (line 69), and if `onerror` rethrows (which `useGenerate.ts:476-481` does), the inner catch re-rejects the outer promise at line 75: `reject(innerErr)`.

`web/src/hooks/useGenerate.ts:482-484`:

```ts
}).catch(() => {
  // Stream terminated (abort or fatal error). State already updated.
});
```

`.catch(() => {})` — the rejection is consumed here. Because the promise has an attached `.catch` handler, the browser never fires `window.onunhandledrejection`, so Sentry's `GlobalHandlers` integration never sees the error. This is a _handled_ rejection by definition.

### 2c. No `captureException` call anywhere in the web codebase

A search across all of `web/src/` for `captureException`, `captureMessage`, `captureError` returns zero results. The only Sentry calls in `web/src/` are:

- `web/src/sentry.ts` — `Sentry.init`, `Sentry.setUser`
- `web/src/hooks/useFeedbackDialog.ts` — `Sentry.getFeedback()`, `Sentry.getReplay()`
- `web/src/utils/figureFallbackMetric.ts` — `Sentry.metrics.count(...)` (a custom metric, not error capture)

None of these capture the `FatalStreamError` or any stream-failure error.

### 2d. `consoleLoggingIntegration` does not help because the catch is silent

The `consoleLoggingIntegration({ levels: ["warn", "error"] })` would forward `console.error(...)` calls to Sentry, but the `.catch(() => {})` at line 482 is a no-op — there is no `console.error(err)` or `console.warn` inside it. The error is swallowed without any console output.

### 2e. Server-side Sentry also does not report 422s

`server/observability.py:67-71` initialises the backend Sentry SDK with:

```python
FastApiIntegration(),
StarletteIntegration(),
```

Neither is given a `failed_request_status_codes` parameter. The default value for the Starlette integration (which FastAPI sits on top of) is `{500, 502, 503, 504}` — exclusively 5xx status codes.
Source: https://docs.sentry.io/platforms/python/integrations/starlette/ ("failed_request_status_codes: A set of integers or integer ranges that will be reported to Sentry. Defaults to `{500, 502, 503, 504}`.")

A 422 `HTTPException` is handled entirely by FastAPI's built-in exception handler, which serialises it as a JSON response and returns it to the client. This is a _normal_ HTTP response path, not an unhandled Python exception, so neither `StarletteIntegration` nor any other SDK hook ever sees it. The route function raises `HTTPException(422, ...)` and FastAPI catches it at the ASGI middleware layer — the Sentry SDK wraps that layer but only reports it when the status code is in `failed_request_status_codes`.

---

## Recommendations (no code changes — document only)

### R1 — Read the HTTP response body in `onopen`

**Evidence:** `onopen` is awaited (library source line 51), so `await res.json()` is valid there. FastAPI sends `{"detail": "..."}` as the body.

**Minimal change:** in `web/src/hooks/useGenerate.ts:354-363`, after `if (!res.ok)`, add:

```ts
let detail: string | null = null;
try {
  const body = await res.json() as { detail?: unknown };
  if (typeof body.detail === "string" && body.detail.length > 0) {
    detail = body.detail;
  }
} catch { /* not JSON — ignore */ }
const msg = res.status === 401
  ? "Session expired — please sign in again"
  : detail ?? `Stream open failed: HTTP ${res.status}`;
```

This surfaces `per_question_params[0] has unknown parameter(s): count` (or any other detail) directly to the user with zero extra infrastructure.

### R2 — Add `Sentry.captureException` in the stream-failure catch

**Evidence:** `.catch(() => {})` at `useGenerate.ts:482` swallows the error; no Sentry capture exists anywhere in `web/src/`. A single `captureException` or `captureMessage` here would make 422 and all other non-abort stream failures visible in Sentry.

**Minimal change:** replace the no-op catch with:

```ts
}).catch((err: unknown) => {
  if (err instanceof Error && err.name !== "AbortError") {
    Sentry.captureException(err, { tags: { source: "fetchEventSource" } });
  }
  // State already updated via setErrorMessage above.
});
```

Import `* as Sentry from "@sentry/react"` (already used in `useFeedbackDialog.ts` and `figureFallbackMetric.ts`). Guard on `isSentryEnabled()` if needed for parity with the rest of the codebase.

### R3 — Optionally widen `failed_request_status_codes` server-side

**Evidence:** `server/observability.py:67-71` uses default `failed_request_status_codes`. The Sentry FastAPI docs (https://docs.sentry.io/platforms/python/integrations/fastapi/) show that passing `failed_request_status_codes={422, 500, 502, 503, 504}` to `FastApiIntegration()` / `StarletteIntegration()` will capture 422 responses as Sentry issues.

**Trade-off:** 422s generated by _valid_ client errors (user passes bad params intentionally or form validation fails) would create noise. A targeted alternative is to add `logger.warning("generate endpoint 422: %s", exc)` inside the `except ValidationError` block; `LoggingIntegration(level=logging.WARNING, ...)` already forwards warnings to Sentry (see `server/observability.py:72-77`), so this gives visibility without permanently widening the 422 net. The log message must not include `exc` detail that contains user-supplied content, per ADR 0004.

### R4 — Consider a typed error object in the body-read path (cosmetic)

The existing `parseErrorEventData` helper (`useGenerate.ts:159-176`) already handles `{"code", "message"}` SSE events. If the `onopen` body-reading from R1 is added, it would be cleanest to use the same shape — i.e., prefer `.detail` from FastAPI's standard JSON, falling back to `.message` for consistency. No structural change to the server is needed; FastAPI already sends `.detail`.

---

## Load-bearing Citations

| # | Claim | Citation |
|---|---|---|
| 1 | `onopen` never reads `res.text()` / `res.json()` | `web/src/hooks/useGenerate.ts:353-364` |
| 2 | Library awaits `onopen` — body reads are valid there | `web/node_modules/@microsoft/fetch-event-source/lib/esm/fetch.js:51`; README error-handling example |
| 3 | `.catch(() => {})` makes the rejection handled — `GlobalHandlers` never fires | `web/src/hooks/useGenerate.ts:482-484`; library source `fetch.js:66-77` |
| 4 | No `captureException` call exists anywhere in web/src/ | grep result: zero matches for `captureException`, `captureMessage`, `captureError` in `web/src/` |
| 5 | Server Sentry default is 5xx only; 422 is a normal handled HTTP response | `server/observability.py:67-71` (no `failed_request_status_codes`); Sentry docs https://docs.sentry.io/platforms/python/integrations/starlette/ |
