"""Persistence seam tests for the 參考範例紀錄 feature (#670)."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.generate.models import GenerateParams
from server.generate.persistence import (
    make_reference_example_record_recorder,
    persist_aborted_generation_record,
    persist_failed_generation_record,
    persist_generation_record,
)
from server.models import Base, GenerationLog, GenerationRecord, User


def _make_factory(rows: list[Any]) -> Any:
    @asynccontextmanager
    async def factory():
        class FakeSession:
            def add(self, row: Any) -> None:
                rows.append(row)

            async def commit(self) -> None:
                pass

        yield FakeSession()

    return factory


_EXAMPLE_ENTRY = {
    "code": "reference_example",
    "kind": "example",
    "question_id": "test-q",
    "stage": "generator",
    "slot": None,
    "description": "test example description",
    "source": "/some/path/to/few_shot",
    "content": {"題目": "test question"},
    "images": [],
    "timestamp": "2026-09-10T00:00:00Z",
}


def test_completed_math_generation_persists_the_reference_example_record() -> None:
    rows: list[Any] = []
    expected = [_EXAMPLE_ENTRY]

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="math",
            params=GenerateParams(subject="math"),
            payload={"id": "math-ref"},
            reference_example_record_json=expected,
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].reference_example_record_json == expected


def test_completed_social_studies_generation_persists_the_reference_example_record() -> None:
    rows: list[Any] = []
    expected = [
        {
            "code": "reference_example",
            "kind": "example",
            "question_id": "ss-ref",
            "stage": "generator",
            "slot": None,
            "description": "ss example",
            "source": "/ss/few_shot",
            "content": {"題目": "ss question"},
            "images": [],
            "timestamp": "2026-09-10T00:00:00Z",
        }
    ]

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="social_studies",
            params=GenerateParams(subject="social_studies"),
            payload={"id": "ss-ref"},
            reference_example_record_json=expected,
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].reference_example_record_json == expected


def test_incremental_reference_example_recorder_persists_each_entry(tmp_path) -> None:
    async def exercise() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ref.db'}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            session_factory = async_sessionmaker(
                engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )
            user_id = uuid.uuid4()
            log_id = uuid.uuid4()
            async with session_factory() as session:
                session.add(User(id=user_id, email="ref@example.com"))
                session.add(
                    GenerationLog(
                        id=log_id,
                        user_id=user_id,
                        params_json={"subject": "math"},
                        status="started",
                    )
                )
                await session.commit()

            recorder = make_reference_example_record_recorder(
                generation_log_id=log_id,
                loop=asyncio.get_running_loop(),
                session_factory=session_factory,
            )
            # Recorder accepts plain dicts directly
            await asyncio.to_thread(recorder, _EXAMPLE_ENTRY)

            async with session_factory() as session:
                log = await session.get(GenerationLog, log_id)
                assert log is not None
                assert log.reference_example_record_json == {"disabled": False, "entries": [_EXAMPLE_ENTRY]}
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_incremental_reference_example_recorder_retries_a_transient_commit_failure(
    tmp_path,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ref-retry.db'}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            real_session_factory = async_sessionmaker(
                engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )
            user_id = uuid.uuid4()
            log_id = uuid.uuid4()
            async with real_session_factory() as session:
                session.add(User(id=user_id, email="ref-retry@example.com"))
                session.add(
                    GenerationLog(
                        id=log_id,
                        user_id=user_id,
                        params_json={"subject": "math"},
                        status="started",
                    )
                )
                await session.commit()

            attempts = 0

            @asynccontextmanager
            async def flaky_session_factory():
                nonlocal attempts
                async with real_session_factory() as real_session:
                    class SessionProxy:
                        async def execute(self, statement: Any) -> Any:
                            return await real_session.execute(statement)

                        async def commit(self) -> None:
                            nonlocal attempts
                            attempts += 1
                            if attempts == 1:
                                raise RuntimeError("transient database failure")
                            await real_session.commit()

                    yield SessionProxy()

            recorder = make_reference_example_record_recorder(
                generation_log_id=log_id,
                loop=asyncio.get_running_loop(),
                session_factory=flaky_session_factory,
            )
            await asyncio.to_thread(recorder, _EXAMPLE_ENTRY)

            async with real_session_factory() as session:
                log = await session.get(GenerationLog, log_id)
                assert log is not None
                assert log.reference_example_record_json == {"disabled": False, "entries": [_EXAMPLE_ENTRY]}
            assert attempts == 2
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_aborted_generation_copies_the_incrementally_staged_reference_example_record(
    tmp_path,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ref-abort.db'}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            session_factory = async_sessionmaker(
                engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )
            user_id = uuid.uuid4()
            log_id = uuid.uuid4()
            async with session_factory() as session:
                session.add(User(id=user_id, email="ref-aborted@example.com"))
                session.add(
                    GenerationLog(
                        id=log_id,
                        user_id=user_id,
                        params_json={"subject": "math"},
                        status="started",
                        reference_example_record_json=[_EXAMPLE_ENTRY],
                    )
                )
                await session.commit()

            await persist_aborted_generation_record(
                user_id=user_id,
                generation_log_id=log_id,
                subject="math",
                params=GenerateParams(subject="math"),
                session_factory=session_factory,
            )

            async with session_factory() as session:
                record = (
                    await session.execute(
                        select(GenerationRecord).where(
                            GenerationRecord.generation_log_id == log_id
                        )
                    )
                ).scalar_one()
                assert record.status == "aborted"
                assert record.reference_example_record_json == [_EXAMPLE_ENTRY]
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_failed_generation_copies_the_incrementally_staged_reference_example_record(
    tmp_path,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ref-failed.db'}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            session_factory = async_sessionmaker(
                engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )
            user_id = uuid.uuid4()
            log_id = uuid.uuid4()
            async with session_factory() as session:
                session.add(User(id=user_id, email="ref-failed@example.com"))
                session.add(
                    GenerationLog(
                        id=log_id,
                        user_id=user_id,
                        params_json={"subject": "math"},
                        status="started",
                        reference_example_record_json=[_EXAMPLE_ENTRY],
                    )
                )
                await session.commit()

            await persist_failed_generation_record(
                user_id=user_id,
                generation_log_id=log_id,
                subject="math",
                params=GenerateParams(subject="math"),
                error="generation failed with error",
                session_factory=session_factory,
            )

            async with session_factory() as session:
                record = (
                    await session.execute(
                        select(GenerationRecord).where(
                            GenerationRecord.generation_log_id == log_id
                        )
                    )
                ).scalar_one()
                assert record.status == "failed"
                assert record.reference_example_record_json == [_EXAMPLE_ENTRY]
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_make_reference_example_record_recorder_returns_none_when_log_id_is_none() -> None:
    """Disable the recorder when no generation log is being tracked."""
    loop = asyncio.new_event_loop()
    try:
        recorder = make_reference_example_record_recorder(
            generation_log_id=None,
            loop=loop,
            session_factory=_make_factory([]),
        )
        assert recorder is None
    finally:
        loop.close()
