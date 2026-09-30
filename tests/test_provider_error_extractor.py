"""Tests for extract_provider_error and ProviderErrorDetail.

Tasks 1.2, 1.3 — run BEFORE and AFTER implementing the extractor.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "provider_errors"


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text())


def _make_exc(
    *,
    status_code: int | None = None,
    body: dict | list | None = None,
    exc_type: str | None = None,
    exc_code: str | None = None,
    retry_after: str | None = None,
    request_id: str | None = None,
) -> Exception:
    """Build a minimal fake provider exception like the Anthropic/OpenAI SDKs."""
    exc = Exception("fake provider error")
    if status_code is not None:
        exc.status_code = status_code
    if body is not None:
        exc.body = body
    if exc_type is not None:
        exc.type = exc_type
    if exc_code is not None:
        exc.code = exc_code
    # Simulate response headers
    headers: dict = {}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    if request_id is not None:
        headers["request-id"] = request_id
    if headers:
        response = types.SimpleNamespace(headers=headers)
        exc.response = response
    return exc


class TestExtractProviderError:
    """Test extract_provider_error against all body shapes."""

    def test_anthropic_spend_cap(self) -> None:
        """Anthropic spend-cap body → correct fields extracted."""
        from src.llm_client import extract_provider_error

        body = _load("anthropic_spend_cap_429.json")
        exc = _make_exc(status_code=429, body=body)
        detail = extract_provider_error(exc, provider="anthropic", model="claude-opus-4-6")

        assert detail.http_status == 429
        assert detail.provider_error_type == "rate_limit_error"
        assert detail.provider_error_code == "enforced_spend_limit_reached"
        assert detail.retry_after_seconds is None
        assert detail.provider == "anthropic"
        assert detail.model == "claude-opus-4-6"

    def test_anthropic_transient_429_with_retry_after(self) -> None:
        """Anthropic transient 429 with retry-after header → retry_after_seconds set."""
        from src.llm_client import extract_provider_error

        body = {"type": "error", "error": {"type": "rate_limit_error", "message": "rate limited"}}
        exc = _make_exc(status_code=429, body=body, retry_after="30", request_id="req-abc")
        detail = extract_provider_error(exc, provider="anthropic", model="claude-opus-4-6")

        assert detail.http_status == 429
        assert detail.provider_error_type == "rate_limit_error"
        assert detail.provider_error_code is None
        assert detail.retry_after_seconds == 30
        assert detail.request_id == "req-abc"

    def test_google_list_wrapped_invalid_key_400(self) -> None:
        """Google list-wrapped body (fixture) → fields normalized correctly."""
        from src.llm_client import extract_provider_error

        body = _load("google_invalid_key_400.json")
        exc = _make_exc(status_code=400, body=body)
        detail = extract_provider_error(exc, provider="gemini", model="gemini-3.1-pro-preview")

        assert detail.http_status == 400
        assert detail.provider_error_code is None  # SDK sets code=None for list bodies
        assert detail.provider_error_status == "INVALID_ARGUMENT"
        assert detail.provider_message == "Please pass a valid API key"

    def test_google_plausible_quota_429(self) -> None:
        """Google list-wrapped quota 429 → RESOURCE_EXHAUSTED extracted."""
        from src.llm_client import extract_provider_error

        body = [{"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}}]
        exc = _make_exc(status_code=429, body=body)
        detail = extract_provider_error(exc, provider="gemini", model="gemini-3.1-pro-preview")

        assert detail.http_status == 429
        assert detail.provider_error_status == "RESOURCE_EXHAUSTED"

    def test_openai_credit_exhausted(self) -> None:
        """OpenAI credit-exhausted body (fixture) → error_code extracted."""
        from src.llm_client import extract_provider_error

        body = _load("openai_credit_exhausted_429.json")
        exc = _make_exc(status_code=429, body=body, exc_code="credit_balance_exhausted")
        detail = extract_provider_error(exc, provider="openai", model="gpt-5")

        assert detail.provider_error_code == "credit_balance_exhausted"

    def test_api_timeout_error_no_http(self) -> None:
        """APITimeoutError (no status_code, no body) → all provider fields None."""
        from src.llm_client import extract_provider_error

        exc = Exception("timeout")
        detail = extract_provider_error(exc, provider="anthropic", model="claude-opus-4-6")

        assert detail.http_status is None
        assert detail.provider_error_type is None
        assert detail.provider_error_code is None
        assert detail.retry_after_seconds is None
        assert detail.provider_message is None

    def test_body_exceeding_4096_bytes_is_truncated(self) -> None:
        """Body exceeding 4096 bytes → raw_body_truncated is at most 4096 bytes."""
        from src.llm_client import extract_provider_error

        long_message = "x" * 10_000
        body = {"type": "error", "error": {"type": "rate_limit_error", "message": long_message}}
        exc = _make_exc(status_code=429, body=body)
        detail = extract_provider_error(exc, provider="anthropic", model="claude-opus-4-6")

        assert detail.raw_body_truncated is not None
        assert len(detail.raw_body_truncated) <= 4096

    def test_absent_provider_error_fields_are_none(self) -> None:
        """Minimal exception with no code/type → fields None, no exception raised."""
        from src.llm_client import extract_provider_error

        body = {"type": "error", "error": {"message": "something failed"}}
        exc = _make_exc(status_code=500, body=body)
        detail = extract_provider_error(exc, provider="anthropic", model="claude-opus-4-6")

        assert detail.provider_error_code is None
        assert detail.provider_error_status is None
        assert detail.http_status == 500

    def test_dataclass_is_frozen(self) -> None:
        """ProviderErrorDetail is a frozen dataclass."""
        from src.llm_client import ProviderErrorDetail

        detail = ProviderErrorDetail(
            provider="anthropic",
            model="claude-opus-4-6",
            http_status=429,
            provider_error_type="rate_limit_error",
            provider_error_code=None,
            provider_error_status=None,
            provider_message=None,
            request_id=None,
            retry_after_seconds=None,
            raw_body_truncated=None,
        )
        with pytest.raises((AttributeError, TypeError)):
            detail.http_status = 500  # type: ignore[misc]

    def test_retry_after_ms_header(self) -> None:
        """retry-after-ms header → converted to seconds (rounded up)."""
        from src.llm_client import extract_provider_error

        body = {"type": "error", "error": {"type": "rate_limit_error", "message": "limited"}}
        exc = _make_exc(status_code=429, body=body, retry_after="30000")
        # Inject retry-after-ms instead
        exc.response = types.SimpleNamespace(headers={"retry-after-ms": "30000"})
        detail = extract_provider_error(exc, provider="anthropic", model="claude-opus-4-6")

        # 30000 ms = 30 seconds
        assert detail.retry_after_seconds == 30

    def test_google_details_retry_info(self) -> None:
        """Google body with RetryInfo details → retry_after_seconds parsed."""
        from src.llm_client import extract_provider_error

        body = [{"error": {
            "code": 429,
            "message": "Resource exhausted",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "60s",
                }
            ],
        }}]
        exc = _make_exc(status_code=429, body=body)
        detail = extract_provider_error(exc, provider="gemini", model="gemini-3.1-pro-preview")

        assert detail.retry_after_seconds == 60

    def test_google_details_quota_failure(self) -> None:
        """Google body with QuotaFailure details → quota_id accessible."""
        from src.llm_client import extract_provider_error

        body = [{"error": {
            "code": 429,
            "message": "Resource exhausted",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaId": "GenerateContent-Requests-Per-Minute", "subject": ""}],
                }
            ],
        }}]
        exc = _make_exc(status_code=429, body=body)
        detail = extract_provider_error(exc, provider="gemini", model="gemini-3.1-pro-preview")

        # The quota_id is not a top-level ProviderErrorDetail field in the spec.
        # We just verify extraction doesn't crash and RESOURCE_EXHAUSTED is set.
        assert detail.provider_error_status == "RESOURCE_EXHAUSTED"

    def test_unknown_body_type_returns_nulls(self) -> None:
        """Non-dict, non-list body → null provider fields, no exception."""
        from src.llm_client import extract_provider_error

        exc = _make_exc(status_code=500, body="some string body")  # type: ignore[arg-type]
        detail = extract_provider_error(exc, provider="anthropic", model="claude-opus-4-6")

        assert detail.provider_error_type is None
        assert detail.provider_error_code is None
        assert detail.http_status == 500
