## Purpose

Enable an operator to configure a single fallback model for the execute tier that activates automatically when the primary model encounters quota exhaustion, billing depletion, or persistent capacity failure, with every substitution surfaced to teachers through the SSE stream, question metadata, and the frontend UI.

## ADDED Requirements

### Requirement: On-by-default configuration with explicit kill switch
The system SHALL read `LLM_MODEL_EXECUTE_FALLBACK` as an ordered comma-separated list of fallback execute-tier model ids and SHALL read `LLM_EFFORT_EXECUTE_FALLBACK` as a single optional effort override that applies uniformly to all entries in the fallback chain. The system SHALL follow the same convention as other model-tier env vars (unset → default; explicitly empty → feature off):
- When `LLM_MODEL_EXECUTE_FALLBACK` is **unset**: the fallback chain defaults to `["claude-opus-4-6", "gemini-3.1-pro-preview"]` and the feature is active. This default works out of the box because both `LLM_API_KEY` (Anthropic) and `GEMINI_API_KEY` (Gemini) are already required by the default configuration.
- When `LLM_MODEL_EXECUTE_FALLBACK` is set to `""` (empty string): the feature is **disabled** (operator kill switch). SDK retry policy, provider request options, exchange records, SSE events, and stored run parameters SHALL be identical to those produced before this capability existed.
- When `LLM_MODEL_EXECUTE_FALLBACK` is set to a non-empty value: that comma-separated list becomes the chain.

#### Scenario: Unset env var activates default chain
- **WHEN** `LLM_MODEL_EXECUTE_FALLBACK` is not set in the environment
- **THEN** the fallback chain is `["claude-opus-4-6", "gemini-3.1-pro-preview"]` and the feature is active

#### Scenario: Explicit empty string disables feature
- **WHEN** `LLM_MODEL_EXECUTE_FALLBACK` is set to `""` (empty string)
- **THEN** the fallback feature is disabled and all execute-tier behaviour is byte-identical to a system without this capability

#### Scenario: Feature active with single operator entry
- **WHEN** `LLM_MODEL_EXECUTE_FALLBACK` is set to a single non-empty model id (e.g. `claude-opus-4-6`)
- **THEN** the fallback chain has one entry and the feature is active for all execute-tier calls

#### Scenario: Feature active with operator-specified chain
- **WHEN** `LLM_MODEL_EXECUTE_FALLBACK` is set to a comma-separated list (e.g. `claude-opus-4-6,gemini-3.1-pro-preview`)
- **THEN** the fallback chain has those entries in that order and the system walks the chain on successive failures

### Requirement: Startup validation with different policy for default vs. operator-supplied entries
When the fallback feature is enabled, the server SHALL validate at startup according to the source of the chain:
- **Operator-supplied chain** (env var explicitly set to a non-empty value): every entry MUST be in the allowed-models roster and have its provider API key present; a failing entry SHALL cause the server to emit an error identifying the entry and refuse to start.
- **Default chain** (env var unset): an entry whose provider key is absent or which is not in the allowed roster SHALL be dropped with one WARNING log at startup; the remaining entries form the active chain; if all entries are dropped the feature is disabled for this deployment. The server SHALL NOT refuse to start.

#### Scenario: Valid chain at startup (operator-supplied or default with all keys present)
- **WHEN** the fallback feature is enabled and every chain entry is in the allowed roster with its provider key present
- **THEN** the server starts normally and logs the validated chain

#### Scenario: Invalid operator-supplied entry at startup
- **WHEN** `LLM_MODEL_EXECUTE_FALLBACK` is explicitly set to a non-empty value and any entry is not in the allowed roster or its provider key is absent
- **THEN** the server emits an error identifying the misconfigured entry and refuses to start

#### Scenario: Default entry missing key — warn and drop
- **WHEN** `LLM_MODEL_EXECUTE_FALLBACK` is unset (default chain) and one default entry's provider key is missing (e.g. `LLM_API_KEY` absent so `claude-opus-4-6` cannot be used)
- **THEN** the server emits one WARNING dropping that entry and starts normally; the active chain contains only the remaining entries

#### Scenario: All default entries missing keys — feature disabled gracefully
- **WHEN** `LLM_MODEL_EXECUTE_FALLBACK` is unset and all default entries have missing keys
- **THEN** the server emits WARNINGs for each dropped entry, the feature is disabled, and the server starts normally

