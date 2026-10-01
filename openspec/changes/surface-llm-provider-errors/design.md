## Context

See `proposal.md — Why` for motivation. Line references are to commit `dd9e6b8`.

**Current error path (backend):** `LLMClient._call()` at `src/llm_client.py` L795–805 catches all exceptions, emits an `llm_failure` observer event carrying only `type(exc).__name__`, and re-raises. The worker `except Exception` in `server/generate/service.py` L896–900 calls `build_sse_error("generation_failed", f"Question generation failed ({type(exc).__name__})")`, which returns `{"code": "generation_failed", "message": "..."}`. There are four total `build_sse_error` call sites and one `/api/plan-core-questions` unhandled exception path (L647–664).

**Change 1 dependency:** `log-provider-error-body` adds `extract_provider_error(exc) -> ProviderErrorDetail` and enriches `llm_failure` observer events with normalized fields (`http_status`, `provider_error_type`, `provider_error_code`, `provider_error_status`, `provider_message`, `retry_after_seconds`, `raw_body_truncated`). The classifier in this change reads those fields. When change 1 has not landed, the classifier gracefully degrades to exception-class-only input (see D2).

**Gemini compat body shape (confirmed, Part 1 of second research doc):** `exc.code` and `exc.type` are always `None` for Gemini compat errors because the response body is a JSON array, not the dict the OpenAI SDK expects. `exc.body` contains the raw list: `[{"error": {"code": <int>, "message": "...", "status": "<gRPC>"}}]`. Invalid-key returns HTTP 400 `INVALID_ARGUMENT`, not 401.

**Frontend error path:** `parseErrorEventData(raw)` in `web/src/hooks/useGenerate.ts` L396–413 extracts `.message` from the JSON payload. `case "error"` L1288–1296 calls `setErrorMessage(parseErrorEventData(data ?? ""))`. The `errorMessage` state reaches `ProgressLog.tsx` L154–158 as a raw string inside a `<pre>` block. `web/src/i18n/messages.ts` has `statusbar.error` = "Error"/"錯誤" but no keys for any provider condition. **This file has uncommitted local edits on the current branch** — the implementer must merge carefully.

**Overlap with in-flight changes:**
- `per-question-live-progress` (already implemented): adds `failure_class` to the error payload additively — no conflict with v2 event envelopes.
- `detached-generation-runs` (proposal only, not implemented): replaces the SSE stream with a polling model. When that change lands, the persisted question terminal state will need to carry `failure_class` as well. This change does not block on that; the requirement is noted as a future concern.
- `ai-working-surfaces` (proposal only): modifies the running-state UI shimmer, not the error display — no conflict.
- `fable-downgrade-switch` (spec + design written, not implemented): operates inside `_call()` on the model string before the provider request is sent. The classifier in this change reads the exception that survives `_call()`, so the two guards are sequentially ordered and do not conflict.
- `execute-tier-model-fallback` (no artifacts yet): change 3 — explicitly excluded from scope. However, the classifier's `quota_billing_exhausted` code is the signal that change 3 will use for triggering a fallback. The taxonomy is designed with this in mind.

## Goals / Non-Goals

**Goals:**
- Every LLM provider exception that reaches an error-emission site carries a `failure_class` code before the event is sent.
- One classifier definition, one place, consumed at all five emission sites.
- Frontend maps every code to a localized zh-TW and en-US message; no new surfaces required.
- Zero behavior change on success paths and for clients that read only `code`/`message`.

