"""Tests for the live observer registry (issue #909).

These tests exercise subscribe_live, unsubscribe_live, is_live_available, and
_publish_live from server.generate.run without touching the database or the
full generation pipeline.
"""

from __future__ import annotations

import asyncio

import pytest

from server.generate.run import (
    _live_observers,
    _publish_live,
    is_live_available,
    subscribe_live,
    unsubscribe_live,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the global observer registry before and after each test."""
    _live_observers.clear()
    yield
    _live_observers.clear()


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
