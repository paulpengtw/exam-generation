# Tasks: execute-tier-model-fallback

**Prerequisites before starting any task:**
- Change 1 (`log-provider-error-body`): `extract_provider_error(exc) -> ProviderErrorDetail` must be importable. If not yet merged, stub it first.
- Change 2 (`surface-llm-provider-errors`): `classify_provider_error(exc: Exception, detail: ProviderErrorDetail | None = None) -> str` must be importable from `src/llm_client.py`, returning one of: `auth_config`, `quota_billing_exhausted`, `rate_limited`, `overloaded`, `timeout`, `connection`, `context_length`, `content_filtered`, `malformed_response`, `unknown`. If not yet merged, stub it first. Do NOT introduce an enum or alias for these codes.

**Memory:** Run tests with `choom -n 500 -- uv run pytest …` and web tests with `choom -n 500 -- npm --prefix web test`. Max 2–3 concurrent test lanes.

---

## 1. Config: new fields and startup validation

- [ ] 1.1 Add `_DEFAULT_EXECUTE_FALLBACK_CHAIN: list[str] = ["claude-opus-4-6", "gemini-3.1-pro-preview"]` as a module-level constant in `src/config.py` alongside the other model defaults (near `_DEFAULT_MODELS_ALLOWED` — check the exact line before placing). Add `model_execute_fallback: list[str]` parsed from `os.environ.get("LLM_MODEL_EXECUTE_FALLBACK")` (`None` → `_DEFAULT_EXECUTE_FALLBACK_CHAIN`; `""` → `[]`; non-empty → split on `,`, strip, discard blanks). Add `effort_execute_fallback: str = ""` from `LLM_EFFORT_EXECUTE_FALLBACK`. Add `execute_fallback_enabled: bool` property (`bool(self.model_execute_fallback)`). Verify: `choom -n 500 -- uv run pytest tests/test_config.py -k fallback -v` (test cases: unset → default chain; `""` → empty, feature off; single entry; multi-entry; property True/False).

- [ ] 1.2 Add `validate_execute_fallback(config, *, from_default: bool)` to `src/config.py` (or `server/config.py`). When `from_default=False` (operator-supplied): for each entry check it is in `config.llm_models_allowed` and provider key present; raise `ConfigurationError` on first bad entry. When `from_default=True` (default chain): for each entry, if not in roster or key missing, emit one WARNING and remove that entry from `config.model_execute_fallback`; do NOT raise; continue. Verify: `choom -n 500 -- uv run pytest tests/test_config.py -k validate_fallback -v` (operator bad entry → raises; operator good → passes; default bad entry → warns, drops, no raise; all default bad → all dropped, feature disabled, no raise; empty list → no-op for either mode).

- [ ] 1.3 Call `validate_execute_fallback(config)` in `server/app.py` during app startup, after `ServerConfig` is constructed. Verify: `choom -n 500 -- uv run pytest tests/server/test_config_llm_models_allowed.py -v` (update L29, L38 with fallback-model roster test cases); confirm a bad `LLM_MODEL_EXECUTE_FALLBACK` value causes the app to refuse startup in an integration or unit test.

- [ ] 1.4 Update `tests/test_default_model_tiers_split.py` L116 to: (a) include `LLM_MODEL_EXECUTE_FALLBACK` in env-var coverage assertions; (b) assert that when `LLM_MODEL_EXECUTE_FALLBACK` is not set the default chain equals `_DEFAULT_EXECUTE_FALLBACK_CHAIN`; (c) assert that `LLM_MODEL_EXECUTE_FALLBACK=""` produces an empty chain and `execute_fallback_enabled` is False. Verify: `choom -n 500 -- uv run pytest tests/test_default_model_tiers_split.py -v` passes.

## 2. LLM client: sticky fallback state and substitution point

