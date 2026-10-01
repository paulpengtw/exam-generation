## Why

Every LLM provider failure — transient rate limit, exhausted quota, revoked key, server overload, timeout — reaches teachers as the same opaque string `"Question generation failed (RateLimitError)"`. Change 1 (`log-provider-error-body`) captures raw provider detail in `ProviderErrorDetail`; this change maps it to a stable ten-class taxonomy and surfaces an actionable, localized message so a teacher knows whether to wait and retry, reduce 題數, or contact the administrator.

Research: `docs/research/2026-10-01-llm-error-surfacing-and-key-rotation.md` (tables A.2 and B.3) and `docs/research/2026-10-01-execute-tier-fallback-and-gemini-429-shape.md` (Part 1 — Gemini list-wrapped body).

## What Changes

- Add a pure classifier `classify_provider_error(exc: Exception, detail: ProviderErrorDetail | None = None) -> str` that maps each provider error to one of ten stable codes: `auth_config`, `quota_billing_exhausted`, `rate_limited`, `overloaded`, `timeout`, `connection`, `context_length`, `content_filtered`, `malformed_response`, `unknown`. The Gemini compat 429 body is list-wrapped with only a gRPC `status` string available; when `status == "RESOURCE_EXHAUSTED"` and quota vs rate-limit cannot be confirmed, the classifier returns `rate_limited` (conservative — see Open Questions in design.md).
- Enrich every SSE `error` event payload with `failure_class` (the stable code), `provider`, `model`, `tier`, and `retry_after_seconds` (when known). The existing `code` and `message` fields are preserved for backward compatibility with old clients and the legacy stream adapter.
- Wire the classifier to all five error-emission sites: per-question `generation_failed`, batch `batch_generation_failed`, stream-level `stream_failed` (generation), `modification_failed` (modification stream), and the LLM exception path in `/api/plan-core-questions` (returns HTTP 502 with `{failure_class, message}`).
- **Dependency**: this change requires `ProviderErrorDetail` from change 1 (`log-provider-error-body`). The classifier reads the normalized fields that extractor produces. If change 1 has not landed, the classifier receives a minimal `ProviderErrorDetail` with only `exc_class` populated and produces a best-effort result.
- Frontend: extend `parseErrorEventData` to also extract `failure_class`, `provider`, `model`, `retry_after_seconds`. Map `failure_class` codes to i18n keys in both `en-US` and `zh-TW`. Guidance distinguishes teacher-actionable outcomes (wait and retry, reduce 題數) from operator-only outcomes (contact administrator). Unknown or absent `failure_class` falls back to the current generic message — no regression for old clients or unclassifiable errors.
- Display the localized message in the two surfaces where errors already render: `ProgressLog` error block and the per-question error line in `GenerationStatusBar`. No new UI surfaces are added.
- `question_terminal.unknown_reason` is **not** changed. The `error` event that precedes the terminal already carries `failure_class`; the terminal is delivery-and-review evidence, not a causal record, and altering it would break the terminal contract in `generation-event-protocol`.
- **Non-goals** (other changes): retry policy and SDK `max_retries` override (change 3 `execute-tier-model-fallback`); raw body capture and `ProviderErrorDetail` extractor (change 1 `log-provider-error-body`); multi-key pools; model fallback on quota exhaustion.
- This change substantially addresses GitHub issue [#938](https://github.com/paulpengtw/exam-generation/issues/938) ("Expose actionable Gemini provider failures") by providing stable, categorized failure codes for Gemini authentication, quota/rate-limit, timeout, and malformed-response failures.

## Capabilities

### New Capabilities

- `llm-error-messages`: the ten-class failure taxonomy, the enriched SSE error payload contract, the `/api/plan-core-questions` structured error response, and the frontend i18n mapping with actionable guidance per class.

### Modified Capabilities

- `generation-event-protocol`: ADDED requirement — SSE `error` event payloads SHALL carry `failure_class` and safe context (`provider`, `model`, `tier`, `retry_after_seconds`) alongside existing `code` and `message`. The `code` field SHALL remain for backward compatibility.

## Impact

- **Code**:
  - `src/llm_client.py` (or `src/provider_error_classifier.py`): new `classify_provider_error` function consuming `ProviderErrorDetail` from change 1.
  - `server/generate/models.py`: `build_sse_error` gains optional enrichment kwargs.
  - `server/generate/service.py`: all `build_sse_error` call sites in the per-question worker and batch-planner failure path.
  - `server/generate/routes.py`: `stream_failed` site and `/api/plan-core-questions` exception handler.
  - `server/generate/modification_routes.py`: `modification_failed` site.
  - `web/src/hooks/useGenerate.ts`: `parseErrorEventData` extended; `case "error"` localizes via `failure_class`.
  - `web/src/lib/modificationStream.ts`: `parseError` extended.
  - `web/src/i18n/messages.ts`: ~20 new i18n keys (status label + guidance per class × 2 locales). **Note**: this file has uncommitted local edits on `feat/907-unique-saved-result`; the implementer should rebase or merge before touching it.
  - `web/src/components/ProgressLog.tsx`: render localized message.
- **API**: additive only. The `error` SSE event payload gains optional fields; no existing field is removed or renamed. The `/api/plan-core-questions` LLM-failure error body gains `failure_class`.
- **Database**: none.
- **Operations**: none. No new env vars.
- **Backward compatibility**: old clients that read only `code` and `message` continue to work. The legacy stream adapter (`web/src/lib/legacyAdapter.ts`) does not process `error` events; the `case "error"` in `useGenerate.ts` reads `message` which is unchanged.
