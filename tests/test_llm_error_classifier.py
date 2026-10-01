"""Tests for classify_provider_error — issue #946.

All tests are unit-level: they instantiate mock exception objects with the
minimum attributes that ``extract_provider_error`` and
``classify_provider_error`` inspect, then assert the returned taxonomy code.

Ten stable codes:
    auth_config | quota_billing_exhausted | rate_limited | overloaded |
    timeout | connection | context_length | content_filtered |
    malformed_response | unknown
"""
from __future__ import annotations

import types
from typing import Any

from src.llm_client import ProviderErrorDetail, classify_provider_error

# ---------------------------------------------------------------------------
# Helpers — build fake exception objects
# ---------------------------------------------------------------------------


def _exc(
    *,
    status_code: int | None = None,
    body: Any = None,
    headers: dict | None = None,
) -> Exception:
    """Create a mock API exception with ``status_code``, ``body``, ``response``."""
    exc = Exception("mock provider error")
    exc.status_code = status_code  # type: ignore[attr-defined]
    exc.body = body  # type: ignore[attr-defined]

    # Simulate the ``response`` attribute with a ``headers`` dict
    if headers is not None:
        resp = types.SimpleNamespace(headers=headers)
    else:
        resp = types.SimpleNamespace(headers={})
    exc.response = resp  # type: ignore[attr-defined]
    return exc


def _detail(
    *,
    http_status: int | None = None,
    provider_error_type: str | None = None,
    provider_error_code: str | None = None,
    provider_error_status: str | None = None,
    provider_message: str | None = None,
    retry_after_seconds: int | None = None,
) -> ProviderErrorDetail:
    return ProviderErrorDetail(
        provider="test",
        model="test-model",
        http_status=http_status,
        provider_error_type=provider_error_type,
        provider_error_code=provider_error_code,
        provider_error_status=provider_error_status,
        provider_message=provider_message,
        request_id=None,
        retry_after_seconds=retry_after_seconds,
        raw_body_truncated=None,
    )


# ---------------------------------------------------------------------------
# 1. auth_config
# ---------------------------------------------------------------------------


def test_auth_config_401_anthropic():
    exc = _exc(status_code=401, body={"type": "error", "error": {"type": "authentication_error"}})
    assert classify_provider_error(exc) == "auth_config"


def test_auth_config_via_detail():
    d = _detail(http_status=401)
    assert classify_provider_error(None, detail=d) == "auth_config"


def test_auth_config_gemini_invalid_argument_key_message():
    # Gemini compat 400 INVALID_ARGUMENT with API key mention
    exc = _exc(
        status_code=400,
        body=[{"error": {
            "code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT",
        }}],
    )
    assert classify_provider_error(exc) == "auth_config"


def test_auth_config_403():
    exc = _exc(status_code=403, body={"error": {"type": "permission_error"}})
    assert classify_provider_error(exc) == "auth_config"


# ---------------------------------------------------------------------------
# 2. quota_billing_exhausted
# ---------------------------------------------------------------------------


def test_quota_enforced_spend_limit():
    # Anthropic 400 with error_code = enforced_spend_limit_reached
    exc = _exc(
        status_code=400,
        body={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "details": {"error_code": "enforced_spend_limit_reached"},
            },
        },
    )
    assert classify_provider_error(exc) == "quota_billing_exhausted"


def test_quota_billing_error_type():
    # Anthropic 402 billing_error
    exc = _exc(status_code=402, body={"error": {"type": "billing_error"}})
    assert classify_provider_error(exc) == "quota_billing_exhausted"


def test_quota_openai_credit_balance_exhausted():
    # OpenAI 429 with code=credit_balance_exhausted
    exc = _exc(
        status_code=429,
        body={"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted"}},
    )
    assert classify_provider_error(exc) == "quota_billing_exhausted"


def test_quota_openai_insufficient_quota_type():
    exc = _exc(status_code=429, body={"error": {"type": "insufficient_quota"}})
    assert classify_provider_error(exc) == "quota_billing_exhausted"


def test_quota_via_detail_402():
    d = _detail(http_status=402)
    assert classify_provider_error(None, detail=d) == "quota_billing_exhausted"


def test_quota_gemini_compat_payment_required():
    exc = _exc(
        status_code=402,
        body=[{"error": {
            "code": 402, "message": "Billing account is disabled", "status": "FAILED_PRECONDITION",
        }}],
    )
    assert classify_provider_error(exc) == "quota_billing_exhausted"


# ---------------------------------------------------------------------------
# 3. rate_limited
# ---------------------------------------------------------------------------


def test_rate_limited_429_plain():
    # Plain 429 with rate_limit type
    exc = _exc(
        status_code=429,
        body={"error": {"type": "rate_limit_error", "message": "rate limit exceeded"}},
    )
    assert classify_provider_error(exc) == "rate_limited"


def test_rate_limited_gemini_resource_exhausted():
    # Gemini compat 429 RESOURCE_EXHAUSTED
    exc = _exc(
        status_code=429,
        body=[{"error": {
            "code": 429, "message": "Resource has been exhausted", "status": "RESOURCE_EXHAUSTED",
        }}],
    )
    assert classify_provider_error(exc) == "rate_limited"


def test_rate_limited_via_detail():
    d = _detail(http_status=429, provider_error_type="rate_limit_error")
    assert classify_provider_error(None, detail=d) == "rate_limited"


# ---------------------------------------------------------------------------
# 4. overloaded
# ---------------------------------------------------------------------------


def test_overloaded_529():
    exc = _exc(status_code=529, body={"error": {"type": "overloaded_error"}})
    assert classify_provider_error(exc) == "overloaded"


def test_overloaded_type():
    exc = _exc(status_code=529, body={"error": {"type": "overloaded_error"}})
    assert classify_provider_error(exc) == "overloaded"


