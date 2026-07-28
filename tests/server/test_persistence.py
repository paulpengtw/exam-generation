"""Unit tests for server.generate.persistence — injected write sinks, no real DB.

Covers:
  - persist_generation_record: row inserted, image_base64 stripped, image_files collected
  - persist_generation_record: failure is logged-and-swallowed (generation continues)
  - make_exchange_recorder: disabled when log_id is None or retention_days <= 0
  - make_exchange_recorder: writes LLMExchange row on llm_response
  - make_exchange_recorder: write failure is logged-and-swallowed
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest

from server.generate.models import GenerateParams
from server.generate.persistence import make_exchange_recorder, persist_generation_record
from server.models import LLMExchange

# ─────────────────────────────────────────────────────────────────────────────
# Session-factory helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_factory(rows: list) -> Any:
    """Return an async context-manager session factory that records added objects."""

    @asynccontextmanager
    async def factory():
        class _FakeSession:
            def add(self, obj: Any) -> None:
                rows.append(obj)

            async def commit(self) -> None:
                pass

        yield _FakeSession()

    return factory


@asynccontextmanager
async def _failing_factory():
    raise RuntimeError("DB is down")
    yield  # unreachable — satisfies type checker


# ─────────────────────────────────────────────────────────────────────────────
# persist_generation_record
# ─────────────────────────────────────────────────────────────────────────────


def test_persist_generation_record_inserts_one_row() -> None:
    rows: list = []
    factory = _make_factory(rows)
    params = GenerateParams(subject="math", skip_verify=True)
    payload: dict[str, Any] = {"id": "q1", "text": "hello"}

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=uuid.uuid4(),
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
    )

    assert len(rows) == 1
    record = rows[0]
    assert record.question_id == "q1"
    assert record.subject == "math"


def test_persist_generation_record_strips_image_base64() -> None:
    rows: list = []
    params = GenerateParams(subject="math", skip_verify=True)
    payload: dict[str, Any] = {
        "id": "q2",
        "image_base64": "DEADBEEF==",
        "subquestions": [{"id": "s1", "image_base64": "BEEF=="}],
    }

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="math",
            params=params,
            payload=payload,
            session_factory=_make_factory(rows),
        )
    )

    stored = rows[0].question_json
    assert "image_base64" not in stored
    assert "image_base64" not in stored["subquestions"][0]


def test_persist_generation_record_collects_image_files() -> None:
    rows: list = []
    params = GenerateParams(subject="math", skip_verify=True)
    payload: dict[str, Any] = {
        "id": "q3",
        "圖片": "q3.png",
        "subquestions": [{"圖片": "sq1.png"}, {"other": "x"}],
    }

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="math",
            params=params,
            payload=payload,
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].image_files == ["q3.png", "sq1.png"]


def test_persist_generation_record_swallows_db_failure(caplog: pytest.LogCaptureFixture) -> None:
    """A broken session factory must not propagate — generation must continue."""
    params = GenerateParams(subject="math", skip_verify=True)

    with caplog.at_level(logging.WARNING):
        asyncio.run(
            persist_generation_record(
                user_id=uuid.uuid4(),
                generation_log_id=None,
                subject="math",
                params=params,
                payload={"id": "q4"},
                session_factory=_failing_factory,
            )
        )

    assert any("persist" in r.getMessage().lower() for r in caplog.records)


# ─────────────────────────────────────────────────────────────────────────────
# make_exchange_recorder — disabled cases
# ─────────────────────────────────────────────────────────────────────────────


def test_make_exchange_recorder_none_when_log_id_is_none() -> None:
    loop = asyncio.new_event_loop()
    try:
        recorder = make_exchange_recorder(
            generation_log_id=None,
            retention_days=30,
            loop=loop,
            session_factory=None,
            next_order=None,
        )
        assert recorder is None
    finally:
        loop.close()


def test_make_exchange_recorder_none_when_retention_days_zero() -> None:
    loop = asyncio.new_event_loop()
    try:
        recorder = make_exchange_recorder(
            generation_log_id=uuid.uuid4(),
            retention_days=0,
            loop=loop,
            session_factory=None,
            next_order=None,
        )
        assert recorder is None
    finally:
        loop.close()


def test_make_exchange_recorder_none_when_retention_days_negative() -> None:
    loop = asyncio.new_event_loop()
    try:
        recorder = make_exchange_recorder(
            generation_log_id=uuid.uuid4(),
            retention_days=-1,
            loop=loop,
            session_factory=None,
            next_order=None,
        )
        assert recorder is None
    finally:
        loop.close()


# ─────────────────────────────────────────────────────────────────────────────
# make_exchange_recorder — write path
# ─────────────────────────────────────────────────────────────────────────────


def _run_loop_in_background(loop: asyncio.AbstractEventLoop) -> threading.Thread:
    """Start *loop* running in a daemon thread; returns the thread."""
    ready = threading.Event()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    ready.wait(timeout=2)
    return t


def test_make_exchange_recorder_writes_llm_exchange_row() -> None:
    rows: list = []
    log_id = uuid.uuid4()
    loop = asyncio.new_event_loop()
    t = _run_loop_in_background(loop)
    try:
        order = [0]

        def next_order() -> int:
            order[0] += 1
            return order[0]

        recorder = make_exchange_recorder(
            generation_log_id=log_id,
            retention_days=30,
            loop=loop,
            session_factory=_make_factory(rows),
            next_order=next_order,
        )
        assert recorder is not None

        recorder({
            "type": "llm_request",
            "agent": "generator",
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hi"}],
            "params": {"max_tokens": 100},
        })
        recorder({
            "type": "llm_response",
            "agent": "generator",
            "model": "claude-sonnet-4-6",
            "content": "answer",
            "reasoning": None,
            "usage": {"input": 5, "output": 3},
        })

        # Allow the threadsafe future to resolve.
        time.sleep(0.3)

        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, LLMExchange)
        assert row.generation_log_id == log_id
        assert row.agent == "generator"
        assert row.exchange_order == 1
        assert row.prompt_tokens == 5
        assert row.completion_tokens == 3
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        loop.close()


def test_make_exchange_recorder_write_failure_is_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing write sink must not propagate — generation must continue."""
    loop = asyncio.new_event_loop()
    t = _run_loop_in_background(loop)
    try:
        order = [0]

        def next_order() -> int:
            order[0] += 1
            return order[0]

        recorder = make_exchange_recorder(
            generation_log_id=uuid.uuid4(),
            retention_days=30,
            loop=loop,
            session_factory=_failing_factory,
            next_order=next_order,
        )
        assert recorder is not None

        with caplog.at_level(logging.WARNING):
            recorder({
                "type": "llm_request",
                "agent": "gen",
                "model": "m",
                "messages": [],
                "params": {},
            })
            recorder({
                "type": "llm_response",
                "agent": "gen",
                "model": "m",
                "content": "ok",
                "reasoning": None,
                "usage": {"input": 1, "output": 1},
            })
            time.sleep(0.3)

        assert any("insert" in r.getMessage().lower() for r in caplog.records)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        loop.close()
