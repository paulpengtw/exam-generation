## Context

See `proposal.md` — Why. Line references are to commit `dd9e6b8`.

**Current failure path (summarized from research):**

```
Provider raises exception
  └─ _call() catch (L795–805): emits llm_failure with error_type=type(exc).__name__ only
       └─ re-raises → service.py worker catch → SSE "generation_failed (ClassName)"
```

Three `llm_failure` emission sites in `src/llm_client.py`:
- `_call()` L795–805 — covers `generate`, `generate_json`, `generate_with_image`
- `generate_with_tools()` L1362–1372 — Anthropic web-search fact-check path
- `generate_with_google_search()` L1438–1448 — Gemini grounding path
- `generate_image()` L1218–1228 — image generation (covered for completeness)

**ExchangeRecorder** (`server/generate/exchange_recorder.py` L116–137): `__call__` handles only `llm_request` and `llm_response`. An `llm_failure` event falls through with no effect — no DB row is written. This is the gap that makes quota errors invisible in `llm_exchanges`.

**Sentry integration** (`server/observability.py` L111–115): `LoggingIntegration(level=logging.WARNING, event_level=logging.WARNING)` — any `logger.warning(...)` call from any module in the process is forwarded as a Sentry event automatically. No additional Sentry instrumentation is required.

**Body shapes that must be handled** (from research notes):
- Anthropic: `{"type":"error","error":{"type":"rate_limit_error","message":"...","details":{"error_code":"enforced_spend_limit_reached"}}}` — body is a dict; `exc.type` and `exc.body` are available on Anthropic SDK exceptions.
- OpenAI: `{"error":{"type":"...","code":"credit_balance_exhausted","message":"..."}}` — body is a dict; `exc.type`, `exc.code`, `exc.body` available.
- Google compat: `[{"error":{"code":429,"message":"...","status":"RESOURCE_EXHAUSTED"}}]` — body is a **list**; the OpenAI SDK sets `exc.code=None` and `exc.type=None` for list bodies (confirmed by SDK source reading at `.venv/` and research §1.D). The list must be read from `exc.body` directly.

## Goals / Non-Goals

**Goals:**
- One pure, testable extractor function for all three body shapes.
- Every `llm_failure` emission site gains provider error detail — no site is missed.
- Failed calls produce a WARNING log line that Sentry captures.
- Failed calls produce a persisted `llm_exchanges` row for operator inspection.
- Zero change to retry/propagation behaviour; zero secrets in logs or DB.

**Non-Goals:**
- Classifying errors into user-facing codes (change 2).
- Retry policy or SDK `max_retries` override (change 3).
- Changing the SSE wire protocol or frontend display (change 2).
- Backfilling historical exchange rows.

## Decisions

### D1. Extractor as a standalone function in `src/llm_client.py`

Add `extract_provider_error(exc: Exception, *, provider: str, model: str) -> ProviderErrorDetail` as a module-level function, and `ProviderErrorDetail` as a `dataclass(frozen=True)` or TypedDict.

**Rationale:** Placing it in `src/llm_client.py` keeps it adjacent to all four call sites and makes it importable from tests without pulling in server-side dependencies. Change 2 (`surface-llm-provider-errors`) will import the same function to build its classifier; a shared location avoids duplication.

**Alternative — separate `src/provider_errors.py`:** Rejected for now. The function is small and its only caller today is `llm_client.py`. If change 2 or 3 grow it significantly, extracting is a pure refactor with no contract change.

**Alternative — inline extraction at each call site:** Rejected. Four independent copies of body-parsing logic would diverge.

### D2. Body normalization logic (three shapes + non-HTTP)

