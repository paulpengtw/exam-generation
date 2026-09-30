# Research: Execute-Tier Fallback and Gemini Compat-Endpoint 429 Body Shape

**Date:** 2026-10-01
**HEAD SHA:** dd9e6b82b5df874bb958cc6a778d41ab37c4a776
**Repo:** https://github.com/paulpengtw/exam-generation/tree/dd9e6b82b5df874bb958cc6a778d41ab37c4a776
**Branch:** feat/907-unique-saved-result

> **Scope:** Read-only. No code changes.
> **Builds on:** `docs/research/2026-10-01-llm-error-surfacing-and-key-rotation.md` (Section B, Tables B.2.b–B.2.c) and `docs/research/2026-10-01-block-fable-downgrade-to-opus.md`. Do not re-read those sections; all prior findings are cited below.

---

## Part 1 — Gemini compat-endpoint 429 body shape

### 1.A Persisted data: `llm_exchanges` table

**Can failed calls write a row?**

`server/generate/exchange_recorder.py`
([lines 26–29](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/exchange_recorder.py#L26-L29))
is explicit: *"If a request never gets a response (worker crashed), that row is
intentionally not written."* The recorder pairs events by `(run_id, call_id)` key
(`_pending_by_call`). An `llm_request` event is stored as pending when received; the
matching `llm_failure` event is **not** handled at all (only `llm_request` and
`llm_response` are handled in `__call__`). A provider exception means the `llm_response`
event is never emitted and therefore the pending request is never flushed to a DB row.

**Consequence:** quota and rate-limit errors produce **no `llm_exchanges` row**. Inspecting
the DB for a real Gemini quota-error body shape is structurally impossible — the evidence
trail does not exist.

**Local DB check:** `dev.db` at the repo root has `generation_logs` with 0 rows, confirming
no relevant history in this environment. (SELECT-only; no mutation.)

### 1.B Logs / Sentry

`sentry-cli` is installed and authenticated as `sentry.io@cpeng.me`.  The `sentry-cli
projects list` call returned `organization not found` for the `cpeng` slug, and the auth
token has `org:read` scope but lacks the needed project slug.  No `RateLimitError` events
from the Gemini path could be retrieved.

### 1.C Live probe — envelope shape

**A single probe request** was sent to the compat endpoint with a deliberately invalid key
and a one-word prompt. No real API key was used; no real quota was consumed.

```
POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
Authorization: Bearer invalid_test_key_for_envelope_shape
Content-Type: application/json
Body: {"model":"gemini-2.0-flash","messages":[{"role":"user","content":"hi"}]}
```

Raw response:

```
HTTP/2 400
content-type: application/json; charset=UTF-8
server-timing: gfet4t7; dur=11
...

[{
  "error": {
    "code": 400,
    "message": "Please pass a valid API key",
    "status": "INVALID_ARGUMENT"
  }
}
]
```

**Findings from the probe:**

1. **HTTP status is 400, not 401.** An invalid API key returns `400 INVALID_ARGUMENT` on the
   compat endpoint, not `401`. The OpenAI SDK maps this to `BadRequestError`, not
   `AuthenticationError`. This is Google-specific behaviour — the compat endpoint does NOT
   map to standard OpenAI HTTP status conventions for authentication errors.

2. **The body is a JSON array, not an object.** The top-level value is `[{...}]` — a
   single-element list wrapping the `{"error": {...}}` object. This is the **native Google
   API error format**, not the OpenAI `{"error": {"type": "...", "code": "..."}}` dict.

3. **`"status"` is a gRPC status name string**, e.g. `"INVALID_ARGUMENT"`. In Google's
   error taxonomy, quota errors use `"RESOURCE_EXHAUSTED"`. This is absent from the OpenAI
   error shape.

4. **`"code"` in the body is an integer** (HTTP numeric code, 400 / 429), not the string
   discriminant like OpenAI's `"credit_balance_exhausted"`. The body `"code"` and `"status"`
   fields are the only available discriminants.

**This is evidence about the envelope shape, not proof of what a quota 429 body contains.**
A quota-exhausted 429 would plausibly look like:
```json
[{"error": {"code": 429, "message": "Resource has been exhausted ...", "status": "RESOURCE_EXHAUSTED"}}]
```
A per-minute rate-limit 429 might also use `"status": "RESOURCE_EXHAUSTED"` or a different
gRPC status such as `"RATE_LIMIT_EXCEEDED"`. Whether these are distinguishable in the
`"status"` or `"message"` fields is **not confirmed** by this probe.

### 1.D SDK analysis: what `exc.body`, `exc.code`, `exc.type` contain for a list-wrapped body

Source: openai SDK 2.30.0 installed at `.venv/lib/python3.11/site-packages/openai/`
(upstream tag:
[openai/openai-python v2.30.0](https://github.com/openai/openai-python/blob/v2.30.0/src/openai/_client.py#L427-L458),
[_exceptions.py](https://github.com/openai/openai-python/blob/v2.30.0/src/openai/_exceptions.py#L31-L67)).

**Step 1 — `_make_status_error_from_response` parses the body as JSON:**
```python
body = json.loads(err_text)  # succeeds: list is valid JSON
```
`body` = `[{"error": {"code": 429, "message": "...", "status": "RESOURCE_EXHAUSTED"}}]`

**Step 2 — `_make_status_error` extracts the inner `"error"` key:**
```python
data = body.get("error", body) if is_mapping(body) else body
```
`is_mapping([...])` = `False` → `data = body` (the list itself, unchanged).

**Step 3 — `APIError.__init__` extracts `code`/`type`/`param`:**
```python
if is_dict(body):          # False for a list
    self.code = body.get("code")
    ...
else:
    self.code = None
    self.param = None
    self.type = None
```

**Result:** For every error from the Gemini compat endpoint:
- `exc.code` = **`None`** (always — the body is a list, not a dict)
- `exc.type` = **`None`** (always)
- `exc.body` = **the raw list** `[{"error": {"code": <int>, "message": "...", "status": "<gRPC_status>"}}]`
- `exc.message` = the `err_msg` string (`"Error code: 429 - [{'error': {...}}]"`)
- `exc.status_code` = HTTP status code (e.g. `429`)

**Reading quota vs rate-limit via the OpenAI SDK requires body parsing:**
```python
# Application-level code to distinguish quota from rate limit on Gemini compat path
if isinstance(exc.body, list) and exc.body:
    inner = exc.body[0].get("error", {}) if isinstance(exc.body[0], dict) else {}
    google_status = inner.get("status", "")   # "RESOURCE_EXHAUSTED"
    body_code = inner.get("code", 0)          # 429
    message = inner.get("message", "")
```

Neither `quota_exceeded` nor `rate_limit_exceeded` (the OpenAI-shaped Gemini codes cited
in the prior note as the **native** API codes) survive the compat shim in the standard
`exc.code` / `exc.type` fields. The gRPC `status` string and the integer `code` in the
list body are the only programmatic discriminants available.

**Comparison: what the same probe returned for the Anthropic SDK (0.104.1):**
The Anthropic `_exceptions.py`
([upstream v0.104.1](https://github.com/anthropics/anthropic-sdk-python/blob/v0.104.1/src/anthropic/_exceptions.py))
uses a nearly identical pattern but parses `body["error"]["type"]` and
`body["error"]["details"]["error_code"]` — those work because Anthropic's error body is
a proper `{"error": {...}}` dict. The compat-path body's list wrapper breaks the analogous
parsing in the OpenAI SDK.

### 1.E Verdict: **Partially settled**

| Claim | Status |
|---|---|
| Gemini compat endpoint uses list-wrapped body, not OpenAI dict | **Confirmed** by live probe |
| HTTP status for an invalid key is 400 (not 401) | **Confirmed** by live probe |
| `exc.code` and `exc.type` are always `None` for Gemini compat errors | **Confirmed** by SDK source reading |
| `exc.body` contains the raw list and is accessible | **Confirmed** by SDK source reading |
| A quota 429 uses `"status": "RESOURCE_EXHAUSTED"` | **Plausible** but NOT confirmed (no real quota-exhausted response captured) |
| Daily quota (`RESOURCE_EXHAUSTED`) vs per-minute limit are distinguishable by `status` field | **Unknown** — may both use `RESOURCE_EXHAUSTED` |
| `retry-after` header is absent on quota 429 from Gemini compat | **Unknown** |

**Implication for the "never rotate on 401/403" rule:** The compat endpoint returns HTTP
400 `INVALID_ARGUMENT` (not 401) for an invalid API key. A retry-decision rule written as
"do not rotate on 401/403" must be extended to also treat Gemini compat HTTP 400 with
`"status": "INVALID_ARGUMENT"` (or any message containing "valid API key") as an
auth/config error that requires operator action, not a retriable transient failure.

**Cheapest concrete step to settle it:**

Add one `logger.warning` line inside the `llm_failure` emission block of `_call()` at
[`src/llm_client.py` lines 795–804](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L795-L804):

```python
except Exception as exc:
    if self._observer and call_scope is not None:
        self._emit_call_event(
            "llm_failure",
            call_scope,
            purpose=purpose,
            agent=agent,
            model=model,
            error_type=type(exc).__name__,
        )
    # ← ADD THIS:
    logger.warning(
        "llm_failure detail: http_status=%s body=%r",
        getattr(exc, "status_code", None),
        getattr(exc, "body", None),
    )
    raise
```

The next time a Gemini compat quota error occurs in staging, this will write the raw body
to the application log (which Sentry captures), settling whether `status` is
`RESOURCE_EXHAUSTED` for both cases or differs.

---

## Part 2 — Design research for the visible execute-tier fallback

### 2.A Where the execute tier is resolved and called

**Config:**
- `src/config.py::Config.model_execute`
  ([line 52](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/config.py#L52)) —
  default `DEFAULT_MODEL_EXECUTE = "gemini-3.1-pro-preview"`
  ([line 13](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/config.py#L13)).
  Read from `LLM_MODEL_EXECUTE` env var at
  ([line 98](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/config.py#L98)).

- `src/llm_client.py::LLMClient._model_for_purpose()`
  ([lines 543–555](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L543-L555)):
  purposes that are not in `_VERIFY_PURPOSES` or `_CORRECT_PURPOSES` fall through to
  `return self.config.model_execute`. This includes `"execute"`, `"html_image"`,
  `"sub_generator"`, and `"batch"`.

**Client construction:**
- Anthropic: `self.client = Anthropic(api_key=config.api_key, base_url=..., [no max_retries override])`
  ([lines 435–438](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L435-L438)) →
  SDK default `max_retries=2` applies.
- Gemini/OpenAI compat: `OpenAI(api_key=..., base_url=..., timeout=...)` lazy-built in
  `_openai_compat_client()` ([line 631](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L631)),
  also no `max_retries` override → SDK default `2` applies.

**Model-dependent logic in `_call()`:**

1. `resolve_provider(model)` maps the model string to a provider; Gemini prefix → `"gemini"`
   which selects the compat OpenAI client.
2. `_anthropic_output_kwargs(model)` controls `max_tokens` and adaptive thinking
   ([lines 41–45](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L41-L45)). A fallback from a Gemini model to
   an Anthropic model changes the provider branch and max-tokens ceiling.
3. Effort translation: Gemini gets `reasoning_effort` (3-level); Anthropic gets
   `extra_body.output_config.effort`. A fallback across providers would need effort
   re-translation. `EFFORT_LEVELS` in
   [`src/config.py` lines 37–44](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/config.py#L37-L44)
   maps model → allowed effort levels; `gemini-3.1-pro-preview` supports only
   `THREE_EFFORT_LEVELS` (no `max` or `xhigh`), while `claude-opus-4-6` supports
   `FOUR_EFFORT_LEVELS` (no `xhigh`).
4. Prompt caching: the Anthropic path in `_generate_streaming()` adds ephemeral
   `cache_control` on the system prompt. The compat path does not. A fallback from
   Gemini to Anthropic activates prompt caching automatically.
5. Temperature: `_accepts_sampling(model)` gates temperature. Gemini compat calls
   currently do not use temperature because the repo sends Gemini at its default.

**Execute-tier call sites that should be covered by a fallback:**

| Call site | File | Purpose | Notes |
|---|---|---|---|
| Math flat question `generate_json()` | `src/cli.py` | `"execute"` | Covered by `_call()` guard |
| Math/SS/NS 文本生成器 `generate_json()` | `src/common/generation_core.py` | `"execute"` | Covered by `_call()` guard |
| N parallel 子題產生器 `generate_json()` | `src/common/generation_core.py` | `"sub_generator"` | Covered; workers share one `LLMClient` per `_RunContext` |
| HTML image `_generate_html_via_llm()` | `src/renderer.py` line 524 | `"html_image"` | Covered (purpose resolves to execute model) |
| Corrector (inherits execute) | `src/corrector.py`, `src/social_studies/corrector.py`, `src/natural_sciences/corrector.py` | `"correct"` | `model_correct = ""` → inherits execute at call time; covered |

**Execute-tier call sites that should NOT be covered:**

| Call site | Reason |
|---|---|
| Plan tier (`model_plan`; default `claude-opus-4-6`) | Separate tier; failures are not Gemini quota-related by default |
| Verify tier (`model_verify`; default `claude-opus-4-6`) | Separate tier; already on Anthropic by default |
| Anthropic web-search fact-check (`generate_with_tools()`) | Uses verify tier model; bypasses `_call()`; if verify is Anthropic, no Gemini quota risk |
| Image generation (`generate_image()`) | Uses `IMAGE_MODEL`/`IMAGE_API_KEY`; separate client; not execute-tier |

### 2.B Per-request model selection path and fallback model admission

**Admission flow** (server path):

1. `_check_generation_admission(params, config)` at
   [`server/generate/routes.py` lines 448–482](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/routes.py#L448-L482)
   calls `_check_model_allowed(params.model_execute, config, "model_execute")`, which
   validates against `config.llm_models_allowed`. This runs **before** any LLM call.

2. `service.py::_setup_run_context()` at
   [lines 276–286](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/service.py#L276-L286)
   merges per-request params into `client_config` via `dataclasses.replace()`.

**The fallback model is chosen at runtime after a quota error, not at admission time.**
The pre-flight `_check_generation_admission` does not cover the fallback model. However,
the fallback model must itself be an API-reachable model and have its API key present.
The `_check_provider_key_for_model()` check in admission validates key presence for the
primary model; a similar check should run at operator config-load time for the fallback model.

**Proposed env var shape:**

```
LLM_MODEL_EXECUTE_FALLBACK=claude-opus-4-6
```

Mirrors the `LLM_MODEL_EXECUTE` naming convention. Add `model_execute_fallback: str = ""`
to `Config` in
[`src/config.py`](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/config.py),
read from `os.environ.get("LLM_MODEL_EXECUTE_FALLBACK", "")`. Empty = no fallback
(current behaviour).

The `_DEFAULT_MODELS_ALLOWED` roster at
[`server/config.py` lines 38–45](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/config.py#L38-L45)
already includes `claude-opus-4-6` and `claude-sonnet-4-6`. The fallback model must be
in this roster (or added via `LLM_MODELS_ALLOWED` env var) so `_check_model_allowed`
admits it in future pre-flight checks for the fallback tier.

**Effort compatibility when falling back from Gemini to Anthropic:**

`gemini-3.1-pro-preview` supports `three_effort_levels` (`low/medium/high`).
`claude-opus-4-6` supports `four_effort_levels` (`low/medium/high/max`).
The fallback inherits the same `effort_execute` value from the config, which for the
default (`"high"`) is valid on both. If an operator sets `effort_execute=max`, the
pre-flight check validates it against the primary Gemini model — and would reject it
with a 422 error because `max` is not in `THREE_EFFORT_LEVELS`. So effort mismatches
are caught at admission, not at fallback time, for the current admission design.

### 2.C Identity and provenance

**`OperationScope` / `CallScope` model** (issue #743):

Each real provider dispatch in `_call()` allocates a fresh `CallScope` with a unique
`call_id` via `new_call_scope(operation_scope, retry_of_call_id=retry_of_call_id)` at
[`src/llm_client.py` lines 757–765](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L757-L765).

A fallback call after a quota error should use:
- **Same `operation_id`** for the same application-level work unit (the 子題 slot or 文本 call).
  A fallback is not a separate attempt at a different unit; it is a retry of the same unit
  with a different model.
- **New `call_id`** — each provider dispatch gets its own immutable identity.
- **`retry_of_call_id = <original_failed_call_id>`** — this is the correct field for
  "same operation, new provider call retrying the original failed call."
  The `CallScope` model already supports this via the `retry_of_call_id` field.
- **New `OperationScope` is NOT needed** for a model fallback within the same slot; it would
  be appropriate only if the fallback were a "redo" of an already-completed slot (that is
  `supersedes_operation_id`). For an in-flight quota failure replaced by a fallback call,
  `retry_of_call_id` on the same operation is the correct identity.

**`ExchangeRecorder` and `LLMExchange.model_used`:**

`ExchangeRecorder._flush()` at
[`server/generate/exchange_recorder.py` line 212](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/exchange_recorder.py#L212)
sets `"model_used": str(source.get("model", ""))` from the `llm_request` event.
Since the fallback call emits a new `llm_request` event with the fallback model id, the
exchange row for the fallback call would correctly record the model that actually ran.
The failed primary call emits only `llm_request` and `llm_failure` — no row is written
(see §1.A). The failed call's identity (call_id, model) is therefore recorded only in the
`llm_failure` observer event, not persisted to the DB.

**`params_json` on `GenerationLog`:**

`params_json` is persisted from `params.model_dump()` at
[`server/generate/routes.py` lines 495–502](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/routes.py#L495-L502)
**before** workers start. It records the originally requested `model_execute`, not the
fallback. The same gap exists in the fable-downgrade design (prior note §3, Option A).

**Proposed provenance record:**

The fable-downgrade openspec (`openspec/changes/fable-downgrade-switch/proposal.md`)
proposes a `model_substitutions` field in `params_json`. A visible fallback should
emit a similar record, but on the question/小題 level rather than the run level, because
the fallback affects only the worker(s) that hit quota. Suggested location: the `metadata`
sidecar dict on each question output, alongside the existing `model_used` field (if
any), with a `fallback_from_model` key. This is stripped from the content signature
(see `CONTENT_SIGNATURE_EXCLUDED_KEYS` in
[`src/common/generation_events.py` lines 13–29](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/common/generation_events.py#L13-L29)),
so it does not affect deduplication or revision comparisons.

### 2.D "Visible" — SSE v2 protocol and frontend

**What the current SSE v2 protocol can carry:**

- `llm_request` activity event: carries `model`, `agent`, `purpose`, `call_id`,
  `operation_id`. Already visible in the stream and recorded in `ExchangeRecorder`.
- `llm_failure` activity event: carries `model`, `agent`, `purpose`, `error_type`,
  `call_id`. Already delivered to the frontend via the `GenerationStatusBar` progress
  mechanism.
- `stage` activity event: carries free-form `stage` string; used for pipeline progress.
- `question_terminal`: carries `termination_reason`, `delivery_status`, `review.status`.
  Does NOT carry a model field.

**Gap:** There is no SSE event type for "model switched due to quota error". The frontend
currently handles `llm_failure` in `generationEvidence.ts`
([lines 555–558](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/web/src/lib/generationEvidence.ts#L555-L558))
by setting `call.status = "failed"` on the per-call tracking — it does not extract a
fallback model or show any switched-model notice.

**Proposed: new `llm_model_switch` activity event** (server-side emitted in `_call()` after
the quota error is classified and before the fallback call begins):

```python
self._emit_call_event(
    "llm_model_switch",
    call_scope,                    # original failed call's scope
    original_model=model,          # e.g. "gemini-3.1-pro-preview"
    fallback_model=fallback_model, # e.g. "claude-opus-4-6"
    reason="quota_exhausted",      # structured code, not prose
    purpose=purpose,
    agent=agent,
)
```

On the frontend, `applyV2Event` in `generationEvidence.ts` would handle `llm_model_switch`
in its activity-event block
([lines 543–557](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/web/src/lib/generationEvidence.ts#L543-L557))
and store `switchedModel` in per-question evidence state. `QuestionCard.tsx` would render
an amber `role="status"` notice `"此題改用 X 模型產生 (已切換：原因)"` using new i18n keys.

Alternatively, the `stage` event type could carry this information as an informal status
update without a schema change — but that loses the structured `original_model`,
`fallback_model`, and `reason` fields, making the frontend extraction brittle.

**New i18n keys needed** (both `en-US` and `zh-TW` in
[`web/src/i18n/messages.ts`](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/web/src/i18n/messages.ts) _(file has uncommitted local changes)_):

```
card.model_switched_quota:   "Switched to {fallbackModel} (primary quota exhausted)"
card.model_switched_transient: "Switched to {fallbackModel} after provider failure"
statusbar.model_switch_notice: "{count} question(s) used fallback model"
```

### 2.E Retry policy and SDK hooks

**Current state:**

Both SDKs retry 429 and >=500 twice (Anthropic: `DEFAULT_MAX_RETRIES=2` in
`_constants.py`; OpenAI: `DEFAULT_MAX_RETRIES=2` in `_base_client.py`). Both
`_should_retry()` implementations are body-blind:

```python
# Identical pattern in both SDKs (anthropic 0.104.1, openai 2.30.0):
if response.status_code == 429:
    return True    # ← no body inspection for quota vs rate-limit
if response.status_code >= 500:
    return True
```

Neither SDK checks `x-should-retry: false` response header either (it only short-circuits
on `true`). The SDK burns 2 retries on every quota-exhausted 429 before propagating the
exception to the application.

**Options to stop SDK retries on quota errors:**

1. **`max_retries=0` on client construction** — pass `max_retries=0` to both `Anthropic()`
   and `OpenAI()` constructors. Completely disables SDK-level retry. The application owns
   all retry decisions. Requires the application to re-implement exponential backoff for
   transient 429s and 5xx errors.

2. **`x-should-retry: false` header** — the Anthropic API may return this on quota-exhausted
   429s (not confirmed; the SDK does honour it). If Google adds it to Gemini compat endpoint
   quota responses, the SDK would stop retrying automatically. Not under application control.

3. **Subclass `_should_retry`** — both SDKs accept a client subclass. Overriding
   `_should_retry(self, response)` to inspect `response.text` for quota signals is possible
   but fragile and not an officially supported extension point.

4. **`httpx.Client` with a custom event hook** — attach an `httpx` event hook on the
   response that raises immediately on quota body patterns, bypassing the SDK retry loop
   entirely. Fragile; couples to SDK internals.

**Recommended:** `max_retries=0` on both clients, with an explicit application-level retry
loop in `_call()` that:
- Classifies the exception on first failure (using body inspection for Gemini compat and
  `error.details.error_code` for Anthropic per the prior note)
- Does not retry quota-exhausted errors; instead switches to the fallback model immediately
- Retries transient 429s and 5xx errors up to N times with exponential backoff (replacing
  the lost SDK retries)
- Does not retry 401/403 (operator must fix config)

This is consistent with the "rotation/retry decision rule" in the prior note (Section C
recommendation table).

### 2.F Interaction with fable-downgrade proposal

The fable-downgrade openspec (`openspec/changes/fable-downgrade-switch/proposal.md`)
**has not been implemented** — `grep -rn FABLE_DOWNGRADE src server` finds no code. It
exists only as a proposal. The analysis below is forward-looking: it describes the
constraint that would apply if and when that proposal is implemented.

The proposed fable-downgrade feature defines a **static substitution** triggered by env var
at call construction time — all calls to any fable model are silently redirected. The
proposal states: *"The substitution is silent to the requester: no HTTP 422, no change to
the allowed-models roster, no change to the model dropdown."*

A visible execute-tier fallback triggered at runtime by a quota/billing error is
**structurally different:**

| Property | Fable downgrade (proposed) | Visible quota fallback |
|---|---|---|
| Trigger | Env var flag, applies to every call | Provider quota/billing error at runtime |
| Scope | All four tiers, all call sites | Execute tier only (initially) |
| Visibility | Silent (records differ; no SSE event) | Explicit SSE event; i18n notice in UI |
| `params_json` honesty | Gap: shows fable but opus ran | Same gap; mitigated by per-question `metadata.fallback_from_model` |
| Compliance with "no silent model substitution" principle | Acknowledged gap (per proposal) | Compliant — substitution is surfaced |

No existing ADR or `CONTEXT.md` rule prohibits a *visible* fallback. The implicit
constraint is against **silent** substitution (prior note §C.4: *"Any fallback model
substitution must be explicit — surfaced in the SSE stream and in `params_json`"*). A
visible fallback with an SSE event, UI notice, and `metadata.fallback_from_model` complies.

**If/when the fable-downgrade proposal is implemented:** both guards would operate inside
`_call()` on the model string. The quota-fallback must operate on the **post-rewrite
effective model** (after any fable→opus substitution), not on the originally requested
model string. To avoid two independent rewrite layers that can interact unpredictably, the
two guards should share a **single substitution point** at the top of `_call()` — a
`_resolve_effective_model(model, purpose)` method that applies both the static fable rewrite
and the runtime quota-fallback state in one place. Today there is no fable rewrite guard to
order against, so the quota-fallback guard can be placed freely inside `_call()`.

### 2.G Existing tests that pin current behaviour and need updating

Tests that assert the current `generation_failed` code shape or the exact model admission
roster would need updating when a fallback is added:

| File | Line(s) | What it pins | Change needed |
|---|---|---|---|
| `tests/server/test_generate_routes.py` | 2069–2070 | `code="generation_failed"` for ValueError | Add test variant for `RateLimitError` → new code (e.g. `rate_limit_exhausted`) |
| `tests/server/test_generate_routes.py` | 2112, 2286 | `"generation_failed"` in response text | Same |
| `tests/server/test_generation_publisher.py` | 653 | `code="generation_failed"` | Same |
| `tests/test_llm_client_operation_identity.py` | 72 | `llm_failure` event has no `fallback_model` field | Need new test for fallback event emission |
| `tests/test_default_model_tiers_split.py` | 116 | `_DEFAULT_MODELS_ALLOWED` exact roster | Add `LLM_MODEL_EXECUTE_FALLBACK` to env-var coverage |
| `tests/server/test_config_llm_models_allowed.py` | 29, 38 | `llm_models_allowed` roster | If fallback model is auto-appended to the roster, new test cases needed |

### 2.H Related GitHub issues

From `gh issue list --repo paulpengtw/exam-generation --state all --search "fallback OR quota OR 429 OR rate limit OR #938"`:

- **#938 (OPEN):** "Expose actionable Gemini provider failures" — tagged `bug, backend, frontend, ready-for-agent`. Directly motivated by this research. The visible fallback (Part 2 of this note) is the medium-term fix described in the prior note §C.4.
- **#927 (OPEN):** "Planner reports a failed provider call as a provider failure, not as malformed candidates" — a related misclassification that would be exposed more visibly once structured error surfacing is in place (prior note, open question 7).
- **#928 (referenced in prior note):** Sentry raw provider exception deduplication — would be improved when error enrichment produces structured codes.
- **Issue #429 (CLOSED):** An earlier issue about live verdict-only agent, not related.
- **Issue #27 (CLOSED):** slowapi rate limits on endpoints — `tests/server/test_rate_limit.py` tests this path, which is distinct from LLM-provider rate limits.

---

## Part 3 — Multi-key pools (brief)

### 3.A Env shape options

Three options for operator key specification:

| Shape | Format | Notes |
|---|---|---|
| Two-key fallback | `LLM_API_KEY_FALLBACK=<key2>` | Minimal; only two keys; mirrors `LLM_MODEL_EXECUTE_FALLBACK` naming |
| Comma-separated pool | `LLM_API_KEYS=key1,key2,key3` | Flexible pool size; replaces `LLM_API_KEY` or supplements it |
| Indexed env vars | `LLM_API_KEY_0=…`, `LLM_API_KEY_1=…` | Standard shell pattern; clean; harder to enumerate dynamically |

Given that the use case ("only when keys are on separate billing accounts") limits the
useful pool size to 2–3, the `LLM_API_KEY_FALLBACK` / `GEMINI_API_KEY_FALLBACK` pairing
with the existing `LLM_API_KEY` / `GEMINI_API_KEY` is the simplest shape that covers
the real-world operator case.

### 3.B Where keys are read and clients cached

**Anthropic client:**
`self.client = Anthropic(api_key=config.api_key)` is built **eagerly** at `LLMClient.__init__`
([line 435](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L435)).
For a multi-key pool, multiple `Anthropic` client instances would need to exist, e.g.
`self._anthropic_clients: list[Anthropic]`. Since the Anthropic client is stateless
(no token caching, no persistent connection multiplexing beyond httpx connection pools),
swapping the client at call time is safe.

**OpenAI-compat (Gemini) client:**
`_openai_compat_client(provider)` builds the `OpenAI` client **lazily** on first call,
keyed by provider name in `self._compat_clients: dict[str, OpenAI]`
([lines 623–633](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L623-L633)).
For a multi-key pool, the key would need to be `(provider, key_index)` instead of just
`provider`. One `OpenAI` client per key per provider.

### 3.C Cooldown state

**Process-local.** There is no shared in-process key-pool registry. Cooldown state (which
key last failed, until when) would live on the `LLMClient` instance.

**Workers share one `LLMClient` per run.** In `service.py::_setup_run_context()`,
`LLMClient(client_config)` is constructed once and passed to all parallel
`_worker_one` calls (via the `_RunContext`). A `threading.Lock`-guarded cooldown
`dict[str, datetime]` on the `LLMClient` instance is sufficient for intra-run key
coordination.

**Multi-instance deployment:** The CLAUDE.md confirms Railway multi-instance deployment.
Process-local cooldown means different instances discover quota exhaustion independently
and each burns 2 SDK retries on the first error. There is no shared coordination. For a
low-traffic staging environment this is acceptable; for high-traffic production, a shared
cooldown store (Redis or similar) would be needed but is out of scope.

### 3.D Operator evidence requirements

From the prior note (Section B.1.b and B.2.c, not repeated here):

- **Anthropic:** multi-key rotation helps only when keys are from **different Anthropic
  organizations** (rate limits are org-level, not key-level). Same-org keys share the
  same rate-limit bucket. For `enforced_spend_limit_reached` (org monthly cap), only a
  different-org key or a different provider helps.
- **Gemini:** multi-key rotation helps only when keys are from **different GCP projects**
  (quota is applied per project). Same-project keys share the quota bucket.

The operator must provide evidence of separate billing accounts to justify the
complexity of a multi-key pool. The documentation and env var descriptions should make
this requirement explicit.

---

## Raw Evidence Appendix

### A.1 Live probe (Gemini compat endpoint with invalid key)

```
Request: POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
         Authorization: Bearer invalid_test_key_for_envelope_shape
         Content-Type: application/json
         Body: {"model":"gemini-2.0-flash","messages":[{"role":"user","content":"hi"}]}

HTTP/2 400
content-type: application/json; charset=UTF-8
server-timing: gfet4t7; dur=11
...

[{
  "error": {
    "code": 400,
    "message": "Please pass a valid API key",
    "status": "INVALID_ARGUMENT"
  }
}
]
```

Key observations:
- HTTP status: **400** (not 401 as an OpenAI endpoint would return for bad auth)
- Body: **JSON array** wrapping Google-native error object
- No `"type"` field (OpenAI-style); no string `"code"` (OpenAI-style)
- `"status"` is a gRPC status name, absent from OpenAI error bodies

### A.2 OpenAI SDK 2.30.0 body-parsing logic (read from `.venv/`)

`_client.py` `_make_status_error` (line 434):
```python
data = body.get("error", body) if is_mapping(body) else body
```
For a list body: `is_mapping([...]) = False` → `data = body` (the list).

`_exceptions.py` `APIError.__init__` (lines 60–67):
```python
if is_dict(body):
    self.code = body.get("code")
    ...
else:
    self.code = None
    self.param = None
    self.type = None
```
For a list body: `is_dict([...]) = False` → `exc.code = None`, `exc.type = None`.

### A.3 Anthropic SDK 0.104.1 `_should_retry` (read from `.venv/`)

`_base_client.py` lines 804–837:
```python
def _should_retry(self, response: httpx.Response) -> bool:
    should_retry_header = response.headers.get("x-should-retry")
    if should_retry_header == "true":  return True
    if should_retry_header == "false": return False
    if response.status_code == 408:    return True
    if response.status_code == 409:    return True
    if response.status_code == 429:    return True   # ← no body inspection
    if response.status_code >= 500:    return True
    return False
```
`DEFAULT_MAX_RETRIES = 2` (confirmed from `_constants.py`).

### A.4 OpenAI SDK 2.30.0 `_should_retry` (read from `.venv/`)

`_base_client.py` lines 773–806: identical logic and constant. Both SDKs use the same
generated Stainless pattern.

### A.5 Exchange recorder — no row written on exception

`server/generate/exchange_recorder.py` lines 26–29:
> "A row with `request_body=NULL` is written if a response arrives with no matching
> request (defensive). **If a request never gets a response (worker crashed), that row
> is intentionally not written** — the generation_log row's `status='failed'` already
> signals the crash."

And lines 116–137: `__call__` handles only `"llm_request"` and `"llm_response"` event
types. An `"llm_failure"` event is not handled — it falls through to `return` in the
`if event_type ==` branches without writing anything.

### A.6 `dev.db` query results (read-only)

```sql
SELECT COUNT(*) FROM generation_logs;  -- result: 0
SELECT COUNT(*) FROM llm_exchanges;    -- table schema absent from this SQLite file (generation_logs only)
```

No historical exchange data available in this environment.

### A.7 Sentry access status

Authenticated (`sentry.io@cpeng.me`, auth token with `org:read` and `event:read`
scopes). `sentry-cli projects list --org cpeng` returned `organization not found`. No
`RateLimitError` events could be retrieved. Sentry evidence is unavailable for this
session.

---

## Unverified claims

1. **Gemini compat 429 quota body `status` field:** The live probe confirmed the
   envelope shape (list-wrapped, `status` field) using an invalid-key 400 response.
   Whether a quota-exhausted 429 uses `"status": "RESOURCE_EXHAUSTED"` and a
   per-minute rate-limit 429 uses a different `status` is NOT confirmed. Both may use
   `"RESOURCE_EXHAUSTED"` (same gRPC error), differing only in `"message"` text.
   Distinguishing them reliably may require `message` pattern-matching.

2. **Whether Gemini compat endpoint adds `x-should-retry: false` on quota 429:** Not
   confirmed. If it does, the SDK would stop retrying automatically — but that cannot
   be relied on today.

3. **`retry-after` header on Gemini compat 429:** Not confirmed for either quota or
   rate-limit case. Native Gemini API docs do not document this header.

4. **`effort_execute=high` is safe when falling back from Gemini to Anthropic `claude-opus-4-6`:**
   `high` is in both `THREE_EFFORT_LEVELS` and `FOUR_EFFORT_LEVELS`. The pre-flight effort
   admission check only validates against the primary model's effort levels. At fallback
   time, `high` should be safe. Not tested at the wire level with a real fallback call.

5. **Anthropic Opus 4.x models do NOT return `x-should-retry: false` on `enforced_spend_limit_reached`:**
   From the prior note this is inferred from "no `retry-after` header" but the `x-should-retry`
   header presence is not confirmed.

6. **Future ordering of fable-downgrade guard vs. quota-fallback guard inside `_call()`:**
   The fable-downgrade proposal (`openspec/changes/fable-downgrade-switch/`) is not yet
   implemented. If/when it is, both guards must share a single substitution point so the
   quota-fallback operates on the post-rewrite effective model. There is nothing to order
   against today.

---

## Open questions for the operator

1. **Which Gemini fallback model?** `claude-opus-4-6` (same provider as verify; adds
   Anthropic spend) or `claude-sonnet-4-6` (lower cost, may affect quality)? The default
   should be documented in `DEPLOYMENT.md` with a note on quality and cost trade-offs.

2. **Should the fallback apply only to quota-exhausted errors or also to 503/overloaded?**
   The retry decision rule in the prior note treats these differently (quota → fallback
   immediately; overloaded → retry with backoff). A combined approach (retry transient
   errors N times, then fall back) is more complex but avoids premature fallback on
   temporary overloads.

3. **Per-run fallback or per-request fallback?** If the first 子題 worker hits a quota
   error and switches to the fallback model, should all subsequent workers in the same
   run also use the fallback (run-level switch), or should each worker independently
   decide (request-level switch)? Run-level is simpler (set `client_config.model_execute`
   on the shared `_RunContext`), but requires thread-safe state mutation mid-run.

4. **Fallback and fable-downgrade coexistence (forward-looking):** The fable-downgrade
   proposal is not yet implemented. If it lands alongside the quota-fallback, the shared
   substitution point (§2.F) must guard against an identity fallback: if fable→opus rewrite
   leaves `model_execute_effective == model_execute_fallback`, the quota-fallback would
   switch to the same model and should be skipped or re-targeted.

5. **Separate Anthropic org / separate GCP project confirmation (for multi-key):** Do you
   have API keys from separate billing accounts for Anthropic and/or Gemini? Without this,
   multi-key pools add complexity with no benefit (prior note §B.1.b, §B.2.c).

6. **Admission gate for fallback model:** Should `LLM_MODEL_EXECUTE_FALLBACK` be validated
   against `_check_provider_key_for_model()` at server startup, so a missing fallback API
   key is surfaced at boot rather than at first quota error?
