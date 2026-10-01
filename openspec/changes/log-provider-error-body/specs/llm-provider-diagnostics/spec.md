## Purpose

Normalizes provider-specific error bodies from any LLM provider into a structured detail record, and ensures every failed call is captured in observer events, a WARNING log forwarded to Sentry, and a durable `llm_exchanges` database row — giving operators a queryable, bounded, and secret-free record of provider failures.

## ADDED Requirements

### Requirement: Provider error extraction
The system SHALL extract a structured detail record from any LLM provider exception before re-raising it. The record SHALL include: provider name, model id, HTTP status code (integer or `null` for non-HTTP failures such as timeout and connection errors), provider error type (e.g. Anthropic `error.type`, OpenAI/Google `error.status`), provider error code (e.g. `enforced_spend_limit_reached`, `quota_exceeded`, `RESOURCE_EXHAUSTED`), provider error message, request id from response headers where present, `retry-after` value in seconds (integer or `null` when absent), and a raw body string truncated to at most 4 096 bytes. The extractor SHALL NOT classify errors into user-facing codes.

#### Scenario: Anthropic rate-limit exception with spend-cap detail
- **WHEN** an Anthropic SDK `RateLimitError` is raised with an `error.details.error_code` of `enforced_spend_limit_reached`
- **THEN** the extracted detail has `http_status=429`, `provider_error_type="rate_limit_error"`, `provider_error_code="enforced_spend_limit_reached"`, `retry_after_seconds=null`, and `raw_body_truncated` contains the serialized error body

#### Scenario: Anthropic rate-limit exception without spend-cap detail
- **WHEN** an Anthropic SDK `RateLimitError` is raised without an `error_code` detail (transient per-minute limit)
- **THEN** the extracted detail has `http_status=429`, `provider_error_type="rate_limit_error"`, `provider_error_code=null`, and `retry_after_seconds` contains the numeric value of the `retry-after` header when present

#### Scenario: Google list-wrapped error body
- **WHEN** an OpenAI SDK exception is raised from the Gemini compat endpoint with a list-wrapped body `[{"error": {"code": 429, "message": "...", "status": "RESOURCE_EXHAUSTED"}}]`
- **THEN** the extracted detail has `http_status=429`, `provider_error_code=null` (the SDK sets this to null for list bodies), `provider_error_status="RESOURCE_EXHAUSTED"`, and `provider_message` set to the message from the first list element

#### Scenario: OpenAI credit-exhausted exception
- **WHEN** an OpenAI SDK `RateLimitError` is raised with `error.code` equal to `credit_balance_exhausted`
- **THEN** the extracted detail has `http_status=429` and `provider_error_code="credit_balance_exhausted"`

#### Scenario: Non-HTTP failure
- **WHEN** an `APITimeoutError` or `APIConnectionError` is raised (no HTTP response)
- **THEN** the extracted detail has `http_status=null`, `provider_error_type=null`, `provider_error_code=null`, and `retry_after_seconds=null`

#### Scenario: Raw body truncation
- **WHEN** the provider exception body, when serialized, exceeds 4 096 bytes
- **THEN** `raw_body_truncated` contains at most 4 096 bytes of the serialized body and the remainder is discarded

#### Scenario: No API keys or prompts in extracted detail
- **WHEN** a provider exception is extracted
- **THEN** the extracted detail SHALL NOT contain any API key, authorization header value, or request prompt text

### Requirement: llm_failure observer event carries error detail
Every `llm_failure` observer event emitted from any LLM call site SHALL include the fields of the `ProviderErrorDetail` extracted from the exception. The original exception SHALL be re-raised unchanged after the event is emitted.

#### Scenario: _call() failure carries detail
- **WHEN** `LLMClient._call()` raises an exception and an observer is registered
- **THEN** the emitted `llm_failure` event includes `http_status`, `provider_error_type`, `provider_error_code`, `provider_error_status`, `provider_message`, `request_id`, `retry_after_seconds`, and `raw_body_truncated`

#### Scenario: generate_with_tools() failure carries detail
- **WHEN** `LLMClient.generate_with_tools()` raises an exception and an observer is registered
- **THEN** the emitted `llm_failure` event includes the same `ProviderErrorDetail` fields

#### Scenario: generate_with_google_search() failure carries detail
- **WHEN** `LLMClient.generate_with_google_search()` raises an exception and an observer is registered
- **THEN** the emitted `llm_failure` event includes the same `ProviderErrorDetail` fields

#### Scenario: Original exception propagates unchanged
- **WHEN** an exception is caught, a `llm_failure` event is emitted, and the exception is re-raised
- **THEN** the type, message, and attributes of the re-raised exception are byte-identical to those of the original exception