### Requirement: Decision rule for chain advancement
When the fallback feature is enabled, the system SHALL apply the following decision rule for every execute-tier call failure. Failure classes are the string codes produced by `classify_provider_error` from the `surface-llm-provider-errors` capability; this change SHALL NOT redefine or alias them.

- `quota_billing_exhausted`: the system SHALL advance the chain immediately without any retry of the current entry.
- `rate_limited`, `overloaded`, `timeout`, `connection`: the system SHALL retry the current chain entry up to a bounded number of times with exponential backoff honouring any `retry_after_seconds` value, then advance the chain after retries are exhausted. This path also covers Gemini daily quota while it is conservatively classified `rate_limited` by the change-2 classifier.
- `auth_config`: the system SHALL surface the error immediately as a generation failure and SHALL NOT advance the chain. Rotating to a different model on an auth failure would hide a revoked or invalid key from the operator.
- `context_length`, `content_filtered`, `malformed_response`, `unknown`: the system SHALL NOT advance the chain; these are question-level or application-level errors unlikely to be resolved by a different model. `unknown` is handled conservatively.

When the chain is exhausted (all entries tried or skipped as already-tried duplicates), the error from the last failure SHALL be surfaced. Chain entries with the same model id as a model already tried in this run SHALL be skipped during advancement. When the feature is disabled the SDK retries apply unchanged.

#### Scenario: quota_billing_exhausted triggers immediate chain advance
- **WHEN** an execute-tier call returns a failure classified as `quota_billing_exhausted` (Anthropic `enforced_spend_limit_reached`, OpenAI `credit_balance_exhausted` / `organization_spend_limit_exceeded`, Gemini 402, or billing-depleted equivalents)
- **THEN** the system advances to the next chain entry immediately without retrying the current model

#### Scenario: rate_limited triggers retry then chain advance
- **WHEN** an execute-tier call returns a failure classified as `rate_limited` and the configured maximum retries for the current entry are exhausted
- **THEN** the system advances to the next chain entry

#### Scenario: overloaded triggers retry then chain advance
- **WHEN** an execute-tier call returns a failure classified as `overloaded` (e.g. HTTP 503 or 529) and the configured maximum retries are exhausted
- **THEN** the system advances to the next chain entry

#### Scenario: timeout triggers retry then chain advance
- **WHEN** an execute-tier call returns a failure classified as `timeout` and the configured maximum retries are exhausted
- **THEN** the system advances to the next chain entry

#### Scenario: connection triggers retry then chain advance
- **WHEN** an execute-tier call returns a failure classified as `connection` and the configured maximum retries are exhausted
- **THEN** the system advances to the next chain entry

#### Scenario: auth_config is surfaced and chain is not advanced
- **WHEN** an execute-tier call returns a failure classified as `auth_config` (401, 403, or Gemini compat 400 INVALID_ARGUMENT with a key-related message)
- **THEN** the error is surfaced as a generation failure and no chain advancement occurs

#### Scenario: content_filtered failure stops without chain advance
- **WHEN** an execute-tier call returns a failure classified as `content_filtered`
- **THEN** it is treated as a question-level failure and the chain is not advanced

#### Scenario: context_length, malformed_response, unknown stop without chain advance
- **WHEN** an execute-tier call returns a failure classified as `context_length`, `malformed_response`, or `unknown`
- **THEN** the error is surfaced and the chain is not advanced

#### Scenario: Chain exhausted after all entries tried
- **WHEN** the system has advanced through all chain entries (or skipped duplicates) and the last entry also fails with a switching failure class
- **THEN** the system surfaces the last failure's error and failure_class; no special "chain exhausted" code is introduced

#### Scenario: Default config chain — gemini primary with recommended chain
- **WHEN** the primary execute model is `gemini-3.1-pro-preview`, `LLM_MODEL_EXECUTE_FALLBACK=claude-opus-4-6,gemini-3.1-pro-preview`, and `gemini-3.1-pro-preview` fails with `quota_billing_exhausted`
- **THEN** the system advances to `claude-opus-4-6`; if `claude-opus-4-6` also fails, the second chain entry `gemini-3.1-pro-preview` is skipped (already tried) and the chain is exhausted; the error is surfaced