def test_overloaded_via_detail():
    d = _detail(http_status=529)
    assert classify_provider_error(None, detail=d) == "overloaded"


# ---------------------------------------------------------------------------
# 5. timeout
# ---------------------------------------------------------------------------


def test_timeout_from_exception_class():
    """APITimeoutError class → timeout regardless of body/status."""
    try:
        from anthropic import APITimeoutError  # noqa: PLC0415

        exc = APITimeoutError.__new__(APITimeoutError)
    except (ImportError, TypeError):
        # Fallback: create a mock that looks like a timeout error
        exc = Exception("timeout")
        exc.__class__.__name__ = "APITimeoutError"  # type: ignore[attr-defined]
        exc.status_code = None  # type: ignore[attr-defined]
        exc.body = None  # type: ignore[attr-defined]
        exc.response = types.SimpleNamespace(headers={})  # type: ignore[attr-defined]

    assert classify_provider_error(exc) == "timeout"


def test_timeout_openai_compat_exception():
    try:
        from openai import APITimeoutError  # noqa: PLC0415

        exc = APITimeoutError.__new__(APITimeoutError)
    except (ImportError, TypeError):
        class OpenAICompatTimeout(TimeoutError):
            pass

        exc = OpenAICompatTimeout("OpenAI-compatible request timed out")

    assert classify_provider_error(exc) == "timeout"


# ---------------------------------------------------------------------------
# 6. connection
# ---------------------------------------------------------------------------


def test_connection_from_exception_class():
    """APIConnectionError class → connection."""
    try:
        from anthropic import APIConnectionError  # noqa: PLC0415

        exc = APIConnectionError.__new__(APIConnectionError)
    except (ImportError, TypeError):
        exc = Exception("connection error")
        exc.__class__.__name__ = "APIConnectionError"  # type: ignore[attr-defined]
        exc.status_code = None  # type: ignore[attr-defined]
        exc.body = None  # type: ignore[attr-defined]
        exc.response = types.SimpleNamespace(headers={})  # type: ignore[attr-defined]

    assert classify_provider_error(exc) == "connection"


# ---------------------------------------------------------------------------
# 7. context_length
# ---------------------------------------------------------------------------


def test_context_length_413():
    exc = _exc(status_code=413, body={"error": {"type": "request_too_large"}})
    assert classify_provider_error(exc) == "context_length"


def test_context_length_context_window_exceeded():
    exc = _exc(
        status_code=400,
        body={"error": {"type": "invalid_request_error", "code": "context_window_exceeded"}},
    )
    assert classify_provider_error(exc) == "context_length"


def test_context_length_via_detail():
    d = _detail(http_status=413)
    assert classify_provider_error(None, detail=d) == "context_length"


# ---------------------------------------------------------------------------
# 8. content_filtered
# ---------------------------------------------------------------------------


def test_content_filtered_exception_class():
    """ContentFilterFinishReasonError → content_filtered."""
    try:
        from openai import ContentFilterFinishReasonError  # noqa: PLC0415

        exc = ContentFilterFinishReasonError.__new__(ContentFilterFinishReasonError)
    except (ImportError, TypeError):
        exc = Exception("content filter")
        exc.__class__.__name__ = "ContentFilterFinishReasonError"  # type: ignore[attr-defined]
        exc.status_code = None  # type: ignore[attr-defined]
        exc.body = None  # type: ignore[attr-defined]
        exc.response = types.SimpleNamespace(headers={})  # type: ignore[attr-defined]

    assert classify_provider_error(exc) == "content_filtered"


# ---------------------------------------------------------------------------
# 9. malformed_response
# ---------------------------------------------------------------------------


def test_malformed_response_500():
    exc = _exc(status_code=500, body={"error": {"type": "api_error", "message": "unexpected"}})
    assert classify_provider_error(exc) == "malformed_response"


def test_malformed_response_503():
    exc = _exc(status_code=503, body={"error": {"type": "api_error"}})
    assert classify_provider_error(exc) == "malformed_response"


def test_malformed_response_gemini_compat_500():
    exc = _exc(
        status_code=500,
        body=[{"error": {
            "code": 500, "message": "unexpected upstream response", "status": "INTERNAL",
        }}],
    )
    assert classify_provider_error(exc) == "malformed_response"


def test_malformed_response_via_detail():
    d = _detail(http_status=500)
    assert classify_provider_error(None, detail=d) == "malformed_response"


# ---------------------------------------------------------------------------
# 10. unknown
# ---------------------------------------------------------------------------


def test_unknown_unrecognized_class():
    exc = Exception("some totally unknown error")
    # No status_code, no body, no response
    assert classify_provider_error(exc) == "unknown"


def test_unknown_via_detail_none():
    """classify_provider_error(None, detail=None) → unknown."""
    assert classify_provider_error(None) == "unknown"


# ---------------------------------------------------------------------------
# 11. Never raises (safety guarantee)
# ---------------------------------------------------------------------------


def test_never_raises_on_none():
    result = classify_provider_error(None)
    assert isinstance(result, str)


def test_never_raises_on_garbage_exc():
    exc = Exception("garbage")
    exc.status_code = "not an int"  # type: ignore[attr-defined]
    exc.body = object()  # type: ignore[attr-defined]
    exc.response = None  # type: ignore[attr-defined]
    result = classify_provider_error(exc)
    assert isinstance(result, str)
    assert result in {
        "auth_config", "quota_billing_exhausted", "rate_limited", "overloaded",
        "timeout", "connection", "context_length", "content_filtered",
        "malformed_response", "unknown",
    }


def test_never_raises_on_detail_only():
    d = _detail(http_status=999)
    result = classify_provider_error(None, detail=d)
    assert isinstance(result, str)