```
extract_provider_error(exc, provider, model):
  status     = getattr(exc, "status_code", None)    # int or None
  body       = getattr(exc, "body", None)
  headers    = getattr(exc, "response", None) and exc.response.headers

  if isinstance(body, list) and body:               # Google list-wrapped
      inner      = body[0].get("error", {}) if isinstance(body[0], dict) else {}
      error_type = None                             # not present in Google shape
      error_code = None                             # exc.code is None (SDK limitation)
      error_status = inner.get("status")            # gRPC status string
      message    = inner.get("message")
      details    = _parse_google_details(inner.get("details", []))
      retry_after = details.get("retry_after")
  elif isinstance(body, dict):                      # Anthropic or OpenAI
      err        = body.get("error", body)
      error_type = err.get("type") or getattr(exc, "type", None)
      error_code = err.get("code") or getattr(exc, "code", None)
      error_status = None
      message    = err.get("message") or getattr(exc, "message", None)
      details    = _parse_anthropic_details(err.get("details", {}))
      retry_after = (headers or {}).get("retry-after") or \
                    (headers or {}).get("retry-after-ms")  # ms → seconds
  else:                                             # non-HTTP or unparseable
      error_type = error_code = error_status = message = retry_after = None

  raw_body = _truncate(str(body), 4096)
  request_id = (headers or {}).get("request-id") or \
               (headers or {}).get("x-request-id")

  return ProviderErrorDetail(
      provider=provider, model=model,
      http_status=status, provider_error_type=error_type,
      provider_error_code=error_code, provider_error_status=error_status,
      provider_message=message, request_id=request_id,
      retry_after_seconds=_parse_retry_after(retry_after),
      raw_body_truncated=raw_body,
  )
```

The `provider` argument is already computed by `resolve_provider(model)` before each call site's `try` block, so no new code is needed to determine it.

**Google `details[]` parsing:** Anthropic's body occasionally includes a `details` list with `@type`-tagged entries (e.g. `type.googleapis.com/google.rpc.RetryInfo`). Parse `retryDelay` from a `RetryInfo` entry and `violations[].quotaId` from a `QuotaFailure` entry when present. Both are best-effort: missing entries produce `null` fields.

**4 KiB truncation bound justification:** The largest observed error body (Anthropic spend-cap with full rate-limit header list) is under 1 KiB. 4 KiB gives comfortable headroom for future body growth while keeping rows small in the DB. The truncation is a hard limit applied before any persistence or logging.

### D3. WARNING log line format

```python
logger.warning(
    "llm_failure provider=%s model=%s http_status=%s "
    "error_type=%s error_code=%s request_id=%s",
    detail.provider, detail.model, detail.http_status,
    detail.provider_error_type, detail.provider_error_code,
    detail.request_id,
)
```

`provider_message` and `raw_body_truncated` are intentionally omitted from the log line: the message may contain API-key echoes or sensitive context, and the raw body is available in the `llm_exchanges` row. Sentry's `LoggingIntegration` captures the formatted log line as a breadcrumb/event; no extra `sentry_sdk.capture_*` call is needed.

**Why WARNING and not ERROR:** `ERROR` would create high-priority Sentry issues for every quota error including transient rate limits. `WARNING` keeps them grouped as informational events while still being forwarded. After classification (change 2) the worker's SSE `error` event remains the signal for downstream alerting.

### D4. ExchangeRecorder extension for llm_failure

Extend `ExchangeRecorder.__call__` to handle `"llm_failure"` events:

```python
if event_type == "llm_failure":
    agent = str(event.get("agent", ""))
    with self._lock:
        if identity is not None:
            req = self._pending_by_call.pop(identity, None)
        else:
            req = self._pending_legacy.pop(agent, None)
    self._flush_failure(agent, req, event)
    return
```

`_flush_failure` builds a row identical to `_flush` except:
- `response_body` = `{"error": dict(detail)}` where `detail` is the `ProviderErrorDetail` fields serialized from the event's additional fields; identity is nested under `response_body["identity"]` as today.
- `prompt_tokens` and `completion_tokens` are `None`.
- `model_used` comes from the failure event's `model` field.

**No schema change:** `response_body` is already a JSONB column that accepts any dict. A failed-call row is distinguished from a successful-call row by the presence of `response_body["error"]`.

**Persistence guard:** `ExchangeRecorder` is only attached when `LLM_EXCHANGE_RETENTION_DAYS > 0` (see `server/app.py` startup logic). When it is not attached, the `llm_failure` event is never seen by the recorder — no change needed.

**Alternative — a new `failed_response_body` column:** Rejected. Adds a migration, and the `response_body` column already semantically covers "what the provider returned or failed to return."

### D5. Call site changes — four sites, one helper

Each `llm_failure` emission block gains two lines before `raise`:

