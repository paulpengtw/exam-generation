"""Persistence seam tests for the 社會領域 圖像種類 policy trail."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.generate.models import GenerateParams
from server.generate.persistence import (
    make_figure_policy_trail_recorder,
    persist_aborted_generation_record,
    persist_generation_record,
)
from server.models import Base, GenerationLog, GenerationRecord, User
from src.common.figure_policy_trail import FigurePolicySpecEntry


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


def test_completed_social_generation_persists_the_figure_policy_trail() -> None:
    rows: list[Any] = []
    expected_trail = [
        {
            "code": "figure_policy",
            "kind": "spec",
            "question_id": "ss-policy",
            "label": "題幹",
            "effective_figure_kind": "地圖",
            "timestamp": "2026-08-25T00:00:00Z",
        }
    ]

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="social_studies",
            params=GenerateParams(subject="social_studies"),
            payload={"id": "ss-policy"},
            figure_policy_trail_json=expected_trail,
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].figure_policy_trail_json == expected_trail


def test_completed_natural_sciences_generation_persists_the_same_trail_field() -> None:
    rows: list[Any] = []
    expected_trail = [
        {
            "code": "figure_policy",
            "kind": "warning",
            "question_id": "ns-policy",
            "message": "duplicate image shipped",
            "duplicate_image_shipped": True,
            "left": "題幹",
            "right": "小題 1",
            "effective_figure_kind": "實驗裝置",
            "timestamp": "2026-08-25T00:00:00Z",
        }
    ]

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="natural_sciences",
            params=GenerateParams(subject="natural_sciences"),
            payload={"id": "ns-policy"},
            figure_policy_trail_json=expected_trail,
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].figure_policy_trail_json == expected_trail


def test_incremental_figure_policy_recorder_persists_each_prefix(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'policy.db'}")
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
                session.add(User(id=user_id, email="policy@example.com"))
                session.add(
                    GenerationLog(
                        id=log_id,
                        user_id=user_id,
                        params_json={"subject": "social_studies"},
                        status="started",
                    )
                )
                await session.commit()

            recorder = make_figure_policy_trail_recorder(
                generation_log_id=log_id,
                loop=asyncio.get_running_loop(),
                session_factory=session_factory,
            )
            entry = FigurePolicySpecEntry(
                question_id="ss-policy",
                label="題幹",
                effective_figure_kind="地圖",
                timestamp=datetime(2026, 8, 25, tzinfo=timezone.utc),
            )
            await asyncio.to_thread(recorder, entry)

            async with session_factory() as session:
                log = await session.get(GenerationLog, log_id)
                assert log is not None
                assert log.figure_policy_trail_json == [entry.model_dump(mode="json")]
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_incremental_figure_policy_recorder_retries_a_transient_commit_failure(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}")
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
                session.add(User(id=user_id, email="policy-retry@example.com"))
                session.add(
                    GenerationLog(
                        id=log_id,
                        user_id=user_id,
                        params_json={"subject": "social_studies"},
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

            recorder = make_figure_policy_trail_recorder(
                generation_log_id=log_id,
                loop=asyncio.get_running_loop(),
                session_factory=flaky_session_factory,
            )
            entry = FigurePolicySpecEntry(
                question_id="ss-policy-retry",
                label="題幹",
                effective_figure_kind="地圖",
                timestamp=datetime(2026, 8, 25, tzinfo=timezone.utc),
            )
            await asyncio.to_thread(recorder, entry)

            async with real_session_factory() as session:
                log = await session.get(GenerationLog, log_id)
                assert log is not None
                assert log.figure_policy_trail_json == [entry.model_dump(mode="json")]
            assert attempts == 2
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_aborted_generation_copies_the_incrementally_staged_policy_prefix(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'abort.db'}")
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
            entry = {
                "code": "figure_policy",
                "kind": "spec",
                "question_id": "ss-interrupted",
                "label": "題幹",
                "effective_figure_kind": "地圖",
                "timestamp": "2026-08-25T00:00:00Z",
            }
            async with session_factory() as session:
                session.add(User(id=user_id, email="aborted-policy@example.com"))
                session.add(
                    GenerationLog(
                        id=log_id,
                        user_id=user_id,
                        params_json={"subject": "social_studies"},
                        status="started",
                        figure_policy_trail_json=[entry],
                    )
                )
                await session.commit()

            await persist_aborted_generation_record(
                user_id=user_id,
                generation_log_id=log_id,
                subject="social_studies",
                params=GenerateParams(subject="social_studies"),
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
                assert record.figure_policy_trail_json == [entry]
        finally:
            await engine.dispose()

    asyncio.run(exercise())
