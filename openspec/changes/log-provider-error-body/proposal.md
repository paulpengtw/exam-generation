## Why

When any LLM provider call fails, the application captures only the Python exception class name (`RateLimitError`, `OverloadedError`, etc.), discarding the HTTP status code, provider error type/code, human-readable message, and `retry-after` value. This makes quota-exhausted errors indistinguishable from transient rate limits at every layer (observer events, WARNING logs, Sentry, `llm_exchanges` rows), blocking diagnosis of the most impactful failure class — Gemini daily quota exhaustion — and preventing change 3 (`execute-tier-model-fallback`) from making any quota classification decision.

Research: `docs/research/2026-10-01-llm-error-surfacing-and-key-rotation.md` and `docs/research/2026-10-01-execute-tier-fallback-and-gemini-429-shape.md` (esp. Part 1 and appendix).

## What Changes

- Add a pure, provider-agnostic extractor `extract_provider_error(exc) -> ProviderErrorDetail` in `src/llm_client.py` (or a companion module) that normalizes: provider, model, HTTP status, provider error type/code/status string (including Google gRPC `status`), provider message, request id, `retry-after` / `retry-after-ms` value, and a bounded (≤ 4 KiB) raw body — handling Anthropic-shaped dicts, OpenAI-shaped dicts, and Google list-wrapped bodies (including `details[]` entries such as `QuotaFailure.violations[].quotaId` and `RetryInfo.retryDelay`), plus non-HTTP failures (timeout, connection) where `http_status` is `None`. The extractor DOES NOT classify errors into user-facing codes — that belongs to change 2 (`surface-llm-provider-errors`).
- Every `llm_failure` observer event carries the normalized `ProviderErrorDetail` as additional fields (`http_status`, `provider_error_type`, `provider_error_code`, `provider_error_status`, `provider_message`, `request_id`, `retry_after_seconds`, `raw_body_truncated`).
- A structured WARNING log line is emitted on every failed call. Because `LoggingIntegration(level=logging.WARNING)` is configured in `server/observability.py`, this line is forwarded to Sentry automatically — no additional Sentry instrumentation is required.
- **Persist failed calls:** the `ExchangeRecorder` is extended to handle `llm_failure` events and write an `LLMExchange` row whose `response_body` carries the `ProviderErrorDetail`. Rationale: logs and Sentry events are ephemeral; a stored row in `llm_exchanges` gives operators a durable, queryable record of every failed call including the raw error body, which is the primary evidence needed to settle the Gemini compat 429 shape (see research note §1.A and §1.C). The `LLM_EXCHANGE_RETENTION_DAYS=0` disabling mechanism is respected: when disabled no row is written. Identity is preserved in `response_body["identity"]` following the existing convention.
- Safety invariants: no API keys, auth headers, or request prompts are included in the log line or persisted row; raw bodies are truncated at 4 KiB before logging or storing; the original exception is re-raised unchanged after diagnostic capture — current retry and propagation behaviour is untouched.
- **Non-goals** (other changes): user-facing error codes and i18n display (change 2 `surface-llm-provider-errors`); retry policy, SDK `max_retries` override, and model fallback (change 3 `execute-tier-model-fallback`); multi-key pools.

## Capabilities

### New Capabilities

- `llm-provider-diagnostics`: a provider-agnostic error-detail extractor and the contract for how failed LLM call diagnostics are captured in observer events, WARNING logs, and persisted exchange rows.

### Modified Capabilities

None. The existing specs (`generation-event-protocol`, `per-question-live-progress`, `generation-release-control`, `question-snapshot-export`) have no requirements about provider error detail — those are activity-event payload details not covered at spec level. The SSE wire payload changes belong to change 2.

## Impact

- **Code**: `src/llm_client.py` (extractor, three `llm_failure` emission sites: `_call()` lines 795–805, `generate_with_tools()` lines 1362–1372, `generate_with_google_search()` lines 1438–1448; also `generate_image()` lines 1218–1228 for completeness); `server/generate/exchange_recorder.py` (handle `llm_failure` events); `server/models.py` `LLMExchange` (no schema change — `response_body` JSON column absorbs the error detail).
- **API**: additive only. The `llm_failure` observer event gains new optional fields; `llm_exchanges` rows for failed calls are new but within the existing table and column set.
- **Database**: no migration. The `response_body` JSONB column already exists on `LLMExchange`.
- **Operations**: none. No new env vars. The diagnostic path is enabled unconditionally (subject to `LLM_EXCHANGE_RETENTION_DAYS`).
