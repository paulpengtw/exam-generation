## Purpose

Classifies every LLM provider failure into a stable, machine-readable code and surfaces an actionable, localized message to the teacher, distinguishing outcomes the teacher can recover from (wait and retry, reduce 題數) from outcomes only the operator can fix (revoked key, exhausted credit).

## ADDED Requirements

### Requirement: Stable failure taxonomy
The system SHALL classify every LLM provider exception into exactly one of the following stable codes before emitting any user-facing error. The classifier SHALL consume the normalized `ProviderErrorDetail` produced by the `llm-provider-diagnostics` capability (change 1). When `ProviderErrorDetail` is unavailable (change 1 not yet deployed), the classifier SHALL use the Python exception class as a best-effort input and produce `unknown` for any class it cannot determine.

Taxonomy:

| Code | Provider conditions covered |
|---|---|
| `auth_config` | Anthropic 401; OpenAI 401; Gemini compat 400 with gRPC `INVALID_ARGUMENT` and a key-related message; missing provider key (HTTP 422 from pre-flight) |
| `quota_billing_exhausted` | Anthropic 429 `rate_limit_error` with `details.error_code == "enforced_spend_limit_reached"`; Anthropic 400 `invalid_request_error` with message matching "specified API usage limits"; Anthropic 402 `billing_error`; OpenAI 429 with `error.code` in `{credit_balance_exhausted, organization_spend_limit_exceeded, project_spend_limit_exceeded, organization_usage_limit_exceeded}`; Gemini compat 402 |
| `rate_limited` | Anthropic 429 `rate_limit_error` without `enforced_spend_limit_reached`; OpenAI 429 with `error.code == "slow_down"` or no distinguishing code; Gemini compat 429 with gRPC `RESOURCE_EXHAUSTED` (conservative — see Open Questions); any plain 429 not matched above |
| `overloaded` | Anthropic 529 `overloaded_error`; any 503; any 5xx not matched above |
| `timeout` | SDK `APITimeoutError` or equivalent |
| `connection` | SDK `APIConnectionError` or equivalent network failure |
| `context_length` | Anthropic 413 `request_too_large`; SDK `LengthFinishReasonError`; any 413 |
| `content_filtered` | SDK `ContentFilterFinishReasonError`; Anthropic 403 with content-related body |
| `malformed_response` | Application-level JSON parse failure on model output; model returned structurally invalid content |
| `unknown` | Any exception that does not match the above conditions |

The Gemini compat endpoint returns list-wrapped bodies (`[{"error": {"code": <int>, "message": "...", "status": "<gRPC>"}}]`). The `exc.code` and `exc.type` SDK fields are always `None` for Gemini compat errors. The classifier SHALL read `exc.body[0]["error"]["status"]` to detect Gemini conditions. When `status == "RESOURCE_EXHAUSTED"`, the classifier SHALL return `rate_limited` (conservative) because daily quota and per-minute rate limit may be indistinguishable until change 1 produces real bodies. A task in `tasks.md` covers revisiting this classification when evidence is available.

#### Scenario: Anthropic monthly spend cap exhausted
- **WHEN** the provider raises a 429 with `error.details.error_code == "enforced_spend_limit_reached"`
- **THEN** the classifier returns `quota_billing_exhausted`

#### Scenario: Anthropic per-minute rate limit (no spend cap)
- **WHEN** the provider raises a 429 `rate_limit_error` without an `enforced_spend_limit_reached` discriminant
- **THEN** the classifier returns `rate_limited`

#### Scenario: Gemini compat invalid key (HTTP 400 INVALID_ARGUMENT)
- **WHEN** the Gemini compat endpoint returns HTTP 400 with gRPC status `INVALID_ARGUMENT` and a message containing "valid API key"
- **THEN** the classifier returns `auth_config`
- **AND** the response is not misclassified as a generic bad-request error

#### Scenario: Gemini compat 429 RESOURCE_EXHAUSTED
- **WHEN** the Gemini compat endpoint returns HTTP 429 with gRPC status `RESOURCE_EXHAUSTED`
- **THEN** the classifier returns `rate_limited` regardless of whether it is a daily quota or per-minute limit
- **AND** the user message for `rate_limited` notes that the cause may be a daily quota

#### Scenario: OpenAI credit balance exhausted
- **WHEN** the provider raises a 429 with `error.code == "credit_balance_exhausted"`
- **THEN** the classifier returns `quota_billing_exhausted`

#### Scenario: Connection failure (no HTTP)
- **WHEN** the provider raises an `APIConnectionError` (no HTTP status)
- **THEN** the classifier returns `connection`

#### Scenario: Unknown exception
- **WHEN** an exception does not match any taxonomy condition
- **THEN** the classifier returns `unknown`

#### Scenario: ProviderErrorDetail unavailable
- **WHEN** change 1 has not been deployed and only the Python exception class name is available
- **THEN** the classifier maps exception class to a best-effort code (e.g. `RateLimitError` → `rate_limited`) and returns `unknown` for classes it cannot map

