"""Tests for backend Sentry initialization."""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("sentry_sdk", reason="requires [web] extras: uv sync --extra web")


def test_init_sentry_does_not_initialize_without_dsn(monkeypatch) -> None:
    from server import observability

    init_calls: list[dict] = []
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: init_calls.append(kwargs),
    )

    assert observability.init_sentry() is False
    assert init_calls == []


def test_init_sentry_pins_backend_collection_and_logging(monkeypatch) -> None:
    from sentry_sdk.integrations.anthropic import AnthropicIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.openai import OpenAIIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    from server import observability

    init_calls: list[dict] = []
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: init_calls.append(kwargs),
    )

    assert observability.init_sentry() is True
    assert len(init_calls) == 1

    options = init_calls[0]
    assert options["dsn"] == "https://public@example.com/1"
    assert options["environment"] == "production"
    assert options["traces_sample_rate"] == 1.0
    assert options["send_default_pii"] is False
    assert options["max_request_body_size"] == "never"
    assert options["include_local_variables"] is False
    assert options["include_source_context"] is True
    assert options["enable_logs"] is True
    assert options["_experiments"]["data_collection"] == {
        "user_info": False,
        "cookies": {"mode": "off"},
        "http_headers": {"request": {"mode": "off"}},
        "http_bodies": [],
        "query_params": {"mode": "allowlist", "terms": []},
        "graphql": {"document": False, "variables": False},
        "gen_ai": {"inputs": False, "outputs": False},
        "database_query_data": False,
        "queues": False,
        "stack_frame_variables": False,
        "frame_context_lines": 5,
    }

    integrations = {type(integration): integration for integration in options["integrations"]}
    assert FastApiIntegration in integrations
    assert StarletteIntegration in integrations
    assert integrations[AnthropicIntegration].include_prompts is False
    assert integrations[OpenAIIntegration].include_prompts is False

    logging_integration = integrations[LoggingIntegration]
    assert logging_integration._breadcrumb_handler.level == logging.WARNING
    assert logging_integration._handler.level == logging.WARNING
    assert logging_integration._sentry_logs_handler.level == logging.WARNING


def test_init_sentry_uses_configured_environment(monkeypatch) -> None:
    from server import observability

    init_calls: list[dict] = []
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: init_calls.append(kwargs),
    )

    assert observability.init_sentry() is True
    assert init_calls[0]["environment"] == "staging"


def test_init_sentry_initializes_only_once(monkeypatch) -> None:
    from server import observability

    init_calls: list[dict] = []
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: init_calls.append(kwargs),
    )

    assert observability.init_sentry() is True
    assert observability.init_sentry() is True
    assert len(init_calls) == 1


def test_create_app_initializes_sentry_before_fastapi(monkeypatch) -> None:
    from server import app as app_module

    calls: list[str] = []
    real_fastapi = app_module.FastAPI

    monkeypatch.setattr(
        app_module,
        "init_sentry",
        lambda: calls.append("sentry"),
    )

    def recording_fastapi(*args, **kwargs):
        calls.append("fastapi")
        return real_fastapi(*args, **kwargs)

    monkeypatch.setattr(app_module, "FastAPI", recording_fastapi)

    app_module.create_app()

    assert calls[:2] == ["sentry", "fastapi"]


def test_record_generation_outcome_does_not_raise_without_sentry_init(
    monkeypatch,
) -> None:
    from server import observability

    monkeypatch.delenv("SENTRY_DSN", raising=False)

    observability.record_generation_outcome("math", "success")


def test_record_generation_outcome_records_success_for_known_subject(
    monkeypatch,
) -> None:
    from server import observability

    metric_calls: list[dict] = []

    def capture_count(name: str, value: int, **kwargs) -> None:
        metric_calls.append({"name": name, "value": value, **kwargs})

    monkeypatch.setattr(observability.sentry_sdk.metrics, "count", capture_count)

    observability.record_generation_outcome("math", "success")

    assert metric_calls == [
        {
            "name": "generation.outcome",
            "value": 1,
            "attributes": {"outcome": "success", "subject": "math"},
        }
    ]


