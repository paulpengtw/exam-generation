## 1. Fixture bodies and ProviderErrorDetail data model

- [ ] 1.1 Create `tests/fixtures/provider_errors/` and add three fixture JSON files:
  - `anthropic_spend_cap_429.json` — verbatim Anthropic spend-cap body from research note §B.1.b: `{"type":"error","error":{"type":"rate_limit_error","message":"You have reached your API usage limits: your organization has crossed its monthly API usage threshold...","details":{"error_code":"enforced_spend_limit_reached"}}}`
  - `google_invalid_key_400.json` — verbatim Google list-wrapped body from research note §1.C appendix A.1: `[{"error":{"code":400,"message":"Please pass a valid API key","status":"INVALID_ARGUMENT"}}]`
  - `openai_credit_exhausted_429.json` — representative OpenAI credit-exhausted body: `{"error":{"type":"insufficient_quota","code":"credit_balance_exhausted","message":"You exceeded your current quota..."}}`
  Verify all three files parse as valid JSON (`python3 -m json.tool`).

- [ ] 1.2 Write failing tests in `tests/test_provider_error_extractor.py` covering:
  - Anthropic spend-cap body → `http_status=429`, `provider_error_type="rate_limit_error"`, `provider_error_code="enforced_spend_limit_reached"`, `retry_after_seconds=None`
  - Anthropic transient 429 with `retry-after: 30` header → `retry_after_seconds=30`
  - Google list-wrapped body (fixture `google_invalid_key_400.json`) → `http_status=400`, `provider_error_code=None`, `provider_error_status="INVALID_ARGUMENT"`, `provider_message="Please pass a valid API key"`
  - Google plausible quota 429 body (construct inline as `[{"error":{"code":429,"message":"Resource exhausted","status":"RESOURCE_EXHAUSTED"}}]`) → `http_status=429`, `provider_error_status="RESOURCE_EXHAUSTED"`
  - OpenAI credit-exhausted body (fixture `openai_credit_exhausted_429.json`) → `provider_error_code="credit_balance_exhausted"`
  - `APITimeoutError` (no `status_code`, no `body`) → `http_status=None`, all provider fields `None`
  - Body exceeding 4 096 bytes → `len(detail.raw_body_truncated) <= 4096`
  - `provider_error_code` and `provider_error_status` absent from a minimal exception → fields are `None`, no exception raised
  Verify all tests fail before any implementation.

- [ ] 1.3 Add `ProviderErrorDetail` as a `dataclasses.dataclass(frozen=True)` and `extract_provider_error(exc, *, provider: str, model: str) -> ProviderErrorDetail` to `src/llm_client.py`; verify tests from 1.2 pass.

## 2. llm_failure emission sites carry error detail

- [ ] 2.1 Write failing tests in `tests/test_provider_error_emission.py` asserting that after a provider exception:
  - `_call()` `llm_failure` event contains `http_status`, `provider_error_type`, `provider_error_code`, `provider_error_status`, `provider_message`, `request_id`, `retry_after_seconds`, `raw_body_truncated`
  - The original exception is re-raised unchanged (same type and message)
  - `generate_with_tools()` `llm_failure` event also contains those fields
  - `generate_with_google_search()` `llm_failure` event also contains those fields
  Use a fake client that raises a simulated `RateLimitError` with a known body. Verify all tests fail.

- [ ] 2.2 Update `_call()` (L795–805) to call `extract_provider_error` and spread `dataclasses.asdict(detail)` into `_emit_call_event`; verify tests from 2.1 pass for the `_call()` case.

- [ ] 2.3 Apply the same pattern to `generate_with_tools()` (L1362–1372); verify the `generate_with_tools()` test from 2.1 passes.

- [ ] 2.4 Apply to `generate_with_google_search()` (L1438–1448) and `generate_image()` (L1218–1228); verify all tests from 2.1 pass.

- [ ] 2.5 Add a guard-coverage test in `tests/test_provider_error_emission.py` that scans `src/llm_client.py` for `"llm_failure"` literal strings and asserts each one is preceded (within 10 lines) by an `extract_provider_error` call. This fails when a new emission site is added without the extractor.

## 3. WARNING log line

- [ ] 3.1 Write a failing test in `tests/test_provider_error_emission.py` using `caplog` (or `unittest.mock.patch` on `logging.Logger.warning`) that after a simulated `_call()` failure:
  - Exactly one WARNING log entry from `src.llm_client` is emitted containing `provider=`, `model=`, `http_status=`, `error_type=`, `error_code=`, `request_id=`
  - The log entry does NOT contain any string that looks like an API key (assert the fixture key `"sk-test-key"` or `"Bearer"` is absent)
  Verify the test fails before implementation.

