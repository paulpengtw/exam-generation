"""Tests for the live observer registry (issue #909).

These tests cover two layers:
1. Unit tests for subscribe_live, unsubscribe_live, is_live_available, and
   _publish_live from server.generate.run without touching the database.
2. Observer-never-affects-run integration tests that drive execute_run with a
   stubbed generation stream to verify that a misbehaving observer (disconnect
   mid-run, full queue, or broken put_nowait) never blocks or crashes the run.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.config import ServerConfig
from server.generate.run import (
    _live_observers,
    _publish_live,
    accept_run,
    claim_next_run,
    execute_run,
    is_live_available,
    subscribe_live,
    unsubscribe_live,
)
from server.generate.subjects import SUBJECTS
from server.models import Base, User
from tests.server.generate_test_utils import resolved_generate_params

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the global observer registry before and after each test."""
    _live_observers.clear()
    yield
    _live_observers.clear()


@pytest.fixture(autouse=True)
def _quiet_outcome_metric():
    with patch("server.observability.record_generation_outcome"):
        yield


# ---------------------------------------------------------------------------
# Unit tests — subscribe_live / unsubscribe_live / is_live_available / _publish_live
# ---------------------------------------------------------------------------


def test_subscribe_makes_run_live():
    """subscribe_live registers a queue and is_live_available returns True."""
    async def _run():
        queue = await subscribe_live("run-abc")
        assert is_live_available("run-abc")
        assert queue is not None

    asyncio.run(_run())


def test_unsubscribe_removes_queue_but_keeps_slot():
    """Removing a queue leaves the run's slot intact (is_live_available stays True).

    The slot is only removed by execute_run's finally block, not by observers
    disconnecting.  This ensures is_live_available means 'run executing in this
    process', not 'has observers'.
    """
    async def _run():
        queue = await subscribe_live("run-abc")
        assert is_live_available("run-abc")
        await unsubscribe_live("run-abc", queue)
        # Slot still exists even with zero observers.
        assert "run-abc" in _live_observers
        assert _live_observers["run-abc"] == []
        # is_live_available checks slot existence, not observer count.
        assert is_live_available("run-abc")
        # Clean up manually (normally done by execute_run's finally).
        _live_observers.pop("run-abc", None)
        assert not is_live_available("run-abc")

    asyncio.run(_run())


def test_publish_delivers_to_all_observers():
    """_publish_live puts the event on every registered queue for that run."""
    async def _run():
        q1 = await subscribe_live("run-xyz")
        q2 = await subscribe_live("run-xyz")
        event = {"event": "question_update", "payload": {"question_id": "q-1"}}
        await _publish_live("run-xyz", event)
        assert q1.get_nowait() == event
        assert q2.get_nowait() == event

    asyncio.run(_run())


def test_publish_does_not_deliver_to_other_run():
    """Events published for one run_id do not reach observers for a different run."""
    async def _run():
        queue_a = await subscribe_live("run-A")
        queue_b = await subscribe_live("run-B")
        await _publish_live("run-A", {"event": "ping"})
        await unsubscribe_live("run-A", queue_a)
        await unsubscribe_live("run-B", queue_b)
        # queue_a has the event; queue_b received nothing
        assert not queue_a.empty()
        assert queue_b.empty()
        # clean up slots manually
        _live_observers.pop("run-A", None)
        _live_observers.pop("run-B", None)

    asyncio.run(_run())


def test_publish_drops_on_overflow_and_does_not_raise():
    """_publish_live drops events silently when the observer queue is full."""
    async def _run():
        queue = await subscribe_live("run-full")
        # Fill the queue to its maxsize (256).
        event = {"event": "question_update", "payload": {}}
        for _ in range(queue.maxsize):
            queue.put_nowait(event)
        assert queue.full()
        # Publishing one more should NOT raise, and queue stays full.
        await _publish_live("run-full", {"event": "overflow"})
        assert queue.full()
        assert queue.qsize() == queue.maxsize
        _live_observers.pop("run-full", None)

    asyncio.run(_run())


def test_is_live_available_true_when_slot_exists_but_no_observers():
    """is_live_available returns True for an empty observer list (run is executing)."""
    _live_observers["run-empty"] = []
    assert is_live_available("run-empty")
    _live_observers.pop("run-empty", None)
    assert not is_live_available("run-empty")


# ---------------------------------------------------------------------------
# Observer-never-affects-run integration tests (issue #909 item 2)
#
# These tests confirm that execute_run completes successfully regardless of what
# its observers do: disconnect mid-run, let the queue overflow, or raise on put.
# ---------------------------------------------------------------------------


class _FakeObsClient:
    """Minimal LLM stand-in for observer tests — emits no events."""

    def __init__(self, config: Any) -> None:
        pass

    def set_observer(self, cb: Any) -> None:
        pass

    def clear_observer(self) -> None:
        pass

    def emit(self, event: dict) -> None:
        pass