```python
except Exception as exc:
    detail = extract_provider_error(exc, provider=provider, model=model)
    if self._observer and call_scope is not None:
        self._emit_call_event(
            "llm_failure",
            call_scope,
            purpose=purpose,
            agent=agent,
            model=model,
            error_type=type(exc).__name__,
            **dataclasses.asdict(detail),   # spreads all ProviderErrorDetail fields
        )
    logger.warning(
        "llm_failure provider=%s model=%s http_status=%s error_type=%s error_code=%s request_id=%s",
        detail.provider, detail.model, detail.http_status,
        detail.provider_error_type, detail.provider_error_code, detail.request_id,
    )
    raise
```

`generate_image()` uses a fixed provider/model resolved at construction time; the extractor call is identical. `generate_with_tools()` and `generate_with_google_search()` already resolve `call_model` and `provider` before their `try` blocks.

**Why spread `ProviderErrorDetail` into `_emit_call_event` kwargs rather than nest it:** The existing `llm_failure` event consumers (fable-downgrade spec D4, ExchangeRecorder) read flat keys. Nesting under a `provider_error` sub-dict would break event consumers that check for `error_type`. The flat spread is additive and backward-compatible.

### D6. Staging verification task

After the change deploys to staging, a Gemini 429 must be forced and the resulting `llm_exchanges` row inspected to confirm `response_body.error.provider_error_status` and `raw_body_truncated`. This settles the open question from research §1.E about whether quota vs rate-limit Gemini errors are distinguishable by `status` field. The result is recorded in `docs/research/2026-10-01-execute-tier-fallback-and-gemini-429-shape.md`.

## Risks / Trade-offs

- [ExchangeRecorder sees `llm_failure` events that were previously ignored; an ordering edge case could pop a `_pending_by_call` entry already consumed by a concurrent `llm_response`] → The `_pending_by_call` dict is lock-guarded. In practice `llm_failure` replaces `llm_response` — only one or the other arrives per `(run_id, call_id)` pair. A defensive `pop(..., None)` returns `None` if the key is absent, producing a row with `request_body=null`, which is acceptable.
- [The `raw_body_truncated` field in DB rows grows the average `response_body` size by ~few hundred bytes per failed row] → Accepted. Failed calls are rare in normal operation; the 4 KiB cap bounds the worst case.
- [Sentry captures WARNING logs including `provider_message`; that field is excluded from the log line in D3, but is present in the `llm_failure` event which Sentry's OpenAI/Anthropic SDK integrations may capture separately] → `server/observability.py` sets `include_prompts=False` on both SDK integrations. Provider error messages are not prompts; they may appear in SDK breadcrumbs. This is acceptable — error messages are diagnostic, not secret.
- [Four call sites must be updated; a fifth added later bypasses the extractor] → A test (parallel to fable-downgrade tasks task 2.6) enumerates `llm_failure` emission sites and fails when a new one lacks the extractor call.

## Migration Plan

1. Deploy with no env var changes — the extractor is always active once the code lands.
2. Confirm WARNING log entries appear in staging logs within minutes of the first provider call.
3. Query `llm_exchanges` for rows with `response_body ? 'error'` to confirm failed-call rows are being written.
4. Force a Gemini quota-exhausted error in staging (temporarily exhaust quota on a test key or use a key from a project with a low quota) and inspect the resulting row to settle the `RESOURCE_EXHAUSTED` vs distinguishable-status open question.

**Rollback:** remove the deploy. No migration needed to restore previous state — the new rows in `llm_exchanges` are additive and the `response_body` column accepts both old (successful) and new (failed) shapes.

## Open Questions

1. **Gemini quota vs rate-limit distinguishability:** The live probe confirmed `"status":"RESOURCE_EXHAUSTED"` for an invalid-key 400, but whether a quota-exhausted 429 and a per-minute-limit 429 both use `"RESOURCE_EXHAUSTED"` or use different `status` values is not confirmed. This does not block the current change — the extractor captures whatever `status` is present. The staging verification task (D6) settles this for change 3's classifier.

2. **`retry-after` availability on Anthropic 429 after SDK exhaustion:** When the Anthropic SDK retries twice and then raises, is the `retry-after` header from the *last* response available on `exc.response.headers`? If not, `retry_after_seconds` will be `null` even for transient rate limits. This is acceptable for this change (we log and store what we have); change 3 can probe this separately.
