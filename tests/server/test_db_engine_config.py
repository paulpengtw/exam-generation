from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server import db


def test_asyncpg_engine_kwargs_include_default_connect_timeout() -> None:
    kwargs = db.build_async_engine_kwargs("postgresql+asyncpg://localhost/example", {})

    assert kwargs["connect_args"] == {"timeout": 10}


def test_asyncpg_engine_kwargs_honor_connect_timeout_env_override() -> None:
    kwargs = db.build_async_engine_kwargs(
        "postgresql+asyncpg://localhost/example",
        {"DATABASE_CONNECT_TIMEOUT_SECONDS": "12.5"},
    )

    assert kwargs["connect_args"] == {"timeout": 12.5}


@pytest.mark.parametrize(
    "raw_timeout",
    ["", "not-a-number", "0", "-1"],
)
def test_asyncpg_engine_kwargs_default_invalid_connect_timeout(
    raw_timeout: str,
) -> None:
    kwargs = db.build_async_engine_kwargs(
        "postgresql+asyncpg://localhost/example",
        {"DATABASE_CONNECT_TIMEOUT_SECONDS": raw_timeout},
    )

    assert kwargs["connect_args"] == {"timeout": 10}


def test_sqlite_engine_kwargs_do_not_include_connect_args() -> None:
    kwargs = db.build_async_engine_kwargs("sqlite+aiosqlite:///./test.db", {})

    assert "connect_args" not in kwargs


def test_shared_async_engine_configures_pre_ping_and_recycling() -> None:
    assert db.engine.pool._pre_ping is True
    assert db.engine.pool._recycle == 300
