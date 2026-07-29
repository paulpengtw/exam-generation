"""Tests for login-session renewal configuration."""

from __future__ import annotations

import pytest

from server.config import ServerConfig


def test_session_renewal_threshold_defaults_to_two_days() -> None:
    config = ServerConfig()

    assert config.session_renewal_threshold_days == 2


def test_session_renewal_threshold_loads_from_environment(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SESSION_RENEWAL_THRESHOLD_DAYS", "3")

    config = ServerConfig.from_env(env_file=tmp_path / ".env.missing")

    assert config.session_renewal_threshold_days == 3


def test_validate_rejects_renewal_threshold_above_half_jwt_lifetime() -> None:
    config = ServerConfig(
        api_key="test-api-key",
        jwt_secret="test-secret",
        jwt_expire_days=7,
        session_renewal_threshold_days=4,
    )

    with pytest.raises(ValueError) as exc_info:
        config.validate()

    message = str(exc_info.value)
    assert "SESSION_RENEWAL_THRESHOLD_DAYS=4" in message
    assert "JWT_EXPIRE_DAYS=7" in message


def test_validate_accepts_two_day_threshold_for_seven_day_jwt() -> None:
    config = ServerConfig(
        api_key="test-api-key",
        jwt_secret="test-secret",
        jwt_expire_days=7,
        session_renewal_threshold_days=2,
    )

    config.validate()