- [ ] 2.1 Add to `LLMClient` in `src/llm_client.py`: `_execute_chain: list[str]` (built at construction: `[config.model_execute] + config.model_execute_fallback`), `_chain_position: int = 0`, `_chain_lock: threading.Lock`, `_models_used_in_run: set[str]`, and `_advance_chain(failure_class: str) -> bool` (thread-safe: acquires lock, scans forward for next entry not in `_models_used_in_run`, emits `llm_model_switch` event, advances position, returns True; returns False if chain exhausted). Verify: unit tests for concurrent `_advance_chain()` calls, skip-already-tried logic, and chain exhaustion return value; `choom -n 500 -- uv run pytest tests/test_llm_client_fallback_state.py -v`.

- [ ] 2.2 Add `LLMClient._resolve_effective_model(model: str, purpose: str) -> str` that: (1) applies any future fable-downgrade rewrite (placeholder/no-op today); (2) for execute-purpose calls returns `_execute_chain[_chain_position]` when `execute_fallback_enabled`; (3) otherwise returns the input model. Verify: unit tests for primary-model (position 0), advanced-position, and disabled-feature branches; `choom -n 500 -- uv run pytest tests/test_llm_client_resolve_model.py -v`.

- [ ] 2.3 Set `max_retries=0` on `Anthropic()` (L435) and `OpenAI()` (L631) constructors **only when `config.execute_fallback_enabled`**. Verify: unit test checks `client.max_retries == 0` when feature is on and the SDK default when off; `choom -n 500 -- uv run pytest tests/test_llm_client_max_retries.py -v`.

## 3. App-level retry loop in `_call()`

- [ ] 3.1 Write fixture-driven decision-rule tests (`tests/test_execute_tier_fallback_decision.py`) for all ten `classify_provider_error` failure-class codes and the chain scenarios, using mock SDK clients and a mock classifier. Test cases: (a) `quota_billing_exhausted` → immediate chain advance, no same-model retry; (b) `rate_limited` → N retries on current entry then advance; (c) `overloaded` → same as `rate_limited`; (d) `timeout` → same as `rate_limited`; (e) `connection` → same as `rate_limited`; (f) `auth_config` → raised immediately, no advance; (g) `context_length` → raised immediately, no advance; (h) `content_filtered` → raised immediately, no advance; (i) `malformed_response` → raised immediately, no advance; (j) `unknown` → raised immediately, no advance; (k) **Default config chain**: primary=gemini fails `quota_billing_exhausted` → advances to opus-4-6 → uses opus; if opus also fails → gemini skipped (already tried) → chain exhausted → error surfaced; (l) **Teacher-selected model chain**: primary=opus-4-6 (explicit), chain=[opus,gemini] → opus fails → gemini used; (m) **Chain exhaustion**: all entries tried → error from last failure surfaced. Verify: `choom -n 500 -- uv run pytest tests/test_execute_tier_fallback_decision.py -v` — all cases pass.

- [ ] 3.2 Implement the chain-walk retry loop inside `_call()` for execute-tier purposes when `execute_fallback_enabled` is True, following design D5. For each attempt: read current chain entry via `_execute_chain[_chain_position]`, add to `_models_used_in_run`; allocate a new `call_scope` with `retry_of_call_id`; dispatch; on exception classify and apply the decision rule; reset per-entry retry counter when `_chain_position` advances; honour `retry-after` in backoff. Verify: all tests from 3.1 pass against the real implementation; `choom -n 500 -- uv run pytest tests/test_execute_tier_fallback_decision.py tests/test_llm_client*.py -v`.

- [ ] 3.3 Confirm the retry loop does NOT apply to verify-tier or plan-tier calls even when `execute_fallback_enabled` is True. Verify: unit test with a mocked verify call confirms it raises immediately on 429 (no fallback substitution); `choom -n 500 -- uv run pytest tests/test_execute_tier_fallback_decision.py -k verify -v`.

## 4. Event protocol: `llm_model_switch` event type

