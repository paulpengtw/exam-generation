"""Exchange persistence outcomes through the recorder and authenticated read API."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.generate import persistence
from server.models import Base, GenerationLog, User


@dataclass
class ExchangeStore:
    sessions: async_sessionmaker[AsyncSession]
    client: httpx.AsyncClient
    log_id: uuid.UUID
    user_id: uuid.UUID

    async def exchanges(self) -> list[dict[str, Any]]:
        response = await self.client.get(f"/api/generation-logs/{self.log_id}/exchanges")
        assert response.status_code == 200
        return response.json()


@asynccontextmanager
async def exchange_store(tmp_path: Path) -> AsyncIterator[ExchangeStore]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'exchanges.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, log_id = uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(User(id=user_id, email="exchange-test@example.com"))
            session.add(GenerationLog(
                id=log_id, user_id=user_id, params_json={}, status="started",
            ))
            await session.commit()

        async def get_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session

        config = ServerConfig(api_key="test-key", jwt_secret="exchange-test-secret")
        app = create_app()
        app.dependency_overrides[get_async_session] = get_session
        app.dependency_overrides[get_config] = lambda: config
        token = create_jwt(user_id, "exchange-test@example.com", config=config)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield ExchangeStore(sessions, client, log_id, user_id)
    finally:
        await engine.dispose()


def record_exchange(recorder: Any, agent: str = "sub_generator#1") -> None:
    recorder({
        "type": "llm_request", "agent": agent, "model": "test-model",
        "messages": [{"role": "user", "content": "PRIVATE_PROMPT"}],
        "params": {"api_key": "PRIVATE_CREDENTIAL"},
    })
    recorder({
        "type": "llm_response", "agent": agent, "model": "test-model",
        "content": "PRIVATE_ANSWER", "reasoning": "PRIVATE_REASONING",
        "usage": {"input": 5, "output": 3},
    })


async def delayed_exchange(
    store: ExchangeStore,
    error: BaseException | None = None,
    *,
    expect_commit: bool = True,
) -> None:
    """Hold a real commit until the observer returns, then read its eventual row."""
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def delayed_sessions():
        try:
            async with store.sessions() as session:
                class DelayedSession:
                    def add(self, row: Any) -> None:
                        session.add(row)

                    async def commit(self) -> None:
                        entered.set()
                        await release.wait()
                        if error is not None:
                            raise error
                        await session.commit()

                yield DelayedSession()
        finally:
            finished.set()

    recorder = persistence.make_exchange_recorder(
        generation_log_id=store.log_id, retention_days=30,
        loop=asyncio.get_running_loop(), session_factory=delayed_sessions,
        next_order=lambda: 7,
    )
    worker = asyncio.create_task(asyncio.to_thread(record_exchange, recorder))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(asyncio.shield(worker), timeout=12)
        assert await store.exchanges() == []
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=2)
        await worker

    rows = await store.exchanges()
    expected = [("sub_generator#1", 7)] if error is None and expect_commit else []
    assert [(row["agent"], row["exchange_order"]) for row in rows] == expected


def test_wait_timeout_identifies_pending_exchange_that_eventually_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    # Only the time budget changes; scheduling, waiting and committing stay real.
    monkeypatch.setattr(persistence, "EXCHANGE_WRITE_TIMEOUT_SECONDS", 0.05, raising=False)
    caplog.set_level(logging.WARNING, logger="server.generate.persistence")

    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            await delayed_exchange(store)
            warning = next(r for r in caplog.records if r.name == "server.generate.persistence")
            assert getattr(warning, "error_type", None) == "TimeoutError"
            assert warning.outcome == "pending"
            assert warning.generation_log_id == str(store.log_id)
            assert warning.agent == "sub_generator#1"
            assert warning.exchange_order == 7
            assert warning.exc_info is None
            assert "PRIVATE_" not in repr(warning.__dict__)

    asyncio.run(exercise())


@pytest.mark.parametrize("delayed", [False, True])
def test_rejected_insert_reports_real_database_error_without_sql_or_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    delayed: bool,
) -> None:
    monkeypatch.setattr(persistence, "EXCHANGE_WRITE_TIMEOUT_SECONDS", 0.05)
    caplog.set_level(logging.WARNING, logger="server.generate.persistence")

    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            # A real DB rejection: its SQLAlchemy exception includes bound exchange bodies.
            async with store.sessions() as session:
                await session.execute(text(
                    "CREATE TRIGGER reject_exchange BEFORE INSERT ON llm_exchanges "
                    "BEGIN SELECT RAISE(ABORT, 'PRIVATE_DATABASE_MESSAGE'); END"
                ))
                await session.commit()
            if delayed:
                await delayed_exchange(store, expect_commit=False)
            else:
                recorder = persistence.make_exchange_recorder(
                    generation_log_id=store.log_id, retention_days=30,
                    loop=asyncio.get_running_loop(), session_factory=store.sessions,
                    next_order=lambda: 7,
                )
                await asyncio.to_thread(record_exchange, recorder)
                assert await store.exchanges() == []
            warnings = [r for r in caplog.records if r.name == "server.generate.persistence"]
            expected_outcomes = ["pending", "failed"] if delayed else ["failed"]
            assert [r.outcome for r in warnings] == expected_outcomes
            assert warnings[-1].error_type == "IntegrityError"
            assert warnings[-1].error_module == "sqlalchemy.exc"
            assert warnings[-1].generation_log_id == str(store.log_id)
            assert warnings[-1].agent == "sub_generator#1"
            assert warnings[-1].exchange_order == 7
            assert all(r.exc_info is None for r in warnings)
            assert "PRIVATE_" not in repr([r.__dict__ for r in warnings])
            assert "INSERT INTO" not in repr([r.__dict__ for r in warnings])

    asyncio.run(exercise())


def test_deferred_exchange_reports_its_eventual_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(persistence, "EXCHANGE_WRITE_TIMEOUT_SECONDS", 0.05)
    caplog.set_level(logging.WARNING, logger="server.generate.persistence")

    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            await delayed_exchange(store)
            warnings = [r for r in caplog.records if r.name == "server.generate.persistence"]
            assert [r.outcome for r in warnings] == ["pending", "committed"]
            assert warnings[-1].error_type is None
            assert warnings[-1].generation_log_id == str(store.log_id)
            assert warnings[-1].agent == "sub_generator#1"
            assert warnings[-1].exchange_order == 7

    asyncio.run(exercise())


def test_deferred_exchange_reports_cancellation_and_is_absent_from_read_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(persistence, "EXCHANGE_WRITE_TIMEOUT_SECONDS", 0.05)
    caplog.set_level(logging.WARNING, logger="server.generate.persistence")

    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            await delayed_exchange(store, asyncio.CancelledError("PRIVATE_CANCELLATION"))
            warnings = [r for r in caplog.records if r.name == "server.generate.persistence"]
            assert [r.outcome for r in warnings] == ["pending", "cancelled"]
            assert warnings[-1].error_type == "CancelledError"
            assert warnings[-1].generation_log_id == str(store.log_id)
            assert "PRIVATE_" not in repr([r.__dict__ for r in warnings])

    asyncio.run(exercise())


@pytest.mark.parametrize("error_class", [TimeoutError, DatabaseTimeoutError])
def test_database_timeout_is_terminal_and_identifies_its_exception_module(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, error_class: type[Exception],
) -> None:
    caplog.set_level(logging.WARNING, logger="server.generate.persistence")

    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            @asynccontextmanager
            async def unavailable_database():
                raise error_class("PRIVATE_DATABASE_TIMEOUT")
                yield  # pragma: no cover

            recorder = persistence.make_exchange_recorder(
                generation_log_id=store.log_id, retention_days=30,
                loop=asyncio.get_running_loop(), session_factory=unavailable_database,
                next_order=lambda: 7,
            )
            await asyncio.to_thread(record_exchange, recorder)
            assert await store.exchanges() == []
            warnings = [r for r in caplog.records if r.name == "server.generate.persistence"]
            assert [r.outcome for r in warnings] == ["failed"]
            assert warnings[0].error_type == "TimeoutError"
            expected_module = "builtins" if error_class is TimeoutError else "sqlalchemy.exc"
            assert getattr(warnings[0], "error_module", None) == expected_module
            assert "PRIVATE_" not in repr(warnings[0].__dict__)

    asyncio.run(exercise())


def test_closed_loop_reports_unscheduled_exchange_without_leaking_a_coroutine(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, recwarn: pytest.WarningsRecorder,
) -> None:
    caplog.set_level(logging.WARNING)

    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            closed_loop = asyncio.new_event_loop()
            closed_loop.close()
            recorder = persistence.make_exchange_recorder(
                generation_log_id=store.log_id, retention_days=30, loop=closed_loop,
                session_factory=store.sessions, next_order=lambda: 7,
            )
            await asyncio.to_thread(record_exchange, recorder)
            assert await store.exchanges() == []
            warning = next(r for r in caplog.records if r.name.startswith("server.generate"))
            assert getattr(warning, "outcome", None) == "not_scheduled"
            assert warning.error_type == "RuntimeError"
            assert warning.generation_log_id == str(store.log_id)
            assert warning.agent == "sub_generator#1"
            assert warning.exchange_order == 7
            assert not [w for w in recwarn if "was never awaited" in str(w.message)]

    asyncio.run(exercise())
