"""Tests for ProviderErrorDetail emission on llm_failure events.

Tasks 2.1–2.5, 3.1–3.3 — TDD: failing tests written before implementation.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config


# ---------------------------------------------------------------------------
# Helpers to build a minimal LLMClient with a fake provider that raises.
# ---------------------------------------------------------------------------

def _make_config(**overrides: Any) -> Config:
    defaults = dict(
        api_key="sk-test-key",
        base_url="https://api.anthropic.com/v1",
        gemini_api_key="gk-test-key",
        gemini_base_url="https://gemini.example.com",
        model_execute="claude-opus-4-6",
        model_verify="claude-opus-4-6",
        model_plan="claude-opus-4-6",
        model_correct="",
        effort_execute="high",
        effort_verify="high",
        effort_plan="high",
        effort_correct="",
        llm_stream=False,
        llm_timeout_seconds=60,
        image_timeout_seconds=60,
        image_api_key="",
        image_base_url="https://api.openai.com/v1",
        image_model="gpt-image2",
        rate_limit_delay=0,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_fake_exc(status_code: int = 429, body: dict | None = None) -> Exception:
    """Build a fake RateLimitError-like exception."""
    exc = Exception("rate limited")
    exc.status_code = status_code
    exc.body = body or {
        "type": "error",
        "error": {
            "type": "rate_limit_error",
            "message": "You have reached your API usage limits",
        },
    }
    exc.type = "rate_limit_error"
    exc.code = None
    return exc


# ---------------------------------------------------------------------------
# Task 2.1 — _call() failure carries ProviderErrorDetail in llm_failure event
# ---------------------------------------------------------------------------

class TestCallFailureCarriesDetail:

    def _make_client_with_observer(self) -> tuple[Any, list[dict]]:
        """Return (client, events_list) — events are appended by observer."""
        from src.llm_client import LLMClient
        config = _make_config()
        events: list[dict] = []
        client = LLMClient(config)
        client.set_observer(events.append)
        return client, events

    def test_call_failure_event_has_detail_fields(self) -> None:
        """_call() llm_failure event carries all ProviderErrorDetail fields."""
        from src.llm_client import LLMClient
        config = _make_config()
        events: list[dict] = []
        client = LLMClient(config)
        client.set_observer(events.append)

        fake_exc = _make_fake_exc()

        with patch.object(client, "_anthropic_call", side_effect=fake_exc):
            with pytest.raises(Exception):
                client._call(
                    [{"role": "user", "content": "hello"}],
                    "claude-opus-4-6",
                    "generate",
                    scope=None,
                )

        failure_events = [e for e in events if e.get("type") == "llm_failure"]
        assert failure_events, "expected at least one llm_failure event"
        ev = failure_events[-1]

        # All ProviderErrorDetail fields must be present
        assert "http_status" in ev, f"missing http_status in {ev}"
        assert "provider_error_type" in ev, f"missing provider_error_type in {ev}"
        assert "provider_error_code" in ev, f"missing provider_error_code in {ev}"
        assert "provider_error_status" in ev, f"missing provider_error_status in {ev}"
        assert "provider_message" in ev, f"missing provider_message in {ev}"
        assert "request_id" in ev, f"missing request_id in {ev}"
        assert "retry_after_seconds" in ev, f"missing retry_after_seconds in {ev}"
        assert "raw_body_truncated" in ev, f"missing raw_body_truncated in {ev}"

        # Values make sense
        assert ev["http_status"] == 429
        assert ev["provider_error_type"] == "rate_limit_error"

    def test_call_failure_reraises_original_exception(self) -> None:
        """The original exception is re-raised unchanged."""
        from src.llm_client import LLMClient
        config = _make_config()
        events: list[dict] = []
        client = LLMClient(config)
        client.set_observer(events.append)

        fake_exc = _make_fake_exc()
        with patch.object(client, "_anthropic_call", side_effect=fake_exc):
            with pytest.raises(Exception) as exc_info:
                client._call(
                    [{"role": "user", "content": "hello"}],
                    "claude-opus-4-6",
                    "generate",
                    scope=None,
                )
        assert exc_info.value is fake_exc

    def test_generate_with_tools_failure_carries_detail(self) -> None:
        """generate_with_tools() llm_failure event carries ProviderErrorDetail fields."""
        from src.llm_client import LLMClient
        config = _make_config()
        events: list[dict] = []
        client = LLMClient(config)
        client.set_observer(events.append)

        fake_exc = _make_fake_exc(
            body={"type": "error", "error": {"type": "rate_limit_error", "message": "limited"}},
        )

        # Patch the internal Anthropic messages.create to raise
        with patch.object(client.client.messages, "create", side_effect=fake_exc):
            with pytest.raises(Exception):
                client.generate_with_tools(
                    system="sys",
                    user="user",
                    tools=[{"type": "web_search_20250305", "name": "web_search"}],
                    scope=None,
                )

        failure_events = [e for e in events if e.get("type") == "llm_failure"]
        assert failure_events, "expected llm_failure from generate_with_tools"
        ev = failure_events[-1]
        assert "http_status" in ev, f"missing http_status in {ev}"
        assert "provider_error_type" in ev

    def test_generate_with_google_search_failure_carries_detail(self) -> None:
        """generate_with_google_search() llm_failure event carries detail fields."""
        from src.llm_client import LLMClient
        config = _make_config()
        events: list[dict] = []
        client = LLMClient(config)
        client.set_observer(events.append)

        fake_exc = _make_fake_exc(
            body=[{"error": {"code": 429, "message": "exhausted", "status": "RESOURCE_EXHAUSTED"}}],
        )

        with patch.object(client, "_openai_compat_client") as mock_compat:
            mock_cc = MagicMock()
            mock_cc.chat.completions.create.side_effect = fake_exc
            mock_compat.return_value = mock_cc
            with pytest.raises(Exception):
                client.generate_with_google_search(
                    system="sys",
                    user="user",
                    scope=None,
                )

        failure_events = [e for e in events if e.get("type") == "llm_failure"]
        assert failure_events, "expected llm_failure from generate_with_google_search"
        ev = failure_events[-1]
        assert "http_status" in ev, f"missing http_status in {ev}"
        assert "provider_error_status" in ev


# ---------------------------------------------------------------------------
# Task 2.5 — guard test: every "llm_failure" in llm_client.py has extractor
# ---------------------------------------------------------------------------

class TestLlmFailureGuard:

    def test_every_llm_failure_site_uses_extract_provider_error(self) -> None:
        """Every 'llm_failure' literal is preceded by extract_provider_error within 10 lines."""
        import inspect
        from src import llm_client
        source = inspect.getsource(llm_client)
        lines = source.splitlines()

        failure_positions = [
            i for i, line in enumerate(lines)
            if '"llm_failure"' in line or "'llm_failure'" in line
        ]
        assert failure_positions, "no llm_failure emission sites found"

        for pos in failure_positions:
            # Look at the 10 lines BEFORE the emission site
            window_start = max(0, pos - 10)
            window = lines[window_start:pos + 1]
            window_text = "\n".join(window)
            assert "extract_provider_error" in window_text, (
                f"llm_failure at line {pos + 1} is missing an extract_provider_error call "
                f"in the preceding 10 lines.\n"
                f"Context:\n{window_text}"
            )


# ---------------------------------------------------------------------------
# Task 3.1 — WARNING log is emitted with correct fields, no secrets
# Task 3.3 — WARNING log does not contain provider_message or raw_body text
# ---------------------------------------------------------------------------

class TestWarningLog:

    def test_warning_log_emitted_on_call_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """Exactly one WARNING from src.llm_client with required fields."""
        import logging
        from src.llm_client import LLMClient
        config = _make_config()
        events: list[dict] = []
        client = LLMClient(config)
        client.set_observer(events.append)

        fake_exc = _make_fake_exc()

        with caplog.at_level(logging.WARNING, logger="src.llm_client"):
            with patch.object(client, "_anthropic_call", side_effect=fake_exc):
                with pytest.raises(Exception):
                    client._call(
                        [{"role": "user", "content": "hello"}],
                        "claude-opus-4-6",
                        "generate",
                        scope=None,
                    )

        warnings = [r for r in caplog.records if r.levelname == "WARNING" and "llm_failure" in r.message]
        assert warnings, f"no llm_failure WARNING found; records={[r.message for r in caplog.records]}"
        msg = warnings[0].message
        assert "provider=" in msg or "provider" in msg
        assert "http_status=" in msg or "http_status" in msg
        assert "error_type=" in msg or "error_type" in msg
        assert "error_code=" in msg or "error_code" in msg

    def test_warning_log_does_not_contain_api_key(self, caplog: pytest.LogCaptureFixture) -> None:
        """WARNING log entry does not expose the API key."""
        import logging
        from src.llm_client import LLMClient
        config = _make_config(api_key="sk-test-key")
        events: list[dict] = []
        client = LLMClient(config)
        client.set_observer(events.append)

        fake_exc = _make_fake_exc()

        with caplog.at_level(logging.WARNING, logger="src.llm_client"):
            with patch.object(client, "_anthropic_call", side_effect=fake_exc):
                with pytest.raises(Exception):
                    client._call(
                        [{"role": "user", "content": "hello"}],
                        "claude-opus-4-6",
                        "generate",
                        scope=None,
                    )

        for record in caplog.records:
            assert "sk-test-key" not in record.message, (
                f"API key found in log message: {record.message}"
            )
            assert "Bearer" not in record.message

    def test_warning_log_does_not_include_provider_message_or_raw_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """WARNING log does not include provider_message or raw_body_truncated."""
        import logging
        from src.llm_client import LLMClient
        config = _make_config()
        events: list[dict] = []
        client = LLMClient(config)
        client.set_observer(events.append)

        long_msg = "specific provider error text " * 10
        fake_exc = _make_fake_exc(
            body={"type": "error", "error": {"type": "rate_limit_error", "message": long_msg}},
        )

        with caplog.at_level(logging.WARNING, logger="src.llm_client"):
            with patch.object(client, "_anthropic_call", side_effect=fake_exc):
                with pytest.raises(Exception):
                    client._call(
                        [{"role": "user", "content": "hello"}],
                        "claude-opus-4-6",
                        "generate",
                        scope=None,
                    )

        failure_warnings = [r for r in caplog.records if "llm_failure" in r.message]
        for record in failure_warnings:
            assert "specific provider error text" not in record.message, (
                f"provider_message found in log: {record.message}"
            )
            # raw_body_truncated should not appear as-is in log
            assert "rate_limit_error" not in record.message or (
                "error_type" in record.message
            ), record.message

    def test_successful_call_produces_no_llm_failure_event_or_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A successful _call() produces no llm_failure event and no WARNING."""
        import logging
        from src.llm_client import LLMClient
        config = _make_config()
        events: list[dict] = []
        client = LLMClient(config)
        client.set_observer(events.append)

        with caplog.at_level(logging.WARNING, logger="src.llm_client"):
            with patch.object(client, "_anthropic_call", return_value="result text"):
                result = client._call(
                    [{"role": "user", "content": "hello"}],
                    "claude-opus-4-6",
                    "generate",
                )

        assert result == "result text"
        failure_events = [e for e in events if e.get("type") == "llm_failure"]
        assert not failure_events, f"unexpected llm_failure events: {failure_events}"
        failure_warnings = [r for r in caplog.records if "llm_failure" in r.message]
        assert not failure_warnings, f"unexpected WARNING: {failure_warnings}"
