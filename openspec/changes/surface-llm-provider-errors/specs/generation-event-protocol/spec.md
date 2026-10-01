## ADDED Requirements

### Requirement: Error events carry stable failure class and safe context
Every SSE `error` event in the generation stream SHALL carry, alongside the existing `code` and `message` fields, a `failure_class` field containing one of the stable taxonomy codes defined in the `llm-error-messages` capability. The payload SHALL additionally include `provider`, `model`, `tier`, and `retry_after_seconds` when available, all `null` otherwise. The `code` field SHALL be preserved unchanged for backward compatibility with clients that predate this requirement. No raw provider body, no API keys, and no authentication material SHALL appear in any `error` event payload.

#### Scenario: Error event structure is additive
- **WHEN** the server emits a `generation_failed` or `stream_failed` error event
- **THEN** the payload contains `code`, `message`, and `failure_class` as top-level fields
- **AND** a client that reads only `code` and `message` receives the same values it would have received before this requirement

#### Scenario: Per-question error carries question context
- **WHEN** a per-question worker emits a `generation_failed` error event
- **THEN** the event context carries `question_id` and `index` as required by the envelope contract
- **AND** the payload carries `failure_class`, `provider`, `model`, and `tier`

#### Scenario: Batch-level error carries failure class
- **WHEN** a batch-planning failure emits a `batch_generation_failed` error event
- **THEN** the payload carries `failure_class` derived from the cause of the planning failure

#### Scenario: failure_class is always a string from the taxonomy
- **WHEN** any error event is emitted
- **THEN** `failure_class` is one of `auth_config`, `quota_billing_exhausted`, `rate_limited`, `overloaded`, `timeout`, `connection`, `context_length`, `content_filtered`, `malformed_response`, or `unknown`
- **AND** `failure_class` is never `null` or absent when the error event is emitted

#### Scenario: No provider secret in payload
- **WHEN** any error event is emitted after an authentication or key error
- **THEN** the `error` event payload contains no API key, no auth token, and no raw provider error body text

#### Scenario: Run-level exception emits error event before done sentinel (issue #956 Gap 1)
- **WHEN** a run-level exception (outside of per-question workers) terminates the generation stream
- **THEN** the run host loop emits an SSE `error` event with `code="stream_failed"` and `failure_class` derived from the exception via `classify_provider_error` BEFORE the `done` sentinel
- **AND** for `_TimeLimitExceededError`, `failure_class` is conservatively `"unknown"`

#### Scenario: failure_class persisted to generation_logs (issue #956 Gap 2)
- **WHEN** a generation run ends in `status="failed"`
- **THEN** the `generation_logs.failure_class` column stores the first resolved `failure_class` string (from a per-question error event or from the run-level exception handler, whichever fires first)
- **AND** `GET /api/runs/{id}` includes `failure_class` in the response body
- **AND** a reconnecting client reads `snapshot.failure_class` and renders the same localized error message as the live path

#### Scenario: started_invalid error event carries failure_class (issue #956 Gap 3)
- **WHEN** the generation manifest validation fails before any workers start
- **THEN** the `started_invalid` error event carries `failure_class="unknown"`
