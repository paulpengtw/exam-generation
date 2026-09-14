"""Slice 4 – GenerationPublisher tests.

Tests ensure:
1. GenerationPublisher assigns strictly monotonic event_seq.
2. Concurrent publishes from threads produce strictly ordered seq (no gaps, no dups).
3. Emitted envelopes use the {context, payload} structure.
4. QUESTION_TERMINAL is present in SSEEventName and EMITTED_EVENT_NAMES.
5. Publisher is wired into _RunContext (has 'publisher' field).
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from server.generate.marshalling import EMITTED_EVENT_NAMES, SSEEventName

# ---------------------------------------------------------------------------
# SSEEventName / EMITTED_EVENT_NAMES
# ---------------------------------------------------------------------------


def test_question_terminal_in_sse_event_name() -> None:
    assert SSEEventName.QUESTION_TERMINAL == "question_terminal"


def test_question_terminal_in_emitted_event_names() -> None:
    assert "question_terminal" in EMITTED_EVENT_NAMES


# ---------------------------------------------------------------------------
# GenerationPublisher structural tests
# ---------------------------------------------------------------------------


def _make_publisher() -> Any:
    from server.generate.publisher import GenerationPublisher

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    return GenerationPublisher(run_id="abc123", loop=loop, queue=queue), loop, queue


def test_publisher_initial_seq_is_one() -> None:
    from server.generate.publisher import GenerationPublisher

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pub = GenerationPublisher(run_id="abc", loop=loop, queue=queue)
    try:
        assert pub.next_seq() == 1
    finally:
        loop.close()


def test_publisher_seq_is_monotonic() -> None:
    from server.generate.publisher import GenerationPublisher

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pub = GenerationPublisher(run_id="abc", loop=loop, queue=queue)
    try:
        seqs = [pub.next_seq() for _ in range(5)]
        assert seqs == list(range(1, 6))
    finally:
        loop.close()


def test_publisher_concurrent_seqs_unique_and_monotonic() -> None:
    """Multiple threads calling next_seq() should get unique, monotonically ordered values."""
    from server.generate.publisher import GenerationPublisher

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pub = GenerationPublisher(run_id="abc", loop=loop, queue=queue)
    results: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        seq = pub.next_seq()
        with lock:
            results.append(seq)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    loop.close()

    assert sorted(results) == list(range(1, 21)), "seqs must be 1..20 with no dups"


def test_publisher_publish_enqueues_v2_envelope() -> None:
    """publish() must put a {context, payload} envelope onto the queue."""
    from server.generate.publisher import GenerationPublisher

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pub = GenerationPublisher(run_id="myrun", loop=loop, queue=queue)

    # Run the event loop briefly to let call_soon_threadsafe fire
    async def _drain() -> dict:
        pub.publish("question_terminal", question_id="myrun_001", index=0, payload={"status": "ok"})
        await asyncio.sleep(0)
        return await queue.get()

    envelope = loop.run_until_complete(_drain())
    loop.close()

    assert "context" in envelope, "envelope must have 'context' key"
    assert "payload" in envelope, "envelope must have 'payload' key"
    ctx = envelope["context"]
    assert ctx["run_id"] == "myrun"
    assert isinstance(ctx["event_seq"], int)
    assert ctx["event_seq"] >= 1
    assert envelope["payload"] == {"status": "ok"}


# ---------------------------------------------------------------------------
# _RunContext wiring
# ---------------------------------------------------------------------------


def test_run_context_has_publisher_field() -> None:
    import dataclasses

    from server.generate.service import _RunContext

    fields = {f.name for f in dataclasses.fields(_RunContext)}
    assert "publisher" in fields
