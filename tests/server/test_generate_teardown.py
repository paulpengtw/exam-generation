"""Public SSE teardown behavior for generation-history tombstones."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationRecord, User
from server.rate_limit import limiter


async def _run_asgi(
    app: Any,
    *,
    disconnect_after_first_body: bool,
) -> list[dict[str, Any]]:
    """Drive one GET request through the ASGI interface and collect sent messages."""
    disconnect_ready = asyncio.Event()
    request_sent = False
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        if disconnect_after_first_body:
            await disconnect_ready.wait()
            return {"type": "http.disconnect"}
        await asyncio.Event().wait()
        raise AssertionError("the response should finish before another request message")

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        if (
            disconnect_after_first_body
            and message["type"] == "http.response.body"
            and message.get("body")
        ):
            disconnect_ready.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/generate",
        "raw_path": b"/api/generate",
        "query_string": b"subject=math&count=1",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }

    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    return sent


async def _test_generate_stream_teardown_distinguishes_disconnect_from_generation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'teardown.db'}",
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    user = User(id=uuid.uuid4(), email="u@example.com")
    async with session_factory() as session:
        session.add(user)
        await session.commit()

    config = ServerConfig(
        api_key="test-key",
        jwt_secret="test-secret",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )

    dependency_sessions: list[AsyncSession] = []

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        session = session_factory()
        dependency_sessions.append(session)
        yield session

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config

    from server.generate import routes as generate_routes

    monkeypatch.setattr(generate_routes, "AsyncSessionLocal", session_factory)

    async def disconnected_stream(
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        yield {"event": "started", "data": ""}
        await asyncio.Event().wait()

    monkeypatch.setattr(generate_routes, "generate_question_stream", disconnected_stream)
    limiter.reset()
    try:
        await _run_asgi(app, disconnect_after_first_body=True)

        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(GenerationRecord).order_by(GenerationRecord.created_at.asc())
                )
            ).scalars().all()

        assert [row.status for row in rows] == ["aborted"]
        assert rows[0].error is None
        assert rows[0].question_json is None
        assert rows[0].params_json["subject"] == "math"

        async def generation_error_stream(
            *_args: Any, **_kwargs: Any
        ) -> AsyncGenerator[dict[str, Any], None]:
            raise RuntimeError("boom")
            yield  # pragma: no cover — make this an async generator

        monkeypatch.setattr(generate_routes, "generate_question_stream", generation_error_stream)
        await _run_asgi(app, disconnect_after_first_body=False)

        async with session_factory() as session:
            error_rows = (
                await session.execute(
                    select(GenerationRecord).order_by(GenerationRecord.created_at.asc())
                )
            ).scalars().all()[1:]

        assert [row.status for row in error_rows] == ["failed"]
        assert error_rows[0].error == "Stream error (RuntimeError)"
        assert all(row.status != "aborted" for row in error_rows)
    finally:
        limiter.reset()
        for session in dependency_sessions:
            await session.close()
        await engine.dispose()


def test_generate_stream_teardown_distinguishes_disconnect_from_generation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _test_generate_stream_teardown_distinguishes_disconnect_from_generation_error(
            tmp_path,
            monkeypatch,
        )
    )
