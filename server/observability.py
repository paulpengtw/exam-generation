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


def init_sentry() -> bool:
    """Initialize Sentry when a backend DSN is configured."""
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
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT") or "production",
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
    _initialized = True
    return True
