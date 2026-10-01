# Research: LLM Error Surfacing and Key Rotation

**Date:** 2026-10-01
**HEAD SHA:** dd9e6b82b5df874bb958cc6a778d41ab37c4a776
**Repo:** https://github.com/paulpengtw/exam-generation/tree/dd9e6b82b5df874bb958cc6a778d41ab37c4a776

> **Scope:** Read-only. No code changes.
> Two problems motivate this note:
> 1. When an LLM provider call fails, the frontend shows a generic, non-actionable message.
> 2. When a key runs out of tokens/credit/quota there is no way to rotate to another key or model.

---

## Section A — Current behaviour: end-to-end failure trace

### A.1 The full propagation path

1. **Provider raises an SDK exception** inside `LLMClient._call()` at
   [`src/llm_client.py` lines 795–805](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L795-L805).

   ```python
   except Exception as exc:
       if self._observer and call_scope is not None:
           self._emit_call_event(
               "llm_failure",
               call_scope,
               purpose=purpose,
               agent=agent,
               model=model,
               error_type=type(exc).__name__,   # ← class name only
           )
       raise                                    # ← re-raises; nothing is classified
   ```

   The `llm_failure` observer event carries `error_type=type(exc).__name__` — e.g.
   `"RateLimitError"`, `"OverloadedError"`, `"APITimeoutError"` — but the exception
   body (HTTP status code, `error.type` string such as `"rate_limit_error"`,
   `error.details.error_code` such as `"enforced_spend_limit_reached"`, provider
   error message, `retry-after` header value) is not captured anywhere.

