"""Tests for JWT session-origin claims."""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.auth import tokens
from server.auth.tokens import create_jwt, decode_jwt
from server.config import ServerConfig


def _config() -> ServerConfig:
    return ServerConfig(api_key="test-api-key", jwt_secret="test-secret")


def test_create_jwt_sets_new_session_origin_to_issued_at() -> None:
    config = _config()

    token = create_jwt(uuid.uuid4(), "teacher@example.com", config=config)
    payload = decode_jwt(token, config=config)

    assert payload["origin"] == payload["iat"]


def test_create_jwt_preserves_supplied_session_origin() -> None:
    config = _config()
    original_session_started_at = 1_700_000_000

    token = create_jwt(
        uuid.uuid4(),
        "teacher@example.com",
        config=config,
        origin=original_session_started_at,
    )
    payload = decode_jwt(token, config=config)

    assert payload["origin"] == original_session_started_at


def test_session_origin_prefers_origin_claim() -> None:
    assert (
        tokens.session_origin({"origin": 1_700_000_000, "iat": 1_800_000_000})
        == 1_700_000_000
    )


def test_session_origin_falls_back_to_issued_at_for_legacy_token() -> None:
    assert tokens.session_origin({"iat": 1_700_000_000}) == 1_700_000_000
