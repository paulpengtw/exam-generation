"""Bounded, content-safe diagnostics for exhausted fixed subquestion slots."""

from __future__ import annotations

from typing import Literal

SubquestionFailureCode = Literal[
    "validation_exhausted",
    "parser_failure",
    "provider_failure",
    "unknown",
]

MAX_FAILURE_DETAIL_CHARS = 240
MAX_EXCEPTION_CLASS_CHARS = 64


def sanitize_failure_detail(value: str | None) -> str | None:
    """Collapse whitespace and bound an already-safe diagnostic detail."""
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    return normalized[:MAX_FAILURE_DETAIL_CHARS]


def sanitize_exception_class(exc: BaseException) -> str:
    """Return only identifier characters from an exception's class name."""
    class_name = type(exc).__name__
    sanitized = "".join(
        character
        for character in class_name
        if character.isalnum() or character == "_"
    )[:MAX_EXCEPTION_CLASS_CHARS]
    return sanitized or "Exception"