#### Scenario: Teacher-selected model with recommended chain
- **WHEN** a teacher explicitly pins `model_execute=claude-opus-4-6`, `LLM_MODEL_EXECUTE_FALLBACK=claude-opus-4-6,gemini-3.1-pro-preview`, and `claude-opus-4-6` fails with `quota_billing_exhausted`
- **THEN** the system advances to the first chain entry; `claude-opus-4-6` is already tried so it is skipped; the system advances to `gemini-3.1-pro-preview` and uses it; if that also fails, the chain is exhausted and the error is surfaced

### Requirement: Chain position is sticky for the run
Once a run advances the chain, the chain position SHALL only move forward; it SHALL NOT move backward to retry earlier entries. All subsequent execute-tier calls in that run SHALL begin at the current chain position. The chain position SHALL be scoped to the run's shared LLM client instance. Distinct concurrent runs SHALL remain independent.

#### Scenario: Sibling workers inherit the chain position
- **WHEN** one execute-tier worker in a run advances the chain position
- **THEN** subsequent execute-tier calls in the same run begin at the new chain position without retrying earlier entries

#### Scenario: Concurrent runs are independent
- **WHEN** run A has advanced its chain and run B starts concurrently or afterwards
- **THEN** run B uses its own chain starting from the primary model, unaffected by run A's chain position

#### Scenario: Teacher-explicitly-selected model still triggers fallback
- **WHEN** a teacher has explicitly set `model_execute` in the web form and the primary call fails with a switching failure class
- **THEN** the fallback chain still applies and is disclosed; the run's chain is built as `[request.model_execute] + config.model_execute_fallback`

### Requirement: Scope of execute-tier fallback
The fallback SHALL cover every call resolved to the execute-tier model: the 文本生成器 call, each concurrent 子題產生器 call, flat math generation, HTML image generation (purpose `html_image`), and correction calls when `model_correct` is empty and inherits the execute model. The fallback SHALL NOT apply to the verify tier, the plan tier, the Anthropic web-search fact-check path, or image generation via `gpt_image`.

#### Scenario: 子題產生器 workers fall back
- **WHEN** a 子題產生器 call in a parallel batch fails with quota exhaustion
- **THEN** that call and all remaining execute-tier calls in the same run use the fallback model

#### Scenario: HTML image call falls back
- **WHEN** the HTML image generation call fails with a quota error and the fallback is configured
- **THEN** the image generation is retried on the fallback model

#### Scenario: Verify tier is unaffected
- **WHEN** a verify-tier call fails with any error
- **THEN** no execute-tier fallback substitution occurs for that call

### Requirement: Request options match the fallback model
When a call uses the fallback model, the provider request options that depend on the model (output-token ceiling, thinking parameters, temperature, effort translation) SHALL be those the system uses for the fallback model. An effort value not accepted by the fallback model SHALL be clamped to the nearest accepted value at or below the requested level. When `LLM_EFFORT_EXECUTE_FALLBACK` is set it overrides `LLM_EFFORT_EXECUTE` for fallback calls.

#### Scenario: Cross-provider fallback options
- **WHEN** the primary model is Gemini and the fallback is an Anthropic model
- **THEN** the fallback call uses Anthropic's request options including prompt caching and the Anthropic output ceiling, not Gemini's options

#### Scenario: Effort clamped on fallback
- **WHEN** the configured `LLM_EFFORT_EXECUTE` is a value not accepted by the fallback model
- **THEN** the fallback call uses the nearest accepted effort level at or below the requested value

### Requirement: Call identity preserved across fallback
Each retry and each fallback call SHALL have its own unique `call_id`. Every call after the first attempt for the same slot SHALL carry `retry_of_call_id` identifying the preceding failed call. The `operation_id` for a work unit SHALL remain unchanged across retries and the fallback switch for the same application-level slot.

#### Scenario: Fallback call identity
- **WHEN** a call fails and the fallback model is used for the same slot
- **THEN** the fallback call has a new `call_id`, carries `retry_of_call_id` referencing the failed primary call, and shares the same `operation_id` as the failed call

### Requirement: Model switch announced via SSE activity event per hop
When the fallback feature is enabled and a run advances the chain, the server SHALL emit one `llm_model_switch` activity event per chain hop, before each fallback call begins. The event payload SHALL carry `original_model` (the model whose failure triggered the hop), `fallback_model` (the next model to be tried), `failure_class` (the `classify_provider_error` code that triggered the hop), `purpose`, and `agent`. The event envelope SHALL conform to the v2 generation protocol uniform envelope contract. A two-hop run SHALL emit two events.