**Non-Goals:**
- Retry policy, SDK `max_retries` override, or model fallback (change 3).
- Modifying `question_terminal.unknown_reason` (terminal is delivery evidence, not cause record).
- Sentry fingerprinting improvement (addressed by change 1's structured WARNING log).
- Handling modification-stream non-LLM errors (e.g., database failures) with `failure_class`.

## Decisions

### D1. Classifier location and input

Place `classify_provider_error(exc: Exception, detail: ProviderErrorDetail | None = None) -> str` in `src/llm_client.py` (alongside `extract_provider_error` from change 1). The classifier takes the raw exception as primary input and the `ProviderErrorDetail` as optional enrichment — this means it works before change 1 lands (graceful degradation) and is tighter after.

*Why here*: `llm_client.py` already owns provider routing logic (`resolve_provider`). Placing the classifier elsewhere (e.g. `server/generate/models.py`) would create an upward dependency from `server/` into `src/`.

*Why not classify in the worker*: the worker `except Exception` block in `service.py` catches exceptions from the full pipeline (verify, correct, render, JSON parse). Classifying at the worker level requires distinguishing LLM exceptions from application exceptions. Classifying in `llm_client.py` (or at the `build_sse_error` call site with the exception available) is cleaner because the LLM exceptions arrive directly from `_call()`.

*Alternative — classify at the worker based on the `llm_failure` observer event*: rejected. The observer event is async and fire-and-forget; the synchronous exception in the worker's `except` block is the authoritative signal.

### D2. Graceful degradation before change 1 lands

When `ProviderErrorDetail` is unavailable, map Python exception class name to taxonomy codes:
```
RateLimitError         → "rate_limited"
AuthenticationError    → "auth_config"
PermissionDeniedError  → "auth_config"
OverloadedError        → "overloaded"
ServiceUnavailableError → "overloaded"
InternalServerError    → "overloaded"
APITimeoutError        → "timeout"
APIConnectionError     → "connection"
RequestTooLargeError   → "context_length"
ContentFilterFinishReasonError → "content_filtered"
BadRequestError        → "unknown"   (Gemini compat uses this — can't refine without body)
(all others)           → "unknown"
```
When `ProviderErrorDetail` is available, override the class-based fallback with body-based precision (e.g. `RateLimitError` + `enforced_spend_limit_reached` → `quota_billing_exhausted`).

### D3. `build_sse_error` signature extension

Extend `build_sse_error` to accept optional enrichment kwargs:
```python
def build_sse_error(
    code: str,
    message: str,
    *,
    failure_class: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    tier: str | None = None,
    retry_after_seconds: float | None = None,
) -> dict[str, Any]:
```
All new keys are omitted from the dict when `None` so wire-format bytes for old code paths are identical to today (the old call sites that don't pass the new kwargs produce the same output). Only the five error sites that have exception context pass the enrichment.

*Alternative — a new `build_sse_error_enriched` helper*: rejected. Two helpers for the same concept; the existing helper already says "both raise sites … call this helper so the shape is defined in exactly one place."

### D4. Taxonomy code for Gemini compat 429 `RESOURCE_EXHAUSTED`

Both daily quota exhaustion and per-minute rate limits may return `status: "RESOURCE_EXHAUSTED"` via the Gemini compat endpoint (see Part 1 of the research doc — unverified). The classifier MUST return `rate_limited` (not `quota_billing_exhausted`) for this condition because:
1. It's the conservative choice: the user gets "wait and retry" guidance rather than "contact admin", which is correct for the per-minute case.
2. The message for `rate_limited` with a Gemini-provenance note explicitly mentions "may be a daily quota" so the teacher can escalate.
3. Once change 1 produces real logged bodies from staging, the classifier can be updated to check `message` text patterns (e.g. "Resource has been exhausted") and return `quota_billing_exhausted` when confirmed.

A task in section 7 of `tasks.md` covers this revisit.

### D5. `failure_class` in `question_terminal`

**Not included.** The `question_terminal` contract is immutable delivery/review evidence (requirement "Explicit immutable terminal evidence per question" in `generation-event-protocol`). A terminal's `unknown_reason` is a free-text description of *why the terminal state is unknown*, not a provider error code. Adding `failure_class` to the terminal would couple two orthogonal concerns (delivery evidence vs provider error attribution) and require a protocol change. The `error` event that precedes the terminal already carries `failure_class` — clients that need the failure class read the `error` event.

### D6. `/api/plan-core-questions` structured error

The current path lets provider exceptions propagate as unhandled 500s after the `except ValueError` block at L647–664. Add a second `except Exception as exc` after it that calls `classify_provider_error(exc)` and raises `HTTPException(status_code=502, detail={"failure_class": fc, "message": safe_message})`. HTTP 502 (Bad Gateway) is correct: the endpoint is acting as a proxy to an upstream LLM provider. The `CandidateValidationError` path remains a 502 with its existing plain string `detail` — adding `failure_class` to that case is out of scope.

### D7. Modification stream

`modification_failed` in `server/generate/modification_routes.py` L459–462 follows the same pattern as `generation_failed`. Add exception classification before the `build_sse_error` call, passing the new kwargs. The modification stream does not have a `tier` concept; pass `tier=None`.

### D8. i18n key structure

Add to `web/src/i18n/messages.ts` for each locale:
```
error.class.<code>           — short status label (e.g. "Rate limited", "配額已耗盡")
error.class_hint.<code>      — actionable guidance (1-2 sentences)
```
Teacher-actionable classes (`rate_limited`, `overloaded`, `timeout`, `connection`, `context_length`, `malformed_response`): guidance says "wait and retry" or "reduce 小題數 and retry."
Operator-only classes (`auth_config`, `quota_billing_exhausted`): guidance says "Please contact the administrator / 請聯絡管理員."
`rate_limited` (Gemini `RESOURCE_EXHAUSTED`): a separate key `error.class_hint.rate_limited_quota_possible` for "may be a daily quota limit — contact admin if retry fails" — OR the base `rate_limited` hint notes this possibility.
`unknown`: re-use the existing `statusbar.error` label + an empty or generic hint.

*Decision*: use a single `rate_limited` key whose guidance text mentions "may be a daily quota." This avoids a 10th frontend-visible variant. The underlying `failure_class` code on the wire remains `rate_limited` in both cases.

### D9. `parseErrorEventData` extension

Extend the existing `parseErrorEventData` function or add a companion `parseErrorPayload` that returns a typed `{message, failureClass, provider, model, tier, retryAfterSeconds}` object. The `case "error"` handler in `useGenerate.ts` calls this, computes the localized message from `failureClass` + `t("error.class.{failureClass}")`, and falls back to `message` (the raw backend string) when `failureClass` is absent or unrecognized. This preserves full backward compatibility.

## Risks / Trade-offs

- [Gemini quota vs rate-limit ambiguity] → conservative `rate_limited` classification; `rate_limited` hint mentions quota possibility; a task covers revisiting after real bodies are logged.
- [Uncommitted edits in `messages.ts` and `useGenerate.ts` on `feat/907-unique-saved-result`] → implementer must merge from `staging` or `main` before touching those files; merge conflict likely in `messages.ts`. Noted in tasks.
- [The `ProviderErrorDetail` type may not be available if change 1 is delayed] → D2 provides graceful degradation; the spec explicitly states the classifier works without it.
- [A new exception type from an SDK upgrade is unclassified] → falls to `unknown` safely; the teacher sees the generic message; Sentry gets the WARNING log from change 1.
- [`detached-generation-runs` (change 4) replaces the SSE stream] → when that change lands, persisted question terminal state should carry `failure_class`. Recorded as an open question rather than a blocker.
- [Test files `test_generate_routes.py` (L2069, L2112, L2286), `test_generation_publisher.py` (L653) pin `code="generation_failed"` and `"generation_failed" in response.text`] → those tests remain valid because `code` is preserved; add parallel assertions for `failure_class` rather than replacing the existing ones.

## Migration Plan

1. Implement with `LLM_FABLE_DOWNGRADE` unset and change 1 already deployed (preferred) or not yet deployed (graceful degradation).
2. Deploy backend with enriched `build_sse_error` kwargs. Old clients read `code`/`message` and are unaffected.
3. Deploy frontend with new i18n keys and updated `parseErrorEventData`. New keys have no effect until a failure actually occurs.
4. Rollback: removing the `failure_class` kwargs from `build_sse_error` call sites restores the previous wire format exactly. No database changes to undo.

## Open Questions

1. **Gemini compat `RESOURCE_EXHAUSTED` disambiguation**: Once change 1 starts logging `llm_failure` bodies to `llm_exchanges`, inspect a real Gemini quota-exhausted 429 body from the `llm_exchanges` table. If quota and rate-limit use different `message` text patterns, update the classifier to distinguish `quota_billing_exhausted` from `rate_limited` for Gemini. This is deferrable and does not change the spec interface — `failure_class` on the wire remains the same string; only which string is chosen changes.

2. **`detached-generation-runs` (change 4) forward compatibility**: When the SSE stream is replaced by a polling model, the persisted question-level state should include `failure_class` so a returning teacher can see why a question failed. This change does not need to pre-implement it, but the data model should be noted as a candidate field in the future run-state schema.