### Requirement: Enriched error payload for generation and modification streams
Every SSE `error` event emitted by the generation stream and the modification stream SHALL include, alongside the existing `code` and `message` fields: `failure_class` (one of the ten taxonomy codes above), `provider` (the provider identifier: `anthropic`, `openai`, or `gemini`), `model` (the model id that was being called), and `tier` (the generation tier: `plan`, `execute`, `verify`, `correct`, or `unknown`). `retry_after_seconds` (a positive number) SHALL be included when the provider supplied a `retry-after` header value. Fields SHALL be `null` when the value is not available. No raw provider body, no API keys, and no authentication headers SHALL appear in the payload.

#### Scenario: Per-question worker failure with rate limit
- **WHEN** a per-question worker catches an `APIRateLimitError` while calling the execute model
- **THEN** the emitted SSE `error` event carries `code: "generation_failed"`, `failure_class: "rate_limited"`, the provider identifier, the model id, and `tier: "execute"`

#### Scenario: Stream-level failure
- **WHEN** the outer `event_generator` catches an exception
- **THEN** the emitted SSE `error` event carries `code: "stream_failed"`, a `failure_class` based on the exception, and the available context fields

#### Scenario: Modification stream failure
- **WHEN** the modification stream catches an LLM provider exception
- **THEN** the emitted SSE `error` event carries `code: "modification_failed"` and `failure_class` based on the classified exception

#### Scenario: retry_after_seconds included when available
- **WHEN** the provider returned a `retry-after` header and the value survives to the classifier
- **THEN** `retry_after_seconds` in the payload contains the numeric seconds value

#### Scenario: No raw provider body in payload
- **WHEN** any SSE `error` event is emitted
- **THEN** the payload SHALL NOT contain raw provider error body text, API keys, or authentication tokens

#### Scenario: Backward compatibility — old client reads only message
- **WHEN** an old client reads only the `code` and `message` fields of an `error` event
- **THEN** it receives the same `code` string and a non-empty `message` string as before this capability existed, with no behavior change

### Requirement: Structured error response for the core-question planner endpoint
When the `/api/plan-core-questions` endpoint encounters an LLM provider exception (not a `CandidateValidationError`), it SHALL return HTTP 502 with a JSON body containing `failure_class` (one of the ten taxonomy codes) and `message` (a safe human-readable string). No raw provider body SHALL appear in the response.

#### Scenario: Provider rate limit during planning
- **WHEN** the planner's LLM call raises a rate-limit exception
- **THEN** `POST /api/plan-core-questions` returns HTTP 502 with `{failure_class: "rate_limited", message: "<safe string>"}`

#### Scenario: Provider auth error during planning
- **WHEN** the planner's LLM call raises an authentication exception
- **THEN** `POST /api/plan-core-questions` returns HTTP 502 with `{failure_class: "auth_config", message: "<safe string>"}`

#### Scenario: Candidate validation error is unaffected
- **WHEN** the planner returns malformed candidates (a `CandidateValidationError`)
- **THEN** the endpoint still returns HTTP 502 with its existing `detail` string and does not carry `failure_class`

### Requirement: Localized actionable messages in both locales
The frontend SHALL map every `failure_class` code to a localized status label and a guidance line in both `en-US` and `zh-TW`. Teacher-actionable outcomes (`rate_limited`, `overloaded`, `timeout`, `connection`, `context_length`, `malformed_response`) SHALL direct the teacher to wait and retry or reduce 題數. Operator-only outcomes (`auth_config`, `quota_billing_exhausted`) SHALL direct the teacher to contact the administrator. `unknown` SHALL show the generic existing error fallback. For `rate_limited` where a Gemini `RESOURCE_EXHAUSTED` body was detected, the guidance SHALL note that the cause may be a daily quota limit, not a transient rate limit.

#### Scenario: Teacher sees rate-limited message
- **WHEN** the frontend receives `failure_class: "rate_limited"` with no `retry_after_seconds`
- **THEN** the displayed message is the localized `rate_limited` label with guidance to wait and retry

#### Scenario: Teacher sees quota-exhausted message
- **WHEN** the frontend receives `failure_class: "quota_billing_exhausted"`
- **THEN** the displayed message directs the teacher to contact the administrator in both zh-TW and en-US

#### Scenario: Teacher sees auth-config message
- **WHEN** the frontend receives `failure_class: "auth_config"`
- **THEN** the displayed message directs the teacher to contact the administrator

#### Scenario: Unknown failure class falls back to generic
- **WHEN** the frontend receives `failure_class: "unknown"` or a payload with no `failure_class` field
- **THEN** the displayed message is the existing generic error string (no regression for old servers)

#### Scenario: Both locales have keys for every class
- **WHEN** the i18n test suite runs
- **THEN** every `failure_class` code has a status label and a guidance line present in both `en-US` and `zh-TW` message objects

### Requirement: Localized message shown in existing error surfaces only
The localized failure message SHALL be displayed where errors already render: the `ProgressLog` error block (replacing the raw `errorMessage` string) and the per-question error area in the generation status bar. No new UI surfaces SHALL be added for this capability.

#### Scenario: ProgressLog shows localized message
- **WHEN** the generation ends with an `error` event carrying `failure_class: "rate_limited"`
- **THEN** the ProgressLog error block shows the localized `rate_limited` message, not the raw backend string

#### Scenario: No new surfaces
- **WHEN** a provider error occurs during generation
- **THEN** no new panels, modals, banners, or toasts appear that did not exist before this capability