### Requirement: Structured WARNING log on every failed call
Every failed LLM provider call SHALL produce one log entry at `WARNING` level containing the provider, model id, HTTP status, provider error type, provider error code, and request id. The entry SHALL NOT contain any API key, authorization header value, or request prompt text.

#### Scenario: WARNING log emitted on failure
- **WHEN** any LLM call fails
- **THEN** a `WARNING` log entry is emitted by `src.llm_client` containing `http_status`, `provider_error_type`, and `provider_error_code`

#### Scenario: WARNING log forwarded to Sentry
- **WHEN** Sentry is initialized with `LoggingIntegration(level=logging.WARNING)` (as in `server/observability.py`) and a LLM call fails
- **THEN** the WARNING log entry is captured as a Sentry event

#### Scenario: No secrets in WARNING log
- **WHEN** a WARNING log entry is emitted for a failed call
- **THEN** the entry does not contain the API key value or any content from the request prompt

### Requirement: Failed calls persisted as llm_exchanges rows
For every failed LLM call, when exchange persistence is enabled (`LLM_EXCHANGE_RETENTION_DAYS > 0`), the `ExchangeRecorder` SHALL write one `LLMExchange` row. The row SHALL record `generation_log_id`, `agent`, `purpose`, `model_used`, `exchange_order`, a non-null `response_body` containing the `ProviderErrorDetail`, and the call identity fields (`run_id`, `call_id`, `operation_id`, `retry_of_call_id`) preserved in `response_body["identity"]` following the existing convention. `request_body` SHALL be populated from the matching pending `llm_request` event when available, and left null otherwise.

#### Scenario: Failed call writes a row when persistence is enabled
- **WHEN** a LLM call emits `llm_request` then `llm_failure` and `LLM_EXCHANGE_RETENTION_DAYS > 0`
- **THEN** one `LLMExchange` row is written with `response_body` containing the `ProviderErrorDetail` and `request_body` from the matched pending request

#### Scenario: Failed call without a prior llm_request
- **WHEN** a `llm_failure` event arrives with no matching pending `llm_request`
- **THEN** one `LLMExchange` row is written with `request_body=null` and `response_body` containing the `ProviderErrorDetail`

#### Scenario: Persistence disabled by LLM_EXCHANGE_RETENTION_DAYS=0
- **WHEN** `LLM_EXCHANGE_RETENTION_DAYS` is `0` and a LLM call fails
- **THEN** no `LLMExchange` row is written

#### Scenario: Exchange recorder write failure does not mask the original exception
- **WHEN** writing the `LLMExchange` row fails (database unavailable)
- **THEN** the write failure is logged as a WARNING by the recorder, the original provider exception continues to propagate, and no additional exception is raised

#### Scenario: Row contains no API keys or prompts
- **WHEN** a `LLMExchange` row is written for a failed call
- **THEN** the row does not contain any API key value; `request_body.messages` contains only the summarized form used by the existing `llm_request` event, not the full prompt text

### Requirement: Extraction covers all three provider body shapes
The extractor SHALL correctly parse errors from Anthropic (dict body `{"type":"error","error":{"type":"...","message":"...","details":{}}`), OpenAI (dict body `{"error":{"type":"...","code":"...","message":"..."}}`), and Google list-wrapped (array body `[{"error":{"code":<int>,"message":"...","status":"<gRPC>"}}]`). For Google bodies, the extractor SHALL further inspect `details[]` entries for `QuotaFailure.violations[].quotaId` and `RetryInfo.retryDelay` when present.

#### Scenario: Anthropic body with details
- **WHEN** the Anthropic exception body contains `error.details.error_code`
- **THEN** `provider_error_code` is set to that value

#### Scenario: Anthropic body with RetryInfo in details
- **WHEN** the Anthropic exception body contains a `details` list entry with `@type` containing `RetryInfo` and a `retryDelay` field
- **THEN** `retry_after_seconds` is parsed from the `retryDelay` duration string

#### Scenario: Google body with QuotaFailure violations
- **WHEN** the Google list-wrapped body contains a `details[]` entry with `@type` containing `QuotaFailure` and a `violations` list
- **THEN** the first `quotaId` value from the violations is recorded in the extracted detail

#### Scenario: Unknown or malformed body
- **WHEN** the exception body is absent, not JSON-parseable, or of an unexpected type
- **THEN** the extractor returns a detail record with `provider_error_type=null`, `provider_error_code=null`, and `raw_body_truncated` set to the truncated string representation of the body