def _obs_generate(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
    """Stubbed generate that returns a valid minimal question."""
    from src.schemas import ExamQuestion

    return ExamQuestion(
        id=kwargs.get("question_id", "q-obs-1"),
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[{"編碼": "A-7-7", "說明": "lc"}],
        題目=["stem"],
        正確解題分析=["answer"],
        核心素養=["數-J-A2"],
        學習表現=[{"編碼": "s-IV-12", "說明": "lp"}],
    )


def _obs_subjects() -> dict:
    return {"math": dataclasses.replace(SUBJECTS["math"], do_generate=_obs_generate)}


_OBS_PARAMS: dict[str, Any] = {
    "subject": "math", "seed": 99, "grade": 8, "context": ["個人"],
    "set_type": "單一題", "q_type": ["選擇題"], "style": ["text_only"],
    "math_thinking": ["形成"], "learning_content": ["A-7-7"],
    "learning_performance": ["s-IV-12"], "core_competency": ["數-J-A2"],
    "content_type": "純文字", "skip_verify": True, "count": 1,
}


async def _setup_claimed_run(tmp_path: Path) -> tuple[Any, Any, Any]:
    """Create DB, accept a run, claim it; return (claimed, sessions, engine)."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'obs.db'}"
    engine = create_async_engine(db_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    owner = uuid.uuid4()
    async with sessions() as session:
        session.add(User(id=owner, email="obs@example.com"))
        await session.commit()

    params = resolved_generate_params(_OBS_PARAMS)
    async with sessions() as session:
        await accept_run(params, owner, session=session)

    claimed = await claim_next_run(sessions, host_id="obs-test-host")
    assert claimed is not None
    return claimed, sessions, engine


def _app_state() -> Any:
    state = MagicMock()
    state.renderer_pool = None
    return state


def _server_config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(
        api_key="x", gemini_api_key="x",
        output_dir=tmp_path / "out", data_dir=Path("data"),
    )


def test_observer_disconnect_mid_run_does_not_block_execute_run(tmp_path: Path) -> None:
    """An observer that unsubscribes mid-run must not block execute_run.

    We subscribe before execute_run starts, consume one event, then unsubscribe.
    execute_run must still reach its finally block and complete the run.
    """
    async def _run() -> None:
        claimed, sessions, engine = await _setup_claimed_run(tmp_path)
        run_str_id = str(claimed.run_id)

        # Pre-register our queue so it is in the slot when execute_run starts.
        # execute_run's setdefault preserves it.
        observer_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        _live_observers[run_str_id] = [observer_queue]

        consumed: list[dict] = []

        async def _observer() -> None:
            """Consume one event then unsubscribe, simulating a disconnected client."""
            event = await asyncio.wait_for(observer_queue.get(), timeout=8.0)
            consumed.append(event)
            await unsubscribe_live(run_str_id, observer_queue)

        observer_task = asyncio.create_task(_observer())
        execute_task = asyncio.create_task(
            execute_run(
                claimed,
                app_state=_app_state(),
                config=_server_config(tmp_path),
                session_factory=sessions,
                host_id="obs-test-host",
                client_factory=_FakeObsClient,
                subjects=_obs_subjects(),
            )
        )

        # Both tasks must finish; the run must not hang after the observer left.
        await asyncio.wait_for(
            asyncio.gather(execute_task, observer_task, return_exceptions=True),
            timeout=20.0,
        )

        # execute_run finishes → slot removed.
        assert run_str_id not in _live_observers, "slot not cleaned up after run"
        # The observer got at least the first event it waited for.
        assert len(consumed) >= 1, "observer received no events"

        await engine.dispose()

    asyncio.run(_run())


def test_overflowed_observer_queue_does_not_block_execute_run(tmp_path: Path) -> None:
    """A full queue (256 items) causes events to be dropped, not execute_run to block.

    We pre-fill the observer queue to its maxsize, then start execute_run.
    All further published events silently drop; the run still completes.
    """
    async def _run() -> None:
        claimed, sessions, engine = await _setup_claimed_run(tmp_path)
        run_str_id = str(claimed.run_id)

        # Fill the queue before the run starts.
        full_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        filler = {"event": "question_update", "payload": {}}
        for _ in range(full_queue.maxsize):
            full_queue.put_nowait(filler)
        assert full_queue.full()

        _live_observers[run_str_id] = [full_queue]

        # execute_run must complete even though every put_nowait raises QueueFull.
        await asyncio.wait_for(
            execute_run(
                claimed,
                app_state=_app_state(),
                config=_server_config(tmp_path),
                session_factory=sessions,
                host_id="obs-test-host",
                client_factory=_FakeObsClient,
                subjects=_obs_subjects(),
            ),
            timeout=20.0,
        )

        # Slot cleaned up; queue still full (no new items were added).
        assert run_str_id not in _live_observers
        assert full_queue.full()

        await engine.dispose()

    asyncio.run(_run())


def test_broken_observer_queue_does_not_crash_execute_run(tmp_path: Path) -> None:
    """An observer queue whose put_nowait raises must not crash execute_run.

    _publish_live swallows all exceptions; the run must still complete and the
    slot must still be cleaned up.
    """
    async def _run() -> None:
        claimed, sessions, engine = await _setup_claimed_run(tmp_path)
        run_str_id = str(claimed.run_id)

        # Inject a broken queue that always raises on put_nowait.
        class _BrokenQueue:
            maxsize = 256

            def put_nowait(self, _item: Any) -> None:
                raise RuntimeError("injected observer error")

        _live_observers[run_str_id] = [_BrokenQueue()]  # type: ignore[list-item]

        # execute_run must not raise; the broken queue's exception is swallowed.
        await asyncio.wait_for(
            execute_run(
                claimed,
                app_state=_app_state(),
                config=_server_config(tmp_path),
                session_factory=sessions,
                host_id="obs-test-host",
                client_factory=_FakeObsClient,
                subjects=_obs_subjects(),
            ),
            timeout=20.0,
        )

        # Slot cleaned up regardless of the broken queue.
        assert run_str_id not in _live_observers

        await engine.dispose()

    asyncio.run(_run())
