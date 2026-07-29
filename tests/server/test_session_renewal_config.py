"""Tests for login-session renewal configuration."""

from __future__ import annotations

import pytest

from server.config import ServerConfig


def test_session_renewal_threshold_defaults_to_360_minutes() -> None:
    config = ServerConfig()

    assert config.session_renewal_threshold_minutes == 360


def test_session_renewal_threshold_loads_from_environment(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SESSION_RENEWAL_THRESHOLD_MINUTES", "180")

    config = ServerConfig.from_env(env_file=tmp_path / ".env.missing")

    assert config.session_renewal_threshold_minutes == 180


def test_validate_rejects_renewal_threshold_above_half_jwt_lifetime() -> None:
    # 7 days = 10080 minutes; half = 5040; 6000 > 5040 should fail
    config = ServerConfig(
        api_key="test-api-key",
        jwt_secret="test-secret",
        jwt_expire_days=7,
        session_renewal_threshold_minutes=6000,
    )

    with pytest.raises(ValueError) as exc_info:
        config.validate()

    message = str(exc_info.value)
    assert "SESSION_RENEWAL_THRESHOLD_MINUTES=6000" in message
    assert "JWT_EXPIRE_DAYS=7" in message


def test_validate_accepts_360_minute_threshold_for_seven_day_jwt() -> None:
    config = ServerConfig(
        api_key="test-api-key",
        jwt_secret="test-secret",
        jwt_expire_days=7,
        session_renewal_threshold_minutes=360,
    )

    config.validate()