- [ ] 4.1 Add `LLM_MODEL_SWITCH = "llm_model_switch"` to the event-type constants in `src/common/generation_events.py`. Add `ModelSwitchPayload(original_model: str, fallback_model: str, failure_class: str, purpose: str, agent: str)` dataclass to `server/generate/event_protocol.py` — `failure_class` carries the `classify_provider_error` code that triggered the switch (not an alias; same string codes). Verify: `python3 -c "from server.generate.event_protocol import ModelSwitchPayload; from src.common.generation_events import LLM_MODEL_SWITCH"` succeeds.

- [ ] 4.2 Emit the `llm_model_switch` event inside `_activate_fallback()` using the current call's `call_scope`; deliver through `GenerationPublisher`. Write an SSE contract test confirming the event is delivered with correct `original_model`, `fallback_model`, `failure_class`, `purpose`, `agent` fields and a valid v2 envelope (`context.run_id`, `event_seq`, `call_id`, `operation_id`). Verify: `choom -n 500 -- uv run pytest tests/test_llm_model_switch_event.py -v`.

- [ ] 4.3 Update `tests/server/test_generation_publisher.py` L653 to add a test variant for `llm_model_switch` event delivery. Update `tests/test_llm_client_operation_identity.py` L72 to add a test confirming `llm_model_switch` carries `retry_of_call_id` referencing the failed primary call's `call_id`. Verify: `choom -n 500 -- uv run pytest tests/server/test_generation_publisher.py tests/test_llm_client_operation_identity.py -v`.

## 5. Per-question metadata: `fallback_from_model`

- [ ] 5.1 In each subject pipeline (math `src/cli.py`, shared `src/common/generation_core.py`), after generation completes for a question, set `question.metadata["fallback_from_model"]` to an ordered list of model ids in `client._models_used_in_run` that were tried before the final successful model (i.e. all entries at chain positions `< _chain_position` that were dispatched). Set only when `_chain_position > 0` and at least one fallback entry was actually used. Verify: unit test with a mocked client that advanced chain position once produces `metadata["fallback_from_model"] = ["<primary>"]`; two hops produces a two-element list; unaffected question has no such field; `choom -n 500 -- uv run pytest tests/test_fallback_metadata.py -v`.

- [ ] 5.2 Confirm `fallback_from_model` is listed in `CONTENT_SIGNATURE_EXCLUDED_KEYS` in `src/common/generation_events.py` (alongside `metadata`, `review`, etc.) so it does not advance the content revision. Verify: `grep -n "fallback_from_model\|CONTENT_SIGNATURE_EXCLUDED" src/common/generation_events.py` shows the key is excluded.

## 6. Update affected existing tests

- [ ] 6.1 Update `tests/server/test_generate_routes.py` lines 2069–2070, 2112, 2286: add test variants for `RateLimitError` → structured code (e.g., `rate_limit`) and for `quota_exhausted`; keep the existing `ValueError` → `generation_failed` test unchanged. Verify: `choom -n 500 -- uv run pytest tests/server/test_generate_routes.py -v`.

## 7. Frontend: `generationEvidence.ts`

- [ ] 7.1 Handle `llm_model_switch` event in `applyV2Event()` in `web/src/lib/generationEvidence.ts`: add `switchedToModel: string | null` and `switchReason: string | null` to `QuestionEvidence` (default both `null`); set them from the event payload. Add `selectFallbackModelCount(state): number` selector counting questions with non-null `switchedToModel`. Expose `fallbackModelCount: number` in `GenerationV2Evidence` (via `projectGenerationEvidence`). Verify: `choom -n 500 -- npm --prefix web test -- --testPathPattern=generationEvidence`.

## 8. Frontend: i18n strings (both locales)