def test_record_generation_outcome_records_failure(monkeypatch) -> None:
    from server import observability

    metric_calls: list[dict] = []

    def capture_count(name: str, value: int, **kwargs) -> None:
        metric_calls.append({"name": name, "value": value, **kwargs})

    monkeypatch.setattr(observability.sentry_sdk.metrics, "count", capture_count)

    observability.record_generation_outcome("math", "failure")

    assert metric_calls == [
        {
            "name": "generation.outcome",
            "value": 1,
            "attributes": {"outcome": "failure", "subject": "math"},
        }
    ]


def test_record_generation_outcome_sanitizes_unknown_subject(monkeypatch) -> None:
    from server import observability

    metric_calls: list[dict] = []

    def capture_count(name: str, value: int, **kwargs) -> None:
        metric_calls.append({"name": name, "value": value, **kwargs})

    monkeypatch.setattr(observability.sentry_sdk.metrics, "count", capture_count)

    observability.record_generation_outcome("fake", "success")

    assert metric_calls == [
        {
            "name": "generation.outcome",
            "value": 1,
            "attributes": {"outcome": "success", "subject": "other"},
        }
    ]


# ---------------------------------------------------------------------------
# Issue #901 — resolve_sentry_release() and release tagging
# ---------------------------------------------------------------------------


def test_resolve_sentry_release_uses_sentry_release_when_set(monkeypatch) -> None:
    from server import observability

    monkeypatch.setenv("SENTRY_RELEASE", "v1.2.3")
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)

    assert observability.resolve_sentry_release() == "v1.2.3"


def test_resolve_sentry_release_falls_back_to_railway_sha(monkeypatch) -> None:
    from server import observability

    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123def456")

    assert observability.resolve_sentry_release() == "abc123def456"


def test_resolve_sentry_release_returns_none_when_neither_set(monkeypatch) -> None:
    from server import observability

    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)

    assert observability.resolve_sentry_release() is None


def test_resolve_sentry_release_sentry_release_wins_over_railway_sha(monkeypatch) -> None:
    from server import observability

    monkeypatch.setenv("SENTRY_RELEASE", "explicit-release")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-should-be-ignored")

    assert observability.resolve_sentry_release() == "explicit-release"


def test_resolve_sentry_release_treats_empty_sentry_release_as_unset(monkeypatch) -> None:
    from server import observability

    monkeypatch.setenv("SENTRY_RELEASE", "")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "fallback-sha")

    assert observability.resolve_sentry_release() == "fallback-sha"


def test_resolve_sentry_release_treats_empty_railway_sha_as_unset(monkeypatch) -> None:
    from server import observability

    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "")

    assert observability.resolve_sentry_release() is None


def test_init_sentry_passes_release_when_resolved(monkeypatch) -> None:
    from server import observability

    init_calls: list[dict] = []
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setenv("SENTRY_RELEASE", "v2.0.0")
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: init_calls.append(kwargs),
    )

    assert observability.init_sentry() is True
    assert init_calls[0]["release"] == "v2.0.0"


def test_init_sentry_passes_railway_sha_as_release_when_sentry_release_unset(
    monkeypatch,
) -> None:
    from server import observability

    init_calls: list[dict] = []
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deadbeef")
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: init_calls.append(kwargs),
    )

    assert observability.init_sentry() is True
    assert init_calls[0]["release"] == "deadbeef"


def test_init_sentry_omits_release_key_when_neither_set(monkeypatch) -> None:
    from server import observability

    init_calls: list[dict] = []
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: init_calls.append(kwargs),
    )

    assert observability.init_sentry() is True
    # The key must be absent entirely — not present as None — so the SDK's own
    # auto-detection (e.g. from SENTRY_RELEASE env) is not suppressed.
    assert "release" not in init_calls[0]