#### Scenario: quota_billing_exhausted hop event
- **WHEN** an execute-tier call fails with `quota_billing_exhausted` and the chain is advanced
- **THEN** the server emits one `llm_model_switch` event with `failure_class: "quota_billing_exhausted"`, `original_model` = exhausted model, `fallback_model` = next chain entry, before that next call begins

#### Scenario: rate_limited-then-advance hop event
- **WHEN** `rate_limited` retries for the current chain entry are exhausted and the chain is advanced
- **THEN** the `llm_model_switch` event carries `failure_class: "rate_limited"`

#### Scenario: Two-hop run emits two events
- **WHEN** the primary model fails then the first fallback entry also fails with a switching failure class, and there is a second fallback entry available
- **THEN** two `llm_model_switch` events are emitted, one per hop, each with its own `original_model`, `fallback_model`, and `failure_class`

#### Scenario: Chain exhaustion produces no additional event
- **WHEN** the last chain entry fails and the chain is exhausted
- **THEN** no additional `llm_model_switch` event is emitted; the last failure is surfaced as a generation failure

#### Scenario: Feature-disabled produces no switch event
- **WHEN** the fallback feature is disabled and an execute-tier call fails
- **THEN** no `llm_model_switch` event is emitted

### Requirement: Per-question fallback provenance in metadata
For each question where any execute-tier call used a fallback chain entry, the question output's `metadata` object SHALL include a `fallback_from_model` field as an ordered list of model ids that were tried before the model that finally succeeded (e.g. `["gemini-3.1-pro-preview"]` for a one-hop run, `["gemini-3.1-pro-preview", "claude-opus-4-6"]` for a two-hop run where the third chain entry succeeded). Questions generated entirely on the primary model SHALL have no `fallback_from_model` field. The `fallback_from_model` field SHALL NOT affect the content signature used for revision comparison.

#### Scenario: One-hop affected question metadata
- **WHEN** the primary model failed and the first fallback entry succeeded
- **THEN** the question's `metadata` contains `fallback_from_model: ["<primary_model>"]`

#### Scenario: Two-hop affected question metadata
- **WHEN** the primary and first fallback entry both failed and the second fallback entry succeeded
- **THEN** the question's `metadata` contains `fallback_from_model: ["<primary>", "<first_fallback>"]` in the order they were tried

#### Scenario: Unaffected question metadata
- **WHEN** all execute-tier calls for a question used the primary model (chain position never advanced)
- **THEN** the question's `metadata` does not contain a `fallback_from_model` field

### Requirement: Exchange records reflect the model that ran
`LLMExchange.model_used` SHALL record the model id that actually handled each call. The stored generation parameters (`params_json`) SHALL retain the originally configured `model_execute` value unchanged. The fallback provenance SHALL be captured at the per-question `metadata` level and via the `llm_model_switch` SSE event; it SHALL NOT overwrite `params_json`.

#### Scenario: Fallback call exchange record
- **WHEN** a fallback call completes and its exchange is recorded
- **THEN** the exchange row records the fallback model id as `model_used`

#### Scenario: params_json unchanged by fallback
- **WHEN** a run that experienced a fallback switch is stored
- **THEN** `params_json` still shows the originally configured `model_execute` value

### Requirement: Frontend notice for affected questions and batches
When a generation run includes questions that used the fallback model, the frontend SHALL render:
- An amber `role="status"` notice on each affected question card naming the fallback model and the reason code.
- A count line in the generation status bar when at least one question in the batch used the fallback model.

Both notices SHALL use localized strings present in both `zh-TW` and `en-US` locales. When no question used the fallback model, no notice SHALL appear.

#### Scenario: Affected card notice in zh-TW
- **WHEN** a question card's evidence records a `llm_model_switch` event
- **THEN** an amber `role="status"` notice is visible on that card with a zh-TW localized string naming the fallback model

#### Scenario: Status bar count
- **WHEN** at least one question in a batch has `switchedToModel` set in its evidence
- **THEN** the status bar renders a localized count of affected questions

#### Scenario: Unaffected batch has no notice
- **WHEN** no question in the batch used the fallback model
- **THEN** no fallback notice appears on any card or in the status bar