- [ ] 8.1 Add to `web/src/i18n/messages.ts` in both `en-US` and `zh-TW` locales (keyed by `failure_class` code; frontend selects the matching key and falls back to `.default`):
  - `card.model_switched.quota_billing_exhausted` — zh-TW: `"此題改用 {fallbackModel} 產生（主要模型配額已用盡）"`; en-US: `"Switched to {fallbackModel} (primary quota exhausted)"`
  - `card.model_switched.rate_limited` — zh-TW: `"此題改用 {fallbackModel} 產生（速率限制，重試後切換）"`; en-US: `"Switched to {fallbackModel} (rate-limited, switched after retries)"`
  - `card.model_switched.overloaded` — zh-TW: `"此題改用 {fallbackModel} 產生（提供者過載）"`; en-US: `"Switched to {fallbackModel} (provider overloaded)"`
  - `card.model_switched.timeout` — zh-TW: `"此題改用 {fallbackModel} 產生（逾時後切換）"`; en-US: `"Switched to {fallbackModel} (timeout, switched after retries)"`
  - `card.model_switched.connection` — zh-TW: `"此題改用 {fallbackModel} 產生（連線失敗後切換）"`; en-US: `"Switched to {fallbackModel} (connection failure, switched after retries)"`
  - `card.model_switched.default` — zh-TW: `"此題改用 {fallbackModel} 產生"`; en-US: `"Switched to {fallbackModel}"`
  - `statusbar.fallback_model_count` — zh-TW: `"{count} 題使用備援模型"`; en-US: `"{count} question(s) used fallback model"`
  Verify: grep confirms all seven keys present in both locale sections.

## 9. Frontend: QuestionCard and status bar notices

- [ ] 9.1 Render amber `role="status"` notice in `web/src/components/QuestionCard.tsx` when `QuestionEvidence.switchedToModel` is non-null; select the i18n key `card.model_switched.<switchReason>` (where `switchReason` is the `failure_class` code from the `llm_model_switch` event payload), falling back to `card.model_switched.default` for any unrecognized code; add `data-testid="evidence-model-switch-notice"`. Verify: `choom -n 500 -- npm --prefix web test -- --testPathPattern=QuestionCard`.

- [ ] 9.2 Render count line in `GenerationV2StatusLine` (`web/src/components/GenerationStatusBar.tsx`) when `fallbackModelCount > 0`; use `statusbar.fallback_model_count`; add `data-testid="statusbar-fallback-model-count"`. Verify: `choom -n 500 -- npm --prefix web test -- --testPathPattern=GenerationStatusBar`.

- [ ] 9.3 Write frontend notice tests covering: affected card (zh-TW) shows amber notice with `data-testid`; affected card (en-US) shows amber notice; unaffected card shows no notice; status bar count visible when at least one card affected; status bar count absent when none affected. Verify: `choom -n 500 -- npm --prefix web test -- --testPathPattern=fallback` — all tests pass.

## 10. Documentation

- [ ] 10.1 Add `LLM_MODEL_EXECUTE_FALLBACK` and `LLM_EFFORT_EXECUTE_FALLBACK` rows to `DEPLOYMENT.md` (§ backend env vars): document that the default when unset is `claude-opus-4-6,gemini-3.1-pro-preview` (feature on by default); that setting to `""` is the kill switch (restores SDK retry behaviour); that Anthropic spend caps are org-wide and Gemini quota is per GCP project so the chain only isolates across providers/billing buckets; that a misconfigured operator-supplied entry causes startup failure; that missing-key default entries are dropped with a WARNING. Verify: `grep -n "LLM_MODEL_EXECUTE_FALLBACK" DEPLOYMENT.md` finds both rows.

- [ ] 10.2 Add the same two env vars to the README environment table, documenting the default value and the empty-string kill switch. Verify: `grep -n "LLM_MODEL_EXECUTE_FALLBACK" README.md` finds the entry.

- [ ] 10.3 Update the "LLM provider is selected per-request" section in `CLAUDE.md` to note: (a) the execute-tier fallback feature is on by default (`LLM_MODEL_EXECUTE_FALLBACK` defaults to `claude-opus-4-6,gemini-3.1-pro-preview`; set to `""` to disable); (b) the `_resolve_effective_model()` substitution point shared with the future fable-downgrade guard — any new model substitution layer MUST be added there, not at a separate location in `_call()`. Verify: updated text is present in the CLAUDE.md section.
