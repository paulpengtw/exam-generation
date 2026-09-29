"""Tests that entries from two attempts are retained and labelled (issue #906, task 2.5).

Red before green: this file is written before the refactoring so the test
drives the implementation.  Entries from attempt 1 carry no explicit 'attempt'
field (the conventional label "no field = attempt 1"); entries from attempt 2
carry 'attempt: 2'.  This keeps the assertion shapes of the existing persistence
tests unchanged while still allowing entries from different attempts to be
distinguished by recovery.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.generate.persistence import (
    _IncrementalTrailStager,
    make_figure_policy_trail_recorder,
    make_reference_example_record_recorder,
)
from server.models import Base, GenerationLog, User
from src.common.figure_policy_trail import FigurePolicySpecEntry


def test_figure_policy_trail_entries_from_two_attempts_are_retained_and_labelled(
    tmp_path: Path,
) -> None:
    """Both attempts' entries appear in the column; attempt-2 entries carry attempt: 2."""

    async def exercise() -> None:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / 'trail-two-attempts.db'}"
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session_factory = async_sessionmaker(
                engine, expire_on_commit=False, class_=AsyncSession
            )
            user_id = uuid.uuid4()
            log_id = uuid.uuid4()
            async with session_factory() as session:
                session.add(User(id=user_id, email="trail-two-attempts@example.com"))
                session.add(
                    GenerationLog(
                        id=log_id,
                        user_id=user_id,
                        params_json={"subject": "social_studies"},
                        status="started",
                    )
                )
                await session.commit()

            entry1 = FigurePolicySpecEntry(
                question_id="q-attempt-1",
                label="題幹",
                effective_figure_kind="地圖",
                timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
            recorder1 = make_figure_policy_trail_recorder(
                generation_log_id=log_id,
                loop=asyncio.get_running_loop(),
                session_factory=session_factory,
                attempt=1,
            )
            await asyncio.to_thread(recorder1, entry1)

            # Attempt 2 starts fresh; caller passes prior entries so both are retained.
            entry2 = FigurePolicySpecEntry(
                question_id="q-attempt-2",
                label="題幹",
                effective_figure_kind="照片",
                timestamp=datetime(2026, 9, 2, tzinfo=timezone.utc),
            )
            recorder2 = make_figure_policy_trail_recorder(
                generation_log_id=log_id,
                loop=asyncio.get_running_loop(),
                session_factory=session_factory,
                attempt=2,
                prior_entries=recorder1.snapshot(),
            )
            await asyncio.to_thread(recorder2, entry2)

            async with session_factory() as session:
                log = await session.get(GenerationLog, log_id)
                assert log is not None
                trail = log.figure_policy_trail_json
                # Both entries are retained.
                assert len(trail) == 2
                # Attempt-1 entry: no 'attempt' field (conventional label).
                assert trail[0] == entry1.model_dump(mode="json")
                assert "attempt" not in trail[0]
                # Attempt-2 entry: explicitly labelled.
                assert trail[1].get("attempt") == 2
                # Base content matches (minus the attempt tag).
                base2 = {k: v for k, v in trail[1].items() if k != "attempt"}
                assert base2 == entry2.model_dump(mode="json")
        finally:
            await engine.dispose()

    asyncio.run(exercise())


_ENTRY_ATTEMPT_1 = {
    "code": "reference_example",
    "kind": "example",
    "question_id": "q-attempt-1",
    "stage": "generator",
    "slot": None,
    "description": "attempt 1 description",
    "source": "/path/few_shot",
    "content": {"題目": "q1"},
    "images": [],
    "timestamp": "2026-09-01T00:00:00Z",
}

_ENTRY_ATTEMPT_2 = {
    "code": "reference_example",
    "kind": "example",
    "question_id": "q-attempt-2",
    "stage": "generator",
    "slot": None,
    "description": "attempt 2 description",
    "source": "/path/few_shot",
    "content": {"題目": "q2"},
    "images": [],
    "timestamp": "2026-09-02T00:00:00Z",
}


def test_reference_example_record_entries_from_two_attempts_are_retained_and_labelled(
    tmp_path: Path,
) -> None:
    """Both attempts' entries appear in entries[]; attempt-2 entries carry attempt: 2."""

    async def exercise() -> None:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / 'ref-two-attempts.db'}"
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session_factory = async_sessionmaker(
                engine, expire_on_commit=False, class_=AsyncSession
            )
            user_id = uuid.uuid4()
            log_id = uuid.uuid4()
            async with session_factory() as session:
                session.add(User(id=user_id, email="ref-two-attempts@example.com"))
                session.add(
                    GenerationLog(
                        id=log_id,
                        user_id=user_id,
                        params_json={"subject": "math"},
                        status="started",
                    )
                )
                await session.commit()

            recorder1 = make_reference_example_record_recorder(
                generation_log_id=log_id,
                loop=asyncio.get_running_loop(),
                session_factory=session_factory,
                attempt=1,
            )
            await asyncio.to_thread(recorder1, _ENTRY_ATTEMPT_1)

            recorder2 = make_reference_example_record_recorder(
                generation_log_id=log_id,
                loop=asyncio.get_running_loop(),
                session_factory=session_factory,
                attempt=2,
                prior_entries=recorder1.snapshot(),
            )
            await asyncio.to_thread(recorder2, _ENTRY_ATTEMPT_2)

            async with session_factory() as session:
                log = await session.get(GenerationLog, log_id)
                assert log is not None
                stored = log.reference_example_record_json
                # Column shape preserved: {disabled, entries}.
                assert set(stored.keys()) >= {"disabled", "entries"}
                entries = stored["entries"]
                assert len(entries) == 2
                # Attempt-1 entry: no 'attempt' field.
                assert entries[0] == _ENTRY_ATTEMPT_1
                assert "attempt" not in entries[0]
                # Attempt-2 entry: explicitly labelled.
                assert entries[1].get("attempt") == 2
                base2 = {k: v for k, v in entries[1].items() if k != "attempt"}
                assert base2 == _ENTRY_ATTEMPT_2
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_stage_snapshot_is_called_while_lock_is_held() -> None:
    """Regression: _stage_snapshot must be called inside the threading lock.

    When _stage_snapshot escapes the lock (the 23d053a regression), two
    concurrent workers can schedule their snapshots out of order: a smaller
    stale snapshot submitted later overwrites a newer, larger one.

    Verified by subclassing _IncrementalTrailStager so that _stage_snapshot
    records whether ``self._lock.locked()`` is True at the moment of the call.
    threading.Lock.locked() returns True while any thread holds the lock; since
    add_entry calls _stage_snapshot from the same thread that acquired the lock,
    locked() is True if and only if the call is made inside the with-block.
    """
    lock_held_at_stage: list[bool] = []

    class InspectableStager(_IncrementalTrailStager):
        def _stage_snapshot(self, snapshot: list) -> None:  # type: ignore[override]
            lock_held_at_stage.append(self._lock.locked())

    loop = asyncio.new_event_loop()
    # Loop is not started; InspectableStager._stage_snapshot overrides the
    # real implementation so asyncio.run_coroutine_threadsafe is never called.
    stager = InspectableStager(
        generation_log_id=uuid.uuid4(),
        loop=loop,
        session_factory=None,
        column_name="test_column",
        render_column_value=lambda entries: entries,
    )
    try:
        stager.add_entry({"foo": "bar"})
        stager.add_entry({"baz": "qux"})
    finally:
        loop.close()

    assert lock_held_at_stage == [True, True], (
        "_stage_snapshot must be called while self._lock is held (regression "
        "for 23d053a where the call was moved outside the with-block, enabling "
        "concurrent threads to schedule snapshots out of order)"
    )
