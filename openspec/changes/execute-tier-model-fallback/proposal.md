## Why

When the execute-tier model (default: `gemini-3.1-pro-preview`) exhausts its daily quota or billing credit, every in-flight and subsequent generation for that run fails with a generic error and no user recourse. Operators need a configured fallback model that activates automatically, with the substitution surfaced to teachers so they can judge the result.

Research: `docs/research/2026-10-01-execute-tier-fallback-and-gemini-429-shape.md` (Part 2) and `docs/research/2026-10-01-llm-error-surfacing-and-key-rotation.md` (Section C.4 and the decision table).

## What Changes

- Add `LLM_MODEL_EXECUTE_FALLBACK` (ordered comma-separated list) and optional `LLM_EFFORT_EXECUTE_FALLBACK` env vars. The feature is **on by default**: unset activates the default chain `claude-opus-4-6,gemini-3.1-pro-preview`. Explicitly setting to `""` (empty string) is the operator kill switch; all behaviour is byte-identical to today in that case, including SDK retry policy. The default chain works out of the box because both `LLM_API_KEY` and `GEMINI_API_KEY` are already required by the default configuration.
- When the feature is on, set SDK `max_retries=0` on execute-tier clients and replace the SDK retry budget with an app-level chain-walk loop that honours `retry-after` and classifies failure classes before deciding whether to retry the current entry or advance the chain.
- On quota-exhausted / billing-depleted failures, advance the chain immediately (no same-model retry). On transient failures (rate-limit, 5xx, timeout, connection), retry the current chain entry with backoff, then advance after retries are exhausted. On auth/config failures, surface immediately and never advance the chain. Chain entries already tried in this run are skipped.
- The chain position is **sticky for the run**: once a hop has been made, all subsequent execute-tier calls in that run begin at the current chain position without retrying earlier entries.
- Emit one `llm_model_switch` SSE activity event **per chain hop**, each carrying `original_model`, `fallback_model`, and `failure_class`.
- Record `metadata.fallback_from_model` (a list of the models tried before the final successful model) on each question that used any fallback entry. `LLMExchange.model_used` records the model that actually ran for each call. `params_json` is unchanged (records the originally configured execute model).
- Frontend renders an amber `role="status"` notice on each affected question card (showing the final model used) and a count line in the status bar, with `zh-TW` and `en-US` localized strings.
- Every entry in the fallback chain is validated against the allowed-models roster and API key availability at server startup; misconfiguration fails fast rather than at first quota error.
- This change **consumes** the failure-class classifier from change 2 (`surface-llm-provider-errors`) and the `ProviderErrorDetail` extractor from change 1 (`log-provider-error-body`). It does not define a competing error taxonomy.

## Capabilities

### New Capabilities

- `execute-tier-fallback`: operator-controlled execute-tier model fallback triggered by quota/billing and persistent provider failure, with explicit SSE event, per-question provenance, and frontend amber notice.

### Modified Capabilities

- `generation-event-protocol`: add `llm_model_switch` to the list of v2 activity event families covered by the uniform envelope contract.

## Impact

- **Code**: `src/config.py` (new `model_execute_fallback: list[str]`, `effort_execute_fallback` fields; `execute_fallback_enabled` property; `validate_execute_fallback()` startup validator); `src/llm_client.py` (`max_retries=0` gate, `_execute_chain`, `_chain_position`, `_advance_chain()`, chain-walk retry loop inside `_call()`, `_resolve_effective_model()` shared substitution point, `llm_model_switch` event emission per hop); `server/generate/service.py` (startup validation call); `src/common/generation_events.py` (`LLM_MODEL_SWITCH` constant); `server/generate/event_protocol.py` (`ModelSwitchPayload`); `src/common/generation_core.py`, `src/cli.py`, subject pipelines (set `metadata.fallback_from_model` as list); `web/src/lib/generationEvidence.ts` (handle `llm_model_switch`); `web/src/components/GenerationStatusBar.tsx` (fallback count line); `web/src/components/QuestionCard.tsx` (amber notice); `web/src/i18n/messages.ts` (new keys).
- **API**: additive only. New `llm_model_switch` SSE event; new optional `fallback_from_model` field (list) in question `metadata`; no field removed or renamed.
- **Database**: no migration. New data lives within the existing JSON/JSONB columns.
- **Operations**: `LLM_MODEL_EXECUTE_FALLBACK` defaults to `claude-opus-4-6,gemini-3.1-pro-preview` when unset — **SDK `max_retries=0` and the app-level retry loop now apply to every correctly-configured deployment by default**. To opt out: `LLM_MODEL_EXECUTE_FALLBACK=""`. `LLM_EFFORT_EXECUTE_FALLBACK` is optional. `DEPLOYMENT.md` and README env-var tables gain both vars, the default value, the empty-string kill switch, and the provider-isolation note. CLAUDE.md "LLM provider" section updated with substitution-point note and default chain.
- **Dependencies**: change 1 (`log-provider-error-body`) for `extract_provider_error` / `ProviderErrorDetail`; change 2 (`surface-llm-provider-errors`) for the failure-class classifier.
