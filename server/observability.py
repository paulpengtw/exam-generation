"""Backend observability configuration."""

from __future__ import annotations

import logging
import os

import sentry_sdk
from sentry_sdk.integrations.anthropic import AnthropicIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.openai import OpenAIIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

_initialized = False

PLANNER_DIAGNOSTIC_MARKER = "planner_diagnostic"
PLANNER_LOGGER_NAME = "server.generate.routes"
_PROVIDER_INTEGRATION_MECHANISMS = frozenset({"anthropic", "openai"})


def _is_provider_integration_event(event: dict) -> bool:
    """Identify raw unhandled events emitted inside provider SDK wrappers."""

    values = (event.get("exception") or {}).get("values") or []
    return any(
        (mechanism := value.get("mechanism") or {}).get("type")
        in _PROVIDER_INTEGRATION_MECHANISMS
        and mechanism.get("handled") is False
        for value in values
    )


def _before_send(event: dict, hint: dict) -> dict | None:
    """Keep safe operational signals while dropping duplicate provider SDK events.

    Anthropic and OpenAI integrations call ``capture_event`` inside the SDK
    wrapper before application code can normalize the provider exception.  The
    resulting unhandled event is both noisy and may carry provider response
    text, so ADR 0004's allowlist drops that event here.  The integrations stay
    enabled for their GenAI tracing; the application WARNING or sanitized
    planner event remains the operational signal.

    The logging integration records the planner warning as a breadcrumb
    alongside the sanitized planner event.  Filtering only the explicitly
    marked warning therefore preserves that diagnostic while unrelated warning
    and error events continue through unchanged.
    """
    if _is_provider_integration_event(event):
        return None
    if (
        event.get("level") == "warning"
        and event.get("logger") == PLANNER_LOGGER_NAME
        and (event.get("extra") or {}).get(PLANNER_DIAGNOSTIC_MARKER) is True
    ):
        return None
    return event


def record_generation_outcome(subject: str, outcome: str) -> None:
    """Record one completed generation outcome."""
    sanitized_subject = (
        subject
        if subject in {"math", "social_studies", "natural_sciences"}
        else "other"
    )
    sentry_sdk.metrics.count(
        "generation.outcome",
        1,
        attributes={"outcome": outcome, "subject": sanitized_subject},
    )


def resolve_sentry_release() -> str | None:
    """Resolve the Sentry release tag from environment variables.

    Priority order:
    1. ``SENTRY_RELEASE`` — explicit operator override.
    2. ``RAILWAY_GIT_COMMIT_SHA`` — commit SHA injected by Railway at deploy time.
    3. ``None`` — neither is available; Sentry initialises without a release tag
       so the SDK can apply its own auto-detection if desired.

    Empty-string values are treated as unset.
    """
    for var in ("SENTRY_RELEASE", "RAILWAY_GIT_COMMIT_SHA"):
        value = os.environ.get(var)
        if value:
            return value
    return None


def init_sentry(*, transport: object | None = None) -> bool:
    """Initialize Sentry when a backend DSN is configured.

    ``transport`` is an injectable SDK transport used by backend tests; the
    production callers leave it unset so the SDK selects its normal transport.
    """
    global _initialized

    if _initialized:
        return True

    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False

    # ADR 0004: pin every supported collection category so SDK defaults cannot leak content.
    data_collection = {
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
    init_kwargs: dict = dict(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT") or "production",
        before_send=_before_send,
        traces_sample_rate=1.0,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        include_source_context=True,
        enable_logs=True,
        _experiments={"data_collection": data_collection},
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            AnthropicIntegration(include_prompts=False),
            OpenAIIntegration(include_prompts=False),
            LoggingIntegration(
                level=logging.WARNING,
                event_level=logging.WARNING,
                sentry_logs_level=logging.WARNING,
            ),
        ],
    )
    # Issue #901: tag every event with the build's release identifier when one
    # is available.  The key is omitted entirely when unresolved so the SDK's
    # own auto-detection (e.g. from SENTRY_RELEASE env) is not suppressed.
    release = resolve_sentry_release()
    if release is not None:
        init_kwargs["release"] = release
    if transport is not None:
        init_kwargs["transport"] = transport

    sentry_sdk.init(**init_kwargs)
    _initialized = True
    return True