- [ ] 3.2 Add `logger.warning(...)` call (per design §D3) to each of the four `llm_failure` sites; verify 3.1 passes.

- [ ] 3.3 Add a regression test asserting that the WARNING log line does not include `provider_message` or `raw_body_truncated` text (to guard the no-secrets invariant). Verify it passes.

## 4. ExchangeRecorder persists failed calls

- [ ] 4.1 Write failing tests in `tests/test_exchange_recorder_failure.py` covering:
  - `llm_failure` event with a prior `llm_request` in `_pending_by_call` → `_flush_failure` is called; one row is written with `response_body["error"]` containing the detail fields and `request_body` populated from the prior request
  - `llm_failure` event without any prior `llm_request` → one row with `request_body=None` and `response_body["error"]` present
  - `llm_failure` event's identity fields appear in `response_body["identity"]`
  - `prompt_tokens` and `completion_tokens` on the written row are `None`
  Verify all tests fail.

- [ ] 4.2 Add `_flush_failure` to `ExchangeRecorder` and extend `__call__` to handle `"llm_failure"` events; verify tests from 4.1 pass.

- [ ] 4.3 Add a test asserting that when `ExchangeRecorder` is not attached to the observer (simulating `LLM_EXCHANGE_RETENTION_DAYS=0`), no row-write method is called; verify it passes (this is structural — no recorder → no event → no row).

- [ ] 4.4 Add a test asserting that a write failure in `_flush_failure` logs a WARNING and does not propagate an exception; verify it passes (mirrors existing `_flush` behavior).

## 5. Regression: no behavior change on success path and no secrets

- [ ] 5.1 Run the full existing `llm_client` test suite (`tests/test_llm_client_*.py` and `tests/test_llm_client_operation_identity.py`) and verify all pass without change. Success-path events (`llm_request`, `llm_response`) must be byte-identical to pre-change output.

- [ ] 5.2 Add a test asserting that a successful `_call()` produces no `llm_failure` event and no WARNING log entry.

- [ ] 5.3 Add a test asserting that `ProviderErrorDetail` fields never expose the `api_key` value from `Config` — construct a detail from an exception whose `body` was contrived to include an API-key-shaped string and assert it is absent from `raw_body_truncated`.

## 6. Server-level integration

- [ ] 6.1 Add a server integration test in `tests/server/test_provider_error_persistence.py` that:
  - Drives a generation request through the FastAPI test client with a fake `LLMClient` that raises a `RateLimitError` with a known Anthropic spend-cap body
  - Asserts one `LLMExchange` row exists in the DB with `response_body["error"]["provider_error_code"] == "enforced_spend_limit_reached"`
  - Asserts `request_body` on that row is populated from the matching `llm_request` event
  Verify it fails before the recorder change is applied.

- [ ] 6.2 Verify 6.1 passes after tasks 4.1–4.2 are complete.

## 7. Verification and staging

- [ ] 7.1 Run `choom -n 500 -- uv run pytest tests/test_provider_error_extractor.py tests/test_provider_error_emission.py tests/test_exchange_recorder_failure.py` and verify all pass. Run at most 2–3 concurrent pytest lanes.

- [ ] 7.2 Run `choom -n 500 -- uv run pytest tests/server/test_provider_error_persistence.py tests/test_llm_client_operation_identity.py tests/test_llm_client_generate_with_tools.py tests/test_llm_client_openai_compat.py` and verify all pass.

- [ ] 7.3 Run `choom -n 500 -- uv run pytest tests/server/` to confirm no regressions in the server test suite.

- [ ] 7.4 Run `uv run ruff check src/ server/` and verify it is clean.

- [ ] 7.5 Run `openspec validate log-provider-error-body --strict` and verify it reports no errors.

- [ ] 7.6 **Staging verification (after deploy):** Force a Gemini quota-exhausted error on the staging instance (use a test GCP key with a minimal quota, or temporarily set `LLM_API_KEY` to an exhausted Gemini key and trigger one generate request). Then:
  - Query `llm_exchanges` for rows with `response_body ? 'error'`: `SELECT response_body FROM llm_exchanges WHERE response_body::jsonb ? 'error' ORDER BY created_at DESC LIMIT 5;`
  - Inspect `response_body["error"]["provider_error_status"]` and `raw_body_truncated` to determine whether a Gemini quota 429 uses `"RESOURCE_EXHAUSTED"` and whether it is distinguishable from a per-minute limit.
  - Record findings in `docs/research/2026-10-01-execute-tier-fallback-and-gemini-429-shape.md` under a new section **Part 1.F — Staging confirmation**. This settles the open question needed by change 3 (`execute-tier-model-fallback`).
