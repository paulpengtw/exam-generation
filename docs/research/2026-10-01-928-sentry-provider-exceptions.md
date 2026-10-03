# Research: Raw LLM provider exceptions reaching Sentry (issue #928)

Date: 2026-10-01
Researcher: holyclaude1

## Summary

The **AnthropicIntegration** (and **OpenAIIntegration**) in Sentry SDK v2.66.1 patch
`messages.create` with a wrapper that calls `sentry_sdk.capture_event()` **directly**
when the underlying HTTP call raises any exception.  This happens inside the patched
wrapper, before the exception propagates to any caller code.  The planner's
`raise CandidateValidationError(...) from None` (planner.py:86) cannot prevent this:
the event has already been dispatched to Sentry's envelope queue.

Under the production `observability.py` configuration (`include_local_variables=False`,
`include_prompts=False`), the exception **message** string is captured (it contains the
API's error JSON body verbatim), but **prompt content is not** captured.  The provider
error message is metadata about the provider's state, not exam content.

## Capturing component (file:line)

**Primary:** `sentry_sdk/integrations/anthropic.py` — functions
`_sentry_patched_create_sync` (line ~664) and `_sentry_patched_create_async` (line ~762):

```python
except Exception as exc:
    exc_info = sys.exc_info()
    with capture_internal_exceptions():
        _capture_exception(exc)   # <-- direct capture_event() call
        span.__exit__(*exc_info)
    reraise(*exc_info)
```

`_capture_exception` at line ~201 calls `sentry_sdk.capture_event(event, hint=hint)`
with `mechanism={"type": "anthropic", "handled": False}`.

**Secondary (Gemini/OpenAI models):** `sentry_sdk/integrations/openai.py` — identical
pattern, mechanism type `"openai"`.

Neither integration fires from exception chaining or `__context__` traversal.  They fire
from inside the patched method, so `raise ... from None` in calling code has no effect.

## Why `from None` does not help

`src/common/planner.py:86` does:

```python
except Exception:
    raise CandidateValidationError("provider_call", ...) from None
```

Python's `from None` sets `__suppress_context__ = True`, hiding the `__context__` chain.
Sentry does not traverse suppressed chains.  However, the `AnthropicIntegration` calls
`sentry_sdk.capture_event()` inside the `messages.create` call — this is a **direct
SDK call**, not a re-raise, and it completes before the `except Exception` block ever
runs.  The resulting event is already in the Sentry envelope queue.

## Does `before_send` apply?

Yes — all `capture_event()` calls pass through `before_send`.  Before issue #967,
`server/observability.py::_before_send` only dropped planner diagnostic warning events,
so AnthropicIntegration events were passed through unchanged.  The production filter
now also drops only exception events containing a value with
`mechanism.type in {"anthropic", "openai"}` and `mechanism.handled is False`.
The integrations remain enabled, so their GenAI spans/tracing continue to work; the
application's WARNING event or sanitized planner event remains the operational signal.

## Per provider × call site table

| Provider | SDK | Integration | Fires? | Which call sites |
|---|---|---|---|---|
| Anthropic (`claude-*`) | anthropic | `AnthropicIntegration` | Yes | planning, execute/文本生成器/子題產生器, 驗證, 修正, fact-check, HTML image generation — any `messages.create` call |
| Gemini (via OpenAI-compat) | openai | `OpenAIIntegration` | Yes | execute/文本生成器/子題產生器, 驗證, 修正, HTML image generation — any `chat.completions.create` call |
| OpenAI (via OpenAI-compat) | openai | `OpenAIIntegration` | Yes | Same as Gemini |
| GPT Image (`gpt-image2`) | openai | `OpenAIIntegration` | Yes | `images.generate` calls in `LLMClient.generate_image` |

All call sites in `src/llm_client.py` that reach `self.client.messages.create` (lines 840,
658, 1308) or `openai_client.chat.completions.create` are covered.

## What content can error messages carry?

### Exception message (captured by the SDK before issue #967)

`str(exc)` = `exc.message` = `f"Error code: {status_code} - {body}"` where `body` is
the decoded JSON response body.  Examples:

- **Credit balance / auth** (400 `invalid_request_error`):
  `"Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."`
  No request content.

- **Oversized prompt** (400 `invalid_request_error`):
  `"prompt is too long (X tokens): 250000 tokens > 200000 max"` or similar.
  Includes token counts, NOT the prompt text itself.
  Token counts are metadata; they do not violate ADR 0004.

- **Content filter / safety** (400 `invalid_request_error`):
  Anthropic's content policy errors say e.g. `"Output blocked by content filtering policy"`.
  They do NOT echo the prompt back.  No request content.

- **Rate limit** (429): `"Rate limit exceeded: ..."`  No request content.

- **Overloaded** (529): `"Overloaded"` or similar.  No request content.

Sources: `.venv/lib/python3.11/site-packages/anthropic/_base_client.py:410-430`
(error construction), `.venv/.../anthropic/_exceptions.py` (class hierarchy).

### Exception attributes NOT serialized by Sentry

`APIStatusError.body` (the JSON dict) and `APIStatusError.request` (httpx.Request
containing the request body with the full prompt) are **custom attributes**, not
`args`.  Sentry's `event_from_exception` serializes `str(exc)` (= the message) and the
stack trace.  It does NOT automatically serialize custom instance attributes.

`APIStatusError.request.content` contains the request body (the full prompt JSON).
This would only leak if `include_local_variables=True` AND the variable is in a live
stack frame.  With `include_local_variables=False` (production setting), it does not.

### Verification (from test)

The reproduction test (`tests/server/test_928_sentry_provider_exception_capture.py`)
confirms:

- With `include_local_variables=False` (production): prompt text does NOT appear in
  telemetry, even though it is passed as a local variable in the patched wrapper.
- Without `include_local_variables=False`: `kwargs["messages"][0]["content"]` DOES
  appear in the serialized local variables of `_sentry_patched_create_sync`.
  The production setting closes this leak.

## PR #956 (feat/946-llm-failure-class) — does explicit `capture_exception` make things worse?

PR #956 adds to `plan_core_questions_endpoint` in `server/generate/routes.py`:

```python
import sentry_sdk as _sentry
_sentry.capture_exception(exc)   # line 670-671 in feat/946-llm-failure-class
```

where `exc` is `CandidateValidationError` (the content-free re-raise).

**Historical assessment:** This added a **third** event for provider failures (in addition to:
(a) the AnthropicIntegration event for `BadRequestError`, and
(b) the LoggingIntegration event for `logger.warning("Planner provider call failed")`).
The explicit `capture_exception(exc)` captures `CandidateValidationError`, which carries
only safe stage metadata (`stage`, `attempt`, `expected_count` etc.) — not provider
messages or prompt content.  It does NOT re-expose the raw provider error.

However, it created a duplicate Sentry issue for the same request, potentially inflating
issue counts.  Under ADR 0004 it was **not strictly harmful** (no forbidden content), but
it was redundant and increased Sentry noise.

## Issue #967 resolution

`server/observability.py::_before_send` now drops the raw provider-integration exception
event by its closed mechanism/type pair.  This is more conservative than disabling
`AnthropicIntegration` and `OpenAIIntegration`: the repository has no application logic
that depends on their spans, but retaining the integrations preserves existing GenAI
tracing for future diagnostics.  The filter also prevents the provider SDK's response
message from becoming a separate event, consistent with ADR 0004's content allowlist.

The planner's explicit `capture_exception` is no longer used for `stage="provider_call"`.
Expected provider failures therefore retain the existing `src.llm_client` WARNING event
once, while malformed planner output keeps the pre-existing sanitized exception event
and warning breadcrumb.  This preserves the distinct malformed-output diagnostic without
reintroducing provider-failure duplication.

The regression tests use the app's `init_sentry(transport=...)` seam and real SDK clients
with `httpx.MockTransport`; they assert no raw Anthropic/OpenAI integration event for
planner or generation calls, while the WARNING signal remains.  They also assert that
provider response messages and prompt sentinels do not appear in the resulting telemetry.

## Reproduction

Test file: `tests/server/test_928_sentry_provider_exception_capture.py`

Run command:
```bash
choom -n 500 -- uv run pytest tests/server/test_928_sentry_provider_exception_capture.py -q
```

Result: 4 passed in ~4 s (verified 2026-10-04).

The tests exercise:
1. Planner path with httpx.MockTransport injected via `Anthropic(http_client=...)`
2. Direct LLM generate path
3. Gemini/OpenAI-compat path via OpenAI client with MockTransport
4. Confirmation that `before_send` filters raw Anthropic integration events

## ADR 0004 compliance verdict

**Compliant under the production config.**  The captured data is:
- Provider error messages: API metadata, not exam content.
- Stack traces: no local variables (include_local_variables=False).
- No prompt/completion content (include_prompts=False, gen_ai.inputs/outputs=False).
- No user info beyond what `Sentry.setUser` explicitly sends.

The one gap (`include_local_variables` must remain False) is already correctly configured
and tested.
