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