2. **Worker `except Exception` in `service.py`** catches the re-raised exception at
   [`server/generate/service.py` lines 896–900](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/service.py#L896-L900):

   ```python
   payload=build_sse_error(
       "generation_failed",
       f"Question generation failed ({type(exc).__name__})",
   ),
   ```

   Again only the Python class name survives. The `build_sse_error` helper
   ([`server/generate/models.py` lines 15–31](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/models.py#L15-L31))
   returns `{"code": "generation_failed", "message": "Question generation failed
   (RateLimitError)"}`.

3. **SSE `error` event** is received by the frontend
   [`web/src/hooks/useGenerate.ts` lines 1043–1050](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/web/src/hooks/useGenerate.ts#L1043-L1050) _(file has uncommitted local changes)_:

   ```typescript
   case "error": {
     const errPayload = payload as { message?: string; code?: string } | string | null;
     let msg = "Unknown error";
     if (typeof errPayload === "string") msg = errPayload;
     else if (errPayload && typeof errPayload === "object" && typeof errPayload.message === "string") {
       msg = errPayload.message;           // ← raw backend string, no localization
     }
     setErrorMessage(msg);
   ```

4. **`errorMessage` state** is rendered in `GenerationStatusBar` / `QuestionCard`
   under a generic "Error"/"錯誤" label
   ([`web/src/i18n/messages.ts` `statusbar.error`](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/web/src/i18n/messages.ts) _(uncommitted local changes)_).
   There are **no i18n keys** for `generation_failed`, `rate_limit`,
   `quota_exceeded`, `overloaded`, `provider_error`, or any provider-specific
   condition — confirmed by `grep -n
   "generation_failed\|rate_limit\|quota\|overloaded\|provider_error"
   web/src/i18n/messages.ts` returning no results.

**Pre-stream errors (non-OK HTTP before first SSE byte)** are handled separately
in `onopen` at
[`web/src/hooks/useGenerate.ts` lines 1361–1406](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/web/src/hooks/useGenerate.ts#L1361-L1406):
`401` → hardcoded English "Session expired"; other statuses → `"Stream open
failed: HTTP {res.status}"` plus whatever `formatHttpErrorDetail()` extracts from
`.detail`. This path handles 426/503 (build admission and authority source errors)
adequately but not provider runtime errors (those arrive as SSE events after the
stream opens).

**`generate_with_tools()` bypass:** The Anthropic web-search path
(`fact_check_question`) dispatches directly to `self.client.messages.create()` at
[`src/llm_client.py` line 1308](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L1308),
bypassing `_call()`. The same `except Exception` → `llm_failure` + re-raise
pattern is repeated there at lines 1365–1370.

### A.2 Failure-class × what backend emits × what frontend displays

| Failure class | Python exc class | HTTP status | Backend SSE `code` | Backend SSE `message` | Frontend display |
|---|---|---|---|---|---|
| Per-minute rate limit (Anthropic) | `RateLimitError` | 429 | `generation_failed` | `"Question generation failed (RateLimitError)"` | same string |
| **Monthly spend-cap exhausted (Anthropic)** | `RateLimitError` | **429** | `generation_failed` | `"Question generation failed (RateLimitError)"` | **indistinguishable from above** |
| **Credit balance / billing issue (Anthropic)** | `AuthenticationError` or `APIError` | **402** | `generation_failed` | `"Question generation failed (...)"` | no billing guidance |
| Overloaded (Anthropic) | `OverloadedError` | 529 | `generation_failed` | `"Question generation failed (OverloadedError)"` | same string |
| Auth failure | `AuthenticationError` | 401 | `generation_failed` | `"Question generation failed (AuthenticationError)"` | same string |
| Permission denied | `PermissionDeniedError` | 403 | `generation_failed` | `"Question generation failed (PermissionDeniedError)"` | same string |
| Request too large | `RequestTooLargeError` | 413 | `generation_failed` | `"Question generation failed (RequestTooLargeError)"` | same string |
| Service unavailable | `ServiceUnavailableError` | 503 | `generation_failed` | `"Question generation failed (ServiceUnavailableError)"` | same string |
| Timeout | `APITimeoutError` | — | `generation_failed` | `"Question generation failed (APITimeoutError)"` | same string |
| Connection error | `APIConnectionError` | — | `generation_failed` | `"Question generation failed (APIConnectionError)"` | same string |
| Per-minute rate limit (OpenAI/Gemini) | `RateLimitError` | 429 | `generation_failed` | `"Question generation failed (RateLimitError)"` | same string |
| **Daily quota exhausted (Gemini native)** | `RateLimitError` | **429** | `generation_failed` | `"Question generation failed (RateLimitError)"` | **indistinguishable from per-minute limit** |
| **Credit depleted (Gemini)** | `BadRequestError` or `RateLimitError` | **402** | `generation_failed` | `"Question generation failed (...)"` | no billing guidance |
| **Org quota / spend limit (OpenAI)** | `RateLimitError` | **429** | `generation_failed` | `"Question generation failed (RateLimitError)"` | **indistinguishable from per-minute limit** |
| Internal server error | `InternalServerError` | 500+ | `generation_failed` | `"Question generation failed (InternalServerError)"` | same string |
| Content filter (OpenAI) | `ContentFilterFinishReasonError` | — | `generation_failed` | `"Question generation failed (ContentFilterFinishReasonError)"` | same string |
| Missing API key (pre-flight) | `ValueError` (caught) | **HTTP 422** | — | HTTP 422 detail via `formatHttpErrorDetail` | `"Stream open failed: HTTP 422 …"` — slightly better |
| Stream-level exception (non-worker) | any | — | `stream_failed` | `"Stream error ({type(exc).__name__})"` | raw string |

**Key losses at each hop:**
- `_call()` loses: HTTP status code, `error.type`, `error.details.error_code`
  (which distinguishes spend cap from rate limit for Anthropic), provider-supplied
  human message, `retry-after` / `retry-after-ms` header value.
- Worker `except Exception` further loses: which worker index failed, which
  LLM tier (plan / execute / verify) was the caller.
- Frontend: receives code=`"generation_failed"` but ignores it; displays the raw
  message string with no i18n adaptation.

---

## Section B — Provider SDK and documentation facts

SDK versions (from `uv.lock` at HEAD):
- **anthropic** `0.104.1`
- **openai** `2.30.0`

### B.1 Anthropic

#### B.1.a SDK exception classes

Source: anthropic 0.104.1 — `src/anthropic/_exceptions.py` (upstream:
[anthropics/anthropic-sdk-python at v0.104.1](https://github.com/anthropics/anthropic-sdk-python/blob/v0.104.1/src/anthropic/_exceptions.py)):

| Class | HTTP status | `error.type` string |
|---|---|---|
| `AuthenticationError` | 401 | `authentication_error` |
| `PermissionDeniedError` | 403 | `permission_error` |
| `NotFoundError` | 404 | `not_found_error` |
| `RateLimitError` | 429 | `rate_limit_error` |
| `RequestTooLargeError` | 413 | `request_too_large` |
| `UnprocessableEntityError` | 422 | `invalid_request_error` |
| `InternalServerError` | 5xx (excl. 529) | `api_error` |
| `ServiceUnavailableError` | 503 | `api_error` |
| `OverloadedError` | **529** | `overloaded_error` |
| `APITimeoutError` | — | — |
| `APIConnectionError` | — | — |

`APIStatusError.type` is extracted from `body["error"]["type"]`.
`APIStatusError.request_id` is available from the `request-id` response header.

#### B.1.b Official API documentation

Source: Anthropic API Errors page (https://platform.claude.com/docs/en/api/errors)
and Rate Limits page (https://platform.claude.com/docs/en/api/rate-limits).

**402 `billing_error`:** A billing/payment issue (expired card, etc.). Distinct
from credit-balance depletion.

**429 `rate_limit_error` — TWO distinct sub-cases, same status and type:**

(a) **Per-minute rate limit:** Has `retry-after` header; `anthropic-ratelimit-*`
headers indicate remaining capacity. The SDK retries automatically up to 2 times,
honoring `retry-after`. Transient; retrying after the window passes succeeds.

(b) **Monthly spend-cap exhausted:** Same 429, same `rate_limit_error` type, but
**`error.details.error_code == "enforced_spend_limit_reached"`** and **no
`retry-after` header.** Example response body (from official docs):
```json
{
  "type": "error",
  "error": {
    "type": "rate_limit_error",
    "message": "You have reached your API usage limits: your organization has crossed its monthly API usage threshold...",
    "details": { "error_code": "enforced_spend_limit_reached" }
  }
}
```
The SDK still retries this twice (its `_should_retry()` sees 429 and returns
`True`), but both retries fail immediately — wasted latency. Retrying succeeds
only when access resumes at the next calendar month or after an org tier upgrade.

**User-set spend limit (below tier cap):** Returns HTTP **400** `invalid_request_error`
(not 429), message begins "You have reached your specified API usage limits".

**`anthropic-ratelimit-*` response headers** (present on per-minute 429 and on
successful responses):
```
anthropic-ratelimit-requests-limit / -remaining / -reset
anthropic-ratelimit-tokens-limit / -remaining / -reset
anthropic-ratelimit-input-tokens-limit / -remaining / -reset
anthropic-ratelimit-output-tokens-limit / -remaining / -reset
retry-after                          (seconds; absent on spend-cap 429)
```

**Rate limit scope:** "Limits are set at the organization level."
([Rate Limits page](https://platform.claude.com/docs/en/api/rate-limits))
Multiple API keys from the same org therefore share the same rate limit bucket.
Per-key rotation within one org does not help with rate limits.

#### B.1.c SDK auto-retry

Source: `src/anthropic/_base_client.py` `_should_retry()` (upstream:
[anthropics/anthropic-sdk-python at v0.104.1](https://github.com/anthropics/anthropic-sdk-python/blob/v0.104.1/src/anthropic/_base_client.py));
`DEFAULT_MAX_RETRIES = 2` in `src/anthropic/_constants.py` (upstream:
[anthropics/anthropic-sdk-python at v0.104.1](https://github.com/anthropics/anthropic-sdk-python/blob/v0.104.1/src/anthropic/_constants.py)).

The SDK retries on: `x-should-retry: true` header, status 408, 409, 429 (all
variants), and >= 500. `OverloadedError` (529) is retried under the `>= 500`
branch. **The SDK does not distinguish spend-cap 429 from rate-limit 429 —
both are retried twice before the application sees the exception.**

The application passes **no `max_retries` override** to the `Anthropic(...)` constructor
([`src/llm_client.py` lines 428–442](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L428-L442)),
so the SDK default of 2 retries applies for all Anthropic calls.

---

### B.2 OpenAI SDK (used also for Gemini via OpenAI-compat endpoint)

#### B.2.a SDK exception classes

Source: openai 2.30.0 — `src/openai/_exceptions.py` (upstream:
[openai/openai-python at v2.30.0](https://github.com/openai/openai-python/blob/v2.30.0/src/openai/_exceptions.py)):

| Class | HTTP status | Notes |
|---|---|---|
| `AuthenticationError` | 401 | |
| `PermissionDeniedError` | 403 | |
| `RateLimitError` | 429 | covers all 429s including quota |
| `BadRequestError` | 400 | |
| `InternalServerError` | 5xx | no dedicated 529 class |
| `APITimeoutError` | — | |
| `APIConnectionError` | — | |
| `ContentFilterFinishReasonError` | — | finish_reason-based |
| `LengthFinishReasonError` | — | finish_reason-based |

`.code` from `body["code"]` (or `body["error"]["code"]`); `.type` from `body["type"]`.

#### B.2.b Official OpenAI error documentation

Source: OpenAI error codes guide (https://developers.openai.com/api/docs/guides/error-codes).

**429 sub-cases distinguished by `error.code`:**

| `error.code` | Meaning | Recoverable by retrying? |
|---|---|---|
| `slow_down` (type `rate_limit_error`) | Request rate too high | Yes, after backoff |
| `credit_balance_exhausted` (type may be `insufficient_quota`) | Hard quota / credit gone | No, requires top-up |
| `organization_spend_limit_exceeded` | Org monthly limit | No, until next period |
| `project_spend_limit_exceeded` | Project-level limit | No, until next period |
| `organization_usage_limit_exceeded` | OpenAI-assigned limit | No |

The broader `error.type` can still be `insufficient_quota` for billing errors.
**`error.code` is the discriminant for spend/quota vs rate-limit.**

The SDK's `_should_retry()` (upstream:
[openai/openai-python at v2.30.0](https://github.com/openai/openai-python/blob/v2.30.0/src/openai/_base_client.py))
retries all 429s identically — including hard quota errors. As with Anthropic,
both SDK retries on `credit_balance_exhausted` are wasted latency.

#### B.2.c Gemini via OpenAI-compatibility endpoint

Source: Gemini API errors reference (https://ai.google.dev/gemini-api/docs/api-errors).

**Native Gemini API** 429 sub-cases distinguished by `error.code` in the
`{"error": {"code": "...", "message": "..."}}` body:

| `error.code` | Meaning |
|---|---|
| `rate_limit_exceeded` | Per-minute or per-second request/token limit |
| `quota_exceeded` | **Daily quota** — not retryable by waiting a minute |
| `too_many_requests` | Short burst limit |

**402 `payment_required`:** Prepay credit balance depleted — not a rate limit.

**Gemini rate limit scope:** Limits are applied per project, not per API key —
source: https://ai.google.dev/gemini-api/docs/rate-limits ("Rate limits are
applied per project, not per API key." and "Limits vary depending on the specific
model being used."). Multiple keys from the same GCP project share the same quota
bucket; multi-key rotation only helps if the keys are from different GCP projects.

**Gemini daily quota reset:** RPD (Requests per Day) quotas reset at midnight
Pacific time (source: https://ai.google.dev/gemini-api/docs/rate-limits). A daily
`quota_exceeded` 429 is therefore recoverable by waiting until midnight PT, using
a key from a different GCP project, or switching to a different model (models have
separate quota buckets).

**Gemini OpenAI-compatibility endpoint error body shape:** The official
compatibility docs do not document the error body format for 429 responses.
It is unclear whether the compat endpoint forwards the native Gemini
`{"error": {"code": "quota_exceeded"}}` body or wraps it in an OpenAI-shaped
`{"error": {"type": "...", "code": "..."}}`. The native `quota_exceeded` /
`rate_limit_exceeded` distinction **may not survive** the compat shim.
**How to verify:** capture a 429 response from a quota-exhausted Gemini compat
call from the existing `llm_exchanges` table (`request_body`, `response_body`
columns) or from server logs, and inspect the raw body shape.

---

### B.3 Provider × failure class reference table

| Provider | Failure class | HTTP status | `error.type` / `error.code` | Distinguishing field | SDK auto-retries (2×)? | `retry-after` present? |
|---|---|---|---|---|---|---|
| Anthropic | Per-minute rate limit | 429 | type=`rate_limit_error` | **`details.error_code` absent** | Yes (wasted on quota) | Yes |
| Anthropic | **Monthly spend cap exhausted** | **429** | type=`rate_limit_error` | **`details.error_code == "enforced_spend_limit_reached"`** | Yes (wasted) | **No** |
| Anthropic | User-set spend limit | **400** | type=`invalid_request_error` | message prefix "specified API usage limits" | No (not 429 or >=500) | No |
| Anthropic | Billing issue (bad card) | 402 | type=`billing_error` | status 402 | No | No |
| Anthropic | Overloaded | 529 | type=`overloaded_error` | status 529 | Yes (transient) | Yes |
| Anthropic | Auth error | 401 | type=`authentication_error` | status 401 | No | No |
| OpenAI | Per-minute rate limit | 429 | code=`slow_down`, type=`rate_limit_error` | `error.code` | Yes (useful) | Yes (`Retry-After`) |
| OpenAI | **Credit / quota exhausted** | **429** | code=`credit_balance_exhausted`, type may be `insufficient_quota` | **`error.code`** | Yes (wasted) | No/unspecified |
| OpenAI | Org spend limit | **429** | code=`organization_spend_limit_exceeded` | `error.code` | Yes (wasted) | No |
| OpenAI | Auth error | 401 | type=`authentication_error` | status 401 | No | No |
| Gemini (native) | Per-minute rate limit | 429 | code=`rate_limit_exceeded` | `error.code` | Yes (useful) | unspecified |
| Gemini (native) | **Daily quota exhausted** | **429** | code=`quota_exceeded` | **`error.code`** — resets midnight PT | Yes (wasted) | unspecified |
| Gemini (native) | Credit depleted | **402** | code=`payment_required` | status 402 | No | No |
| Gemini (compat) | Per-minute rate limit | 429 | **body shape unclear — see B.2.c** | unknown | Yes | unknown |
| Gemini (compat) | **Daily quota exhausted** | **429** | **body shape unclear — see B.2.c** | **unknown** | Yes (wasted) | unknown |

**Critical application implication:** The application currently cannot distinguish
"spend cap / daily quota exhausted" (non-retryable, requires human action) from
"per-minute rate limit" (retryable, wait seconds). Both reach the frontend as
identical `"Question generation failed (RateLimitError)"`. For Anthropic,
`error.details.error_code == "enforced_spend_limit_reached"` is the programmatic
discriminant. For OpenAI, `error.code`. For Gemini via compat, the discriminant
is unknown until the body shape is confirmed.

---

## Section C — Options with trade-offs

### C.1 Option 1 — Enrich error messages without changing retry/rotation logic (minimal fix)

Capture `exc.status_code`, `exc.type` / `exc.code`, and `exc.body` in `_call()`
before re-raising, and thread them into the SSE `error` payload as additional
fields (`http_status`, `provider_error_type`, `provider_error_code`).

In the worker `except Exception` in `service.py`, inspect the exception type and
the captured `provider_error_code` to choose a more specific SSE `code` string:

```
RateLimitError + error_code=="enforced_spend_limit_reached" → code="quota_exhausted"
RateLimitError (no distinguishing field)                    → code="rate_limit"
OverloadedError                                             → code="overloaded"
APITimeoutError                                             → code="timeout"
AuthenticationError                                         → code="auth_error"
ContentFilterFinishReasonError                              → code="content_filter"
(default)                                                   → code="generation_failed"
```

On the frontend, add i18n keys and display the localized string, including
actionable guidance for `quota_exhausted` ("API usage limit reached — contact
your administrator") vs `rate_limit` ("Too many requests — please try again
shortly").

**Trade-offs:**
- Minimal surface area; no new infrastructure.
- Does not address the root cause (no retry / no key rotation).
- `retry-after` value could be forwarded to the frontend to show "try again in N
  seconds" but the current SSE protocol has no retry-after field.
- Covers both `_call()` and `generate_with_tools()` paths.
- `messages.ts` and `useGenerate.ts` already have uncommitted changes on the
  current branch; small conflict risk.

**Recommendation: implement as a near-term fix regardless of which rotation
option is chosen.**

### C.2 Option 2 — Application-level retry for transient errors (no key rotation)

Wrap the call inside `_call()` with an explicit retry loop before the SDK gets a
chance to see the exception. Alternatively, increase the SDK `max_retries`
parameter on each client constructor.

The SDK already retries 429 and 5xx twice. Marginal value is limited for plain
429 (quota window is per minute; retrying quickly still hits the same window) and
moderate for 529/OverloadedError (where a short backoff helps).

**Important: skip application-level retry for quota-exhausted errors.** With
Option 1's structured error codes in place, the application can distinguish
`enforced_spend_limit_reached` (never retry) from `rate_limit_error` (retry with
backoff). Without Option 1, application retry is blind.

**Trade-offs:**
- Simple; no configuration changes.
- Does not help when quota is genuinely exhausted.
- Extends worker lifetime; increases probability of the 60-minute Bash timeout.

### C.3 Option 3 — Multi-key pool per provider (within-provider rotation)

Add `LLM_API_KEY_1`, `LLM_API_KEY_2`, ... (or `LLM_API_KEYS` as
comma-separated) alongside `LLM_API_KEY`. On a `RateLimitError`, mark the failed
key as temporarily unavailable and retry on the next live key.

As established in Section B, rate limits are at the **organization level** for
Anthropic (source: https://platform.claude.com/docs/en/api/rate-limits: "Limits
are set at the organization level"), and per-project for Gemini (source:
https://ai.google.dev/gemini-api/docs/rate-limits: "Rate limits are applied per
project, not per API key."). Multi-key rotation only helps when the keys belong
to **different Anthropic organizations / different GCP projects**. Same-org /
same-project keys share the rate limit bucket.

**Trade-offs:**
- Requires operator to manage multiple separate API accounts.
- Thread-safety needed: parallel sub-question workers share one `LLMClient`.
- Key pool state is process-local; restarts reset cooldowns.

### C.4 Option 4 — Cross-model / cross-provider fallback per tier

On `RateLimitError` (quota-exhausted variant) for a tier model, substitute a
pre-configured fallback model for the remainder of that run. For example,
`model_execute = gemini-3.1-pro-preview` falls back to `claude-opus-4-6` on daily
quota exhaustion. This works across provider quota boundaries.

The existing `_DEFAULT_MODELS_ALLOWED` roster in
[`server/config.py` lines 38–45](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/config.py#L38-L45)
is already an allowlist; it could double as a fallback priority list.

**Any fallback model substitution must be explicit** — surfaced in the SSE stream
and in `params_json`. Silent downgrade would corrupt the audit trail and confuse
the UI's model-selector display. (See also `docs/research/2026-10-01-block-fable-downgrade-to-opus.md`
and the related open spec `openspec/changes/fable-downgrade-switch/`.)

**Anthropic per-model vs org-wide scoping** (source: https://platform.claude.com/docs/en/api/rate-limits:
"Rate limits are applied separately for each model; therefore you can use
different models up to their respective limits simultaneously."):
Switching from an Anthropic model that hit a per-model RPM/ITPM/OTPM limit (plain
`rate_limit_error` with no `enforced_spend_limit_reached`) to another Anthropic
model escapes that rate limit. However, switching Anthropic model does **not**
escape `enforced_spend_limit_reached` (org-wide monthly cap, resets 00:00 UTC
first of next month) or the user-set 400 `invalid_request_error` spend limit —
for those only a key from a different Anthropic organization or a different
provider helps. Note on shared buckets: Opus 4.x models (4.8 / 4.7 / 4.6 / 4.5)
share one combined rate-limit bucket (footnote 2 on the rate-limits page), so
switching within the Opus 4.x family does not escape an Opus 4.x per-model limit.

**Trade-offs:**
- High complexity; fallback model choice, per-tier or per-run granularity, UI/
  `params_json` protocol extension all need design.
- Cheaper fallback model may produce lower-quality output; teacher must be
  informed.
- Most directly addresses issue [#938](https://github.com/paulpengtw/exam-generation/issues/938)
  (Gemini provider failures).

### C.5 Option 5 — Proxy / load-balancer delegation

Route LLM traffic through an external load-balancing proxy that handles
multi-key rotation, per-key quotas, and automatic fallback transparently.

**LiteLLM Router** (https://docs.litellm.ai/docs/routing): Groups multiple
deployments/keys under shared model aliases; automatic fallback cascade when a
group fails; configurable `allowed_fails` and `cooldown_time`; supports
usage-based, latency-based, and cost-based routing; tracks per-deployment
health and triggers cooldowns on 429/quota errors.

**OpenRouter** (https://openrouter.ai/docs/features/provider-routing): Provides
automatic fallback routing across providers; default price-weighted load
balancing with stability filtering (filters out providers with recent outages);
`allow_fallbacks` and `order` request parameters to customize; cascade falls
through providers sequentially on failure.

**Trade-offs:**
- Requires adding a new infrastructure dependency.
- Works with the existing single-key env var (proxy handles the pool).
- Proxy becomes a single point of failure unless highly available.
- Error details are further abstracted; Sentry sees proxy errors, not raw
  provider errors (issue [#928](https://github.com/paulpengtw/exam-generation/issues/928)
  concern worsens).

---

## Recommendation

**Near-term (low effort, high value):** Implement **Option 1** — enrich the SSE
error payload with HTTP status, provider error type, and provider error code; add
i18n keys on the frontend. The two dispatch paths to cover are `_call()` and
`generate_with_tools()`. This also makes the spend-cap vs rate-limit distinction
actionable: frontend can show "quota exhausted — contact your administrator" vs
"rate limit — try again in N seconds".

**Revised from first draft:** The quota-signal research changes the retry logic
recommendation. **Application-level retry (Option 2) must be gated on the error
class — skip retry entirely for quota-exhausted errors** (`enforced_spend_limit_reached`
for Anthropic, `credit_balance_exhausted` / `organization_spend_limit_exceeded`
for OpenAI, `quota_exceeded` for Gemini native). Without this gate, application
retry adds wasted latency on top of the SDK's 2 already-wasted retries. Implement
Option 1 first, then add an opt-out for quota errors in Option 2.

**Medium-term (addresses Gemini quota which is the most-reported failure):**
Implement **Option 4** (cross-provider fallback) scoped to the execute tier only.
Limit to one fallback level (primary → one backup). Surface the substitution
explicitly in the SSE stream and in `params_json`. This directly addresses issue
[#938](https://github.com/paulpengtw/exam-generation/issues/938). Prerequisite:
confirm the Gemini compat body shape for quota-exhausted 429s (see B.2.c) so the
application can detect them reliably.

**Defer Option 3** (multi-key pool) until the operator confirms they have
separate billing accounts / separate GCP projects. Without that, it adds
complexity with no benefit.

**Defer Option 5** (proxy) unless infrastructure cost of managing multiple
provider keys becomes unacceptable.

**Rotation/retry decision rule (compact):**

| Condition | Action |
|---|---|
| Anthropic 429 + `details.error_code == "enforced_spend_limit_reached"` | Rotate/fallback immediately — no retry |
| Anthropic 400 `invalid_request_error` + message "specified … API usage limits" | Rotate/fallback immediately — no retry |
| Anthropic 402 `billing_error` | Rotate/fallback immediately — no retry |
| OpenAI 429 `credit_balance_exhausted` / `organization_spend_limit_exceeded` / `project_spend_limit_exceeded` / `organization_usage_limit_exceeded` | Rotate/fallback immediately — no retry |
| Gemini 402 `payment_required` | Rotate/fallback immediately — no retry |
| Gemini 429 `quota_exceeded` (daily; resets midnight PT) | Rotate/fallback immediately; or wait until midnight PT — no retry |
| Anthropic plain 429 `rate_limit_error` (no `enforced_spend_limit_reached`) | Retry with backoff honouring `retry-after` |
| Anthropic 529 `overloaded_error` | Retry with backoff honouring `retry-after` |
| Anthropic/OpenAI/Gemini 503 / 5xx | Retry with backoff |
| Gemini 429 `rate_limit_exceeded` or `too_many_requests` | Retry with backoff |
| OpenAI 429 `slow_down` | Retry with backoff honouring `Retry-After` |
| Any provider 401 / 403 | Surface immediately — config error the operator must fix; rotating would hide a revoked key |

**Caveat:** The Gemini compat-endpoint body shape (unverified item 1) determines
whether `quota_exceeded` is detectable at all on the application's path. Until
confirmed, `quota_exceeded` and `rate_limit_exceeded` may appear identical via
the compat shim.

---

## Unverified claims

The following claims in this note have no citation from authoritative docs and
should be verified before being relied upon:

1. **Gemini OpenAI-compatibility endpoint error body shape for 429:** The native
   Gemini API returns `{"error": {"code": "rate_limit_exceeded" | "quota_exceeded",
   "message": "..."}}`. It is unknown whether the compat endpoint passes this
   body through unchanged or wraps it in OpenAI shape `{"error": {"type": "...",
   "code": "..."}}`. This affects whether `quota_exceeded` vs `rate_limit_exceeded`
   can be programmatically distinguished via the compat path. Verify by inspecting
   a real 429 response body from the compat endpoint (from `llm_exchanges` rows or
   server logs).

2. **Gemini daily vs per-minute `retry-after` header:** The Gemini native API
   documentation does not specify whether a `retry-after` (or `Retry-After`)
   header is returned on 429. Assumed absent; verify in practice.

3. **OpenAI `x-ratelimit-*` headers:** Commonly documented in community sources
   (e.g. `x-ratelimit-limit-requests`, `x-ratelimit-remaining-tokens`), but the
   fetched error-codes page did not explicitly confirm their names. Assumed present;
   verify from the OpenAI rate-limits reference page.

4. **Anthropic workspace sub-limits cannot add capacity — verified and closed.**
   Source: https://platform.claude.com/docs/en/api/rate-limits: "Organization-wide
   limits always apply, even if Workspace limits add up to more." Workspace limits
   are sub-limits only; they cannot simulate per-key bucketing or add capacity above
   the org-level cap. No action required.

6. **OpenAI SDK `_should_retry()` does not short-circuit `credit_balance_exhausted`:**
   Confirmed by reading `openai/_base_client.py`: `_should_retry()` returns `True`
   for all 429s without inspecting the body. Both SDK retries are wasted on quota
   errors. However, a future SDK version may add body inspection — check release
   notes if upgrading.

---

## Open questions

1. **`retry-after` forwarding:** When the SDK exhausts its retries and raises a
   `RateLimitError`, is the `retry-after` header value available on the exception
   object, and should it be forwarded to the frontend to show a "try again in N
   seconds" notice?

2. **`generate_with_tools()` and `generate_with_google_search()` coverage:** Both
   bypass `_call()` and have their own `except Exception` blocks. Should error
   enrichment (Option 1) be extracted into a shared helper, or duplicated?

3. **Sentry deduplication:** Issue [#928](https://github.com/paulpengtw/exam-generation/issues/928)
   notes that raw provider exceptions reach Sentry with their messages. If we add
   structured error surfacing, does this interact with Sentry fingerprinting in
   a way that would group provider errors better?

4. **Cross-provider fallback and `params_json` honesty:** If a run starts with
   `model_execute = gemini-3.1-pro-preview` but falls back to `claude-opus-4-6`
   mid-run, what is the correct value to write into `params_json`? Options include:
   the requested model, the effective model, or both in a `model_execute_effective`
   field.

5. **Multi-key pool thread safety:** The parallel sub-question workers in
   `ThreadPoolExecutor` share one `LLMClient` instance. A `threading.Lock`-guarded
   cooldown dict is likely sufficient — but does a key going into cooldown mid-batch
   affect siblings that are already in-flight on that key?

6. **Batch partial-failure behaviour:** If one 小題 worker hits a quota error and
   fails, sibling independence (issue #749) allows the other workers to complete.
   Does error-surfacing Option 1 need to convey that only some workers failed, and
   which provider errors were responsible?

7. **Issue #927 interaction:** Planner failures are currently reported as provider
   failures rather than as malformed-candidates errors. Would a structured error
   taxonomy (Option 1) expose this misclassification more visibly, and should #927
   be fixed first?

8. **Gemini compat body shape confirmation:** Resolving the B.2.c unknown is a
   prerequisite for reliably detecting Gemini daily quota exhaustion. Capture one
   real `quota_exceeded` 429 body from the compat endpoint to unblock Option 4
   scoping for Gemini.
