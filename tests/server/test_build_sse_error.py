"""Tests for build_sse_error optional kwargs — issue #946."""
from __future__ import annotations

from server.generate.models import build_sse_error


def test_basic_no_kwargs():
    result = build_sse_error("generation_failed", "something went wrong")
    assert result == {"code": "generation_failed", "message": "something went wrong"}


def test_failure_class_included():
    result = build_sse_error("generation_failed", "err", failure_class="rate_limited")
    assert result["failure_class"] == "rate_limited"
    assert result["code"] == "generation_failed"
    assert result["message"] == "err"


def test_failure_class_none_omitted():
    result = build_sse_error("generation_failed", "err", failure_class=None)
    assert "failure_class" not in result


def test_provider_included():
    result = build_sse_error("stream_failed", "err", provider="anthropic")
    assert result["provider"] == "anthropic"


def test_provider_none_omitted():
    result = build_sse_error("stream_failed", "err", provider=None)
    assert "provider" not in result


def test_model_included():
    result = build_sse_error("generation_failed", "err", model="claude-opus-4-6")
    assert result["model"] == "claude-opus-4-6"


def test_model_none_omitted():
    result = build_sse_error("generation_failed", "err", model=None)
    assert "model" not in result


def test_tier_included():
    result = build_sse_error("generation_failed", "err", tier="execute")
    assert result["tier"] == "execute"


def test_tier_none_omitted():
    result = build_sse_error("generation_failed", "err", tier=None)
    assert "tier" not in result


def test_retry_after_seconds_included():
    result = build_sse_error("generation_failed", "err", retry_after_seconds=30)
    assert result["retry_after_seconds"] == 30


def test_retry_after_seconds_none_omitted():
    result = build_sse_error("generation_failed", "err", retry_after_seconds=None)
    assert "retry_after_seconds" not in result


def test_http_status_included():
    result = build_sse_error("generation_failed", "err", http_status=429)
    assert result["http_status"] == 429


def test_http_status_none_omitted():
    result = build_sse_error("generation_failed", "err", http_status=None)
    assert "http_status" not in result


def test_all_kwargs():
    result = build_sse_error(
        "generation_failed",
        "oops",
        failure_class="overloaded",
        provider="anthropic",
        model="claude-opus-4-6",
        tier="execute",
        http_status=429,
        retry_after_seconds=60,
    )
    assert result == {
        "code": "generation_failed",
        "message": "oops",
        "failure_class": "overloaded",
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "tier": "execute",
        "http_status": 429,
        "retry_after_seconds": 60,
    }


def test_legacy_callers_unchanged():
    """Existing callers that pass only positional args still get the same result."""
    result = build_sse_error("modification_failed", "mod error")
    assert set(result.keys()) == {"code", "message"}
