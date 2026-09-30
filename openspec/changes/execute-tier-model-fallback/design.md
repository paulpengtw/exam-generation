## Context

See `proposal.md → Why`. All execute-tier calls share one `LLMClient` instance per run, constructed at `server/generate/service.py` L276–286 (`_setup_run_context()`). Both SDK clients are built without a `max_retries` override — the SDK default of 2 retries applies ([anthropic v0.104.1 `_constants.py`](https://github.com/anthropics/anthropic-sdk-python/blob/v0.104.1/src/anthropic/_constants.py), [openai v2.30.0 `_base_client.py`](https://github.com/openai/openai-python/blob/v2.30.0/src/openai/_base_client.py)). Both SDKs retry all 429s and >=500s without body inspection, so quota-exhausted errors consume 2 wasted retries before propagating.

**Dependency on change 1 (`log-provider-error-body`):** This design assumes `extract_provider_error(exc) -> ProviderErrorDetail` is importable from `src/llm_client.py` or a companion module. If not yet landed, it must be stubbed before the retry loop can be wired.

**Dependency on change 2 (`surface-llm-provider-errors`):** This design assumes `classify_provider_error(exc: Exception, detail: ProviderErrorDetail | None = None) -> str` is importable from `src/llm_client.py`. It returns one of ten stable string codes: `auth_config`, `quota_billing_exhausted`, `rate_limited`, `overloaded`, `timeout`, `connection`, `context_length`, `content_filtered`, `malformed_response`, `unknown`. This change MUST NOT define a competing taxonomy or introduce any enum alias for these codes.

**Interaction with `fable-downgrade-switch` (unimplemented):** That proposal adds a static, env-flag-controlled model rewrite inside `_call()`. If/when it lands, both substitutions must share one ordered substitution point (see D2). There is no code to order against today.

Key code references at commit `dd9e6b8`:
- `src/llm_client.py` L543–555 `_model_for_purpose()`, L740 `_call()`, L435–438 Anthropic client construction, L623–633 `_openai_compat_client()`.
- `src/config.py` L52 `model_execute`, L98 env reading, L37–44 `EFFORT_LEVELS`.
- `server/generate/service.py` L276–286 `_setup_run_context()`.
- `server/generate/event_protocol.py`, `src/common/generation_events.py`.

## Goals / Non-Goals

**Goals:**
- Explicit-empty kill switch is a zero-byte-change guarantee: SDK retries, event bytes, stored params, exchange records all unchanged when `LLM_MODEL_EXECUTE_FALLBACK` is set to `""`. Unset now activates the default chain.
- One shared substitution point usable by both this fallback and the future fable-downgrade guard.
- App-level retry loop replaces SDK retries for execute-tier calls when the feature is active (default: always).

**Non-goals:**
- Multi-level fallback chains (primary → fallback A → fallback B).
- Verify/plan-tier fallback.
- Multi-key pools (separate billing-account keys).
- Per-request user toggle to disable the fallback (teacher-picked model still falls back; see D9).
- Proxy/router delegation.

## Decisions

### D1. Config fields and startup validator

Add to `src/config.py`. Follow the existing tier-default convention (CLAUDE.md: "only unset env vars use the defaults"):

- `_DEFAULT_EXECUTE_FALLBACK_CHAIN: list[str] = ["claude-opus-4-6", "gemini-3.1-pro-preview"]` — define as a module-level constant alongside the other model defaults (near `_DEFAULT_MODELS_ALLOWED` and the `DEFAULT_MODEL_*` constants; check exact line at `src/config.py` before implementing).
- `Config.model_execute_fallback: list[str]` — parsed from `os.environ.get("LLM_MODEL_EXECUTE_FALLBACK")` (no default in `get`; `None` means unset):
  - `None` (unset) → `_DEFAULT_EXECUTE_FALLBACK_CHAIN` (feature on by default).
  - `""` (explicitly set to empty string) → `[]` (operator kill switch; feature off; all behaviour byte-identical to today).
  - non-empty string → split by `,`, strip each entry, discard blanks (operator-supplied chain).
- `Config.effort_execute_fallback: str = ""` from `os.environ.get("LLM_EFFORT_EXECUTE_FALLBACK", "")`. This single value applies uniformly to all entries in the fallback chain; each entry still goes through its model's provider-native effort translation (`_effort_kwargs()`). No per-entry effort variable is provided — the chain is a resilience mechanism, not a quality-tuning control, and a uniform effort level is sufficient.
- `Config.execute_fallback_enabled: bool` property = `bool(self.model_execute_fallback)`.
- `validate_execute_fallback(config, *, from_default: bool)`: called at server startup. Distinguishes two cases:
  - **Operator-supplied chain** (`from_default=False`): for each entry, check it is in `config.llm_models_allowed` and `_check_provider_key_for_model(entry, config)` passes; raise `ConfigurationError` naming the bad entry on the first failure (fail-fast).
  - **Default chain** (`from_default=True`): for each entry, if its provider key is absent, emit one WARNING (`"execute fallback: dropping default entry '<model>': provider key missing"`) and remove that entry from `model_execute_fallback`; if the entry is not in `config.llm_models_allowed`, also drop with WARNING; continue — a partially-functional default chain is better than crashing the server. If all entries are dropped the chain is empty and the feature becomes disabled for this run.

The `from_default` flag is set to `True` when `os.environ.get("LLM_MODEL_EXECUTE_FALLBACK") is None` and `False` when the operator supplied a value (even if that value resolves to the same list).

Note: the default chain (`claude-opus-4-6`, `gemini-3.1-pro-preview`) requires `LLM_API_KEY` (Anthropic) and `GEMINI_API_KEY` respectively. The existing default config already requires both (CLAUDE.md: "Both `GEMINI_API_KEY` and `LLM_API_KEY` are required for the default configuration"), so the default chain works out of the box on any correctly-configured deployment.

`ServerConfig` inherits from `Config`; the validator runs in the FastAPI app startup hook.

*Why fail-fast for operator-supplied entries*: the operator explicitly wrote the value; a misconfiguration is an error, not a degraded-mode condition.

*Why warn-and-drop for default entries*: a default entry may be missing its key on a minimal deployment (e.g. an operator using only Gemini). Crashing the server over a missing default key would break existing deployments that never needed the fallback.

### D2. Single substitution point shared with fable-downgrade

Add `LLMClient._resolve_effective_model(model: str, purpose: str) -> str` in `src/llm_client.py`:

1. If the fable-downgrade feature is on (once implemented): apply `config.dispatch_model(model)` → rewritten id.
2. For execute-purpose calls, if `_fallback_active` is True: return `config.model_execute_fallback`.
3. Otherwise: return the (possibly rewritten) model.

All call paths — `_call()`, and `generate_with_tools()` (for the future guard) — resolve their effective model through this single method before building provider options and SDK calls. This prevents the two substitution layers from interacting unpredictably if both are active simultaneously.

When the fable-downgrade guard lands it MUST be placed in step 1 of this method, not at a separate location, so the quota-fallback in step 2 operates on the post-fable-rewrite effective model.

*Alternative — sticky state directly on `_model_for_purpose()`*: would work but doesn't establish an explicit named point for future substitution layers. The named `_resolve_effective_model` is a clearer contract for the implementer of fable-downgrade.

### D3. Chain position tracking on `LLMClient`

Add to `LLMClient`:
- `_execute_chain: list[str]` — built at construction time from `[config.model_execute] + config.model_execute_fallback`. When the feature is disabled (`model_execute_fallback` is empty), this list has one entry (the primary model) and the loop never needs to advance.
- `_chain_position: int = 0` — index of the model currently being used. Position 0 is the primary model. Advances monotonically forward; never decreases. "Sticky for the run" means position only moves forward.
- `_chain_lock: threading.Lock` — guards all position advances; ensures concurrent workers agree on position.
- `_models_used_in_run: set[str]` — populated at the start of each attempt with the model id being dispatched; used by `_advance_chain` to skip chain entries already tried.
- `_advance_chain(failure_class: str) -> bool` — thread-safe: acquires lock, scans forward from the current position for the next entry not in `_models_used_in_run`; if found: emits one `llm_model_switch` event (original = current model, fallback = next model), advances `_chain_position`, returns `True`. If no unused entry remains: returns `False` (chain exhausted).

The `LLMClient` is constructed once per run in `_setup_run_context()` and passed to all parallel `_worker_one` calls. Thread-safe because `_chain_lock` guards all advances. Process-local: in a multi-instance Railway deployment each instance discovers quota independently — see Risks.

*Why list + position rather than `_fallback_active: bool`*: the bool design assumed exactly one fallback entry; the chain design handles N entries with the same mechanism. A bool would require extending to an index anyway.

*Why skip models already tried*: the default recommended chain is `claude-opus-4-6,gemini-3.1-pro-preview`, but the primary execute model is also `gemini-3.1-pro-preview`. Without skipping, the chain would be `[gemini, opus, gemini]`, retrying gemini a second time after opus is also exhausted — pointless and wasteful. Skipping ensures each provider is tried at most once regardless of how the chain was configured.

*Alternative — sticky state on `_RunContext`*: semantically equivalent since `LLMClient` is already per-run. Keeping it on the client avoids passing extra context through every call site.

### D4. SDK `max_retries=0` gated on `execute_fallback_enabled`

Pass `max_retries=0` to `Anthropic()` (L435) and `OpenAI()` (L631) constructors **only when `config.execute_fallback_enabled` is True**. When the feature is off, SDK defaults remain unchanged — the zero-byte-change guarantee holds.

Consequence: when the feature is on, the app-level loop (D5) owns all retry decisions for execute-tier calls.

### D5. App-level retry loop inside `_call()`

When `execute_fallback_enabled` and the call's purpose resolves to the execute tier, wrap the provider dispatch in a bounded retry loop. Decision rule by `failure_class` code:

- `quota_billing_exhausted` → `_advance_chain(fc)` immediately; no same-model retry.
- `rate_limited`, `overloaded`, `timeout` → retry the current chain entry with backoff (honouring `retry_after_seconds`); after retries exhausted → `_advance_chain(fc)`. This path also covers Gemini daily quota while it is classified `rate_limited` (see Risks).
- `connection` → same as `rate_limited` / `overloaded` (retry then advance chain). Rationale: a transient DNS or network failure may resolve on the next attempt; switching provider may reach a different network path if the two providers use different infrastructure, which is net positive.
- `auth_config` → `raise` immediately; never advance chain. Rotating to a different model would hide a revoked or misconfigured key from the operator.
- `context_length`, `content_filtered`, `malformed_response`, `unknown` → `raise` immediately; no advance. These are question-level or application-level errors where a different model is unlikely to resolve the underlying problem; `unknown` is handled conservatively.

If `_advance_chain()` returns `False` (chain exhausted), `raise` the last exception — chain exhaustion surfaces the `failure_class` from the final failure.

```
attempt 0..max_app_retries * len(_execute_chain):
    effective_model = _execute_chain[_chain_position]
    _models_used_in_run.add(effective_model)
    call_scope = new_call_scope(op, retry_of=prev_call_id)
    try:
        return _dispatch(effective_model, call_scope, ...)
    except Exception as exc:
        detail = extract_provider_error(exc)                    # change 1
        fc = classify_provider_error(exc, detail)               # change 2
        emit llm_failure event
        if fc == "quota_billing_exhausted":
            if not _advance_chain(fc):
                raise  # chain exhausted
            continue  # next iteration uses new chain position
        elif fc in ("rate_limited", "overloaded", "timeout", "connection"):
            if attempt_on_current_model < max_app_retries:
                sleep(backoff(detail.retry_after_seconds, attempt_on_current_model))
                continue
            if not _advance_chain(fc):
                raise  # chain exhausted after retries
            continue  # next iteration uses new chain position
        else:  # auth_config, context_length, content_filtered, malformed_response, unknown
            raise   # surface immediately, no chain advance
```

`max_app_retries`: default 2 per chain entry (reuses `SUBGEN_RETRIES` concept; exact constant TBD by implementer). `attempt_on_current_model` resets to 0 each time `_chain_position` advances. Backoff: `min(retry_after_seconds or 2**attempt_on_current_model, 30)` seconds.

Chain walk path: `_advance_chain` emits one `llm_model_switch` event (original = exhausted entry, fallback = next entry) and advances `_chain_position`. The next iteration of the loop naturally dispatches to the new position.

*Alternative — separate fallback dispatch outside the loop*: more explicit but duplicates the dispatch, event, and parsing logic.

### D6. Effort translation for cross-provider fallback

When `effort_execute_fallback` is set, it is used as the effort for fallback calls. When not set, `effort_execute` is reused. For the default case (Gemini primary at `high`, Anthropic fallback), `high` is in both `THREE_EFFORT_LEVELS` and `FOUR_EFFORT_LEVELS`, so no clamping is needed. The clamping rule from D2 in the fable-downgrade design applies if the effort is not in the fallback model's `EFFORT_LEVELS` entry.

No new effort-translation machinery is needed: `_effort_kwargs()` already reads from `EFFORT_LEVELS` by model.

### D7. `llm_model_switch` event type

Add to `src/common/generation_events.py`:
- `LLM_MODEL_SWITCH = "llm_model_switch"` constant.

Add to `server/generate/event_protocol.py`:
- `ModelSwitchPayload(original_model, fallback_model, failure_class, purpose, agent)` dataclass. `failure_class` carries the `classify_provider_error` code that triggered the switch (e.g. `"quota_billing_exhausted"`, `"rate_limited"`) so the frontend can display per-code localized guidance. The old `reason` field name is replaced by `failure_class` to reuse the same stable taxonomy codes from change 2 without introducing an alias.

The event is emitted by `_advance_chain()` using the current call's `call_scope` (so it carries `call_id` and `operation_id` for attribution), delivered through `GenerationPublisher.publish()`. One event is emitted per chain hop; a two-hop run emits two events. It is an activity event; clients that do not handle it treat it as unknown-event-name (per the v2 decoder rules: unknown event names occupy their seq slot without causing a permanent gap).

### D8. Frontend evidence and display

`applyV2Event()` in `web/src/lib/generationEvidence.ts` handles `llm_model_switch` in the activity-event block: sets `QuestionEvidence.switchedToModel: string | null` (updated on each hop — the latest value is the model finally used) and `switchReason: string | null` (updated on each hop — reflects the most recent `failure_class`). A run-level `fallbackModelCount: number` selector counts questions with non-null `switchedToModel`.

`QuestionCard.tsx` renders an amber `role="status"` notice with `data-testid="evidence-model-switch-notice"` when `switchedToModel` is set.

`GenerationV2StatusLine` in `GenerationStatusBar.tsx` renders a count line with `data-testid="statusbar-fallback-model-count"` when `fallbackModelCount > 0`.

New i18n keys in `web/src/i18n/messages.ts` (keyed by `failure_class` code):
- `card.model_switched.quota_billing_exhausted` — zh-TW: `此題改用 {fallbackModel} 產生（主要模型配額已用盡）`
- `card.model_switched.rate_limited` — zh-TW: `此題改用 {fallbackModel} 產生（速率限制，重試後切換）`
- `card.model_switched.overloaded` — zh-TW: `此題改用 {fallbackModel} 產生（提供者過載）`
- `card.model_switched.timeout` — zh-TW: `此題改用 {fallbackModel} 產生（逾時後切換）`
- `card.model_switched.connection` — zh-TW: `此題改用 {fallbackModel} 產生（連線失敗後切換）`
- `card.model_switched.default` — fallback for any other code — zh-TW: `此題改用 {fallbackModel} 產生`
- `statusbar.fallback_model_count` — zh-TW: `{count} 題使用備援模型`

The frontend uses `failure_class` from the `llm_model_switch` event payload to select the specific key, falling back to `card.model_switched.default`.

### D9. Fallback and user-selected execute model

**Decision (user, 2026-10-01):** If the teacher explicitly set `model_execute` in the web form (per-request override), the fallback chain still applies when the feature is enabled. The operator enables the feature for resilience; a per-request model selection does not express intent to disable the fallback. The run's `_execute_chain` is built as `[request.model_execute] + config.model_execute_fallback`, so a teacher who picks `claude-opus-4-6` gets `[opus-4-6, gemini-3.1-pro-preview]` with the default chain, while the default `gemini-3.1-pro-preview` primary gets `[gemini, opus-4-6, gemini-skip]`.

The disclosure obligation still applies: one `llm_model_switch` SSE event is emitted per hop regardless of whether the primary model came from config or from the teacher's explicit selection.

### D10. Ordered fallback chain — on by default and chain exhaustion

**Decision (user, 2026-10-01):** `LLM_MODEL_EXECUTE_FALLBACK` is an ordered comma-separated list. The chain order is: first `claude-opus-4-6`, then `gemini-3.1-pro-preview`. The default value when the env var is **unset** is `claude-opus-4-6,gemini-3.1-pro-preview` — the feature is **on by default**. An operator who wants to disable it must set `LLM_MODEL_EXECUTE_FALLBACK=""` (explicit empty string kill switch).

When all entries in `_execute_chain` have been tried (or skipped as already-tried duplicates), `_advance_chain()` returns `False` and the retry loop raises the last exception. The error surfaced is the `failure_class` from the final failure — no special "chain exhausted" code is introduced.

**`metadata.fallback_from_model` for multi-hop runs:** stored as an ordered list of model ids tried before the final model actually produced a result (e.g. `["gemini-3.1-pro-preview", "claude-opus-4-6"]` for a two-hop run where both are exhausted before the question is generated — which cannot happen; more precisely: the list records every model that failed for this run before the model that succeeded). Formally: the list of all `_execute_chain` entries at positions `< final_position` that were actually dispatched (i.e. in `_models_used_in_run` and not the model that ultimately succeeded). The card notice and status bar always show the final model (latest `switchedToModel` value from the last `llm_model_switch` event).

## Risks / Trade-offs

- [Multi-instance process-local sticky state: different Railway instances discover quota independently and each burns app-level retries before falling back] → acceptable for two-instance staging; document in DEPLOYMENT.md; a future shared store (Redis) would coordinate instances.
- [Gemini compat quota/rate-limit distinction: both Gemini daily-quota and per-minute rate-limit 429s are classified `rate_limited` by change 2's classifier (conservative choice per its spec D4 and Open Questions). The `rate_limited` path retries then falls back — adds latency but produces no incorrect outcome. Once change-1 evidence settles whether the `RESOURCE_EXHAUSTED` body contains a disambiguating `message` pattern, change-2's classifier can promote Gemini daily quota to `quota_billing_exhausted` for immediate fallback without changing this change's decision rule.]
- [This change modifies requirement "Uniform envelopes and complete event attribution" in `generation-event-protocol`. The in-flight change `per-question-live-progress` also modifies that same requirement. Whichever change archives second must rebase its MODIFIED block onto the result of the first archive, so the merged requirement reflects both sets of changes without one overwriting the other.]
- [Fable-downgrade + quota-fallback interaction: if fable rewrite makes the primary model id identical to a chain entry, `_models_used_in_run` already contains it so that entry is skipped by `_advance_chain`; no infinite loop] → D3 documents the skip-already-tried rule; this covers both the fable interaction and the default config where primary = last chain entry.
- [Anthropic spend caps are org-wide; Gemini quota is per GCP project. This means the chain only provides quota isolation across providers/billing buckets — which the recommended chain `claude-opus-4-6,gemini-3.1-pro-preview` does (Anthropic → Google). A chain entirely within one provider/org will exhaust together. Document in DEPLOYMENT.md: for meaningful quota isolation, each entry should be from a different provider or a different billing account.]
- [With on-by-default, SDK `max_retries=0` + the app-level retry loop now apply to every correctly-configured deployment, not just opt-in ones. Operators who never set `LLM_MODEL_EXECUTE_FALLBACK` will see the change. The explicit-empty kill switch restores today's SDK-retry behaviour; document it in DEPLOYMENT.md and the README as the way to opt out.]
- [App retry loop adds latency under the 60-minute Bash timeout] → max 2 retries × 2 chain entries × max 30s backoff = bounded; max added latency ≈ (2+2)×30s = 120s per call site when both Gemini and Anthropic are saturated; acceptable per the worker timeout budget. In the normal (no-quota-error) case the loop adds zero latency.
- [Feature-on `max_retries=0` changes SDK behaviour for all Anthropic/Gemini calls in the run, including verify tier] → verify tier calls go through `_call()` but their purpose resolves to `model_verify`; the retry loop gate MUST check `execute_fallback_enabled AND purpose is execute-tier` before applying the loop. The retry loop applies only to execute-tier purposes.

## Migration Plan

1. Deploy: the default chain activates automatically when `LLM_MODEL_EXECUTE_FALLBACK` is unset and both `LLM_API_KEY` and `GEMINI_API_KEY` are present (existing requirement). Confirm with the startup log: `"execute fallback validated: claude-opus-4-6, gemini-3.1-pro-preview"`.
2. To disable: set `LLM_MODEL_EXECUTE_FALLBACK=""` (empty string) on the Railway backend service and redeploy. This restores today's SDK-retry behaviour exactly.
3. To override with a custom chain: set `LLM_MODEL_EXECUTE_FALLBACK=<model1>,<model2>` and redeploy; every entry is validated at startup.
4. To verify the chain works: run with `LLM_EXCHANGE_RETENTION_DAYS > 0` and trigger a quota error (or use a test harness); inspect the `llm_exchanges` rows and the SSE stream for `llm_model_switch` events.
5. Rollback to pre-feature binary: deploy without this code; `fallback_from_model` metadata fields in stored records are ignored by the old system.

## Open Questions

*(None — OQ1 and OQ2 resolved by user decision on 2026-10-01; see D9 and D10.)*
