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
import dataclasses
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from server.generate.marshalling import EMITTED_EVENT_NAMES, SSEEventName
from server.generate.publisher import GenerationPublisher
from server.generate.subjects import SUBJECTS
from src.social_studies.schemas import (
    ExamQuestion,
    QuestionMetadata,
    QuestionType,
)

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
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    return GenerationPublisher(run_id="abc123", loop=loop, queue=queue), loop, queue


def test_publisher_initial_seq_is_one() -> None:
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pub = GenerationPublisher(run_id="abc", loop=loop, queue=queue)
    try:
        assert pub.next_seq() == 1
    finally:
        loop.close()


def test_publisher_seq_is_monotonic() -> None:
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

    assert "event" in envelope, "envelope must have top-level 'event' key for v1 compat"
    assert "context" in envelope, "envelope must have 'context' key"
    assert "payload" in envelope, "envelope must have 'payload' key"
    assert envelope["event"] == "question_terminal"
    ctx = envelope["context"]
    assert ctx["run_id"] == "myrun"
    assert isinstance(ctx["event_seq"], int)
    assert ctx["event_seq"] >= 1
    assert envelope["payload"] == {"status": "ok"}


# ---------------------------------------------------------------------------
# _RunContext wiring
# ---------------------------------------------------------------------------


def test_run_context_has_publisher_field() -> None:
    import dataclasses as _dc

    from server.generate.service import _RunContext

    fields = {f.name for f in _dc.fields(_RunContext)}
    assert "publisher" in fields


# ---------------------------------------------------------------------------
# Slice 4 additions: full-stream publisher tests
# ---------------------------------------------------------------------------


def _make_ss_spec_s4():
    def _fake_gen(rng_params, overrides, **kwargs):
        return ExamQuestion(
            id=kwargs["question_id"],
            情境=[c for c in rng_params.情境],
            題型種類=rng_params.題型種類,
            題型=rng_params.題型[0] if rng_params.題型 else QuestionType("選擇題"),
            題目內容類型=rng_params.題目內容類型,
            取材來源=list(rng_params.學習內容_pool),
            metadata=QuestionMetadata(grade=rng_params.grade, model="test-model"),
        )

    return dataclasses.replace(SUBJECTS["social_studies"], do_generate=_fake_gen)


def _run_stream_s4(tmp_path):
    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from tests.server.generate_test_utils import resolved_generate_params

    fake_spec = _make_ss_spec_s4()
    params = resolved_generate_params({
        "subject": "social_studies", "skip_verify": True, "count": 1,
    })
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    app_state = SimpleNamespace(renderer_pool=None)
    events = []

    async def collect():
        async for ev in generate_question_stream(
            params, config, app_state,
            subjects={"social_studies": fake_spec},
        ):
            events.append(ev)

    asyncio.run(collect())
    return events


def test_started_event_seq_is_1_in_full_stream(tmp_path) -> None:
    """In a full stream, started must be item 0 with context.event_seq==1."""
    events = _run_stream_s4(tmp_path)
    assert events, "no events"
    item0 = events[0]
    assert item0.get("event") == "started"
    ctx = item0.get("context", {})
    assert ctx.get("event_seq") == 1, f"first event_seq must be 1, got {ctx.get('event_seq')}"


def test_all_v2_envelopes_have_strictly_increasing_event_seq(tmp_path) -> None:
    """Every {context, payload} envelope must have strictly increasing event_seq with no gaps."""
    events = _run_stream_s4(tmp_path)
    v2_events = [e for e in events if "context" in e and "payload" in e]
    seqs = [e["context"]["event_seq"] for e in v2_events]
    assert seqs == list(range(1, len(seqs) + 1)), (
        f"event_seqs not strictly increasing from 1: {seqs}"
    )


def test_context_has_no_event_key(tmp_path) -> None:
    """The 'context' dict inside a v2 envelope must NOT contain an 'event' key."""
    events = _run_stream_s4(tmp_path)
    v2_events = [e for e in events if "context" in e and "payload" in e]
    for ev in v2_events:
        ctx = ev["context"]
        assert "event" not in ctx, f"context must not have 'event' key, got: {ctx}"


def test_publisher_deep_copy_prevents_mutation_affecting_queued_payload() -> None:
    """Mutating a dict after publish() must not change the queued payload."""
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pub = GenerationPublisher(run_id="r", loop=loop, queue=queue)
    mutable = {"x": 1}

    async def run():
        pub.publish("result", payload=mutable)
        await asyncio.sleep(0)
        mutable["x"] = 999  # mutate after publish
        return await queue.get()

    envelope = loop.run_until_complete(run())
    loop.close()
    assert envelope["payload"]["x"] == 1, "deep copy failed: mutation affected queued payload"


def test_publisher_sidecars_attached_to_envelope() -> None:
    """Sidecars dict keys must appear at the top level of the queued envelope."""
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pub = GenerationPublisher(run_id="r", loop=loop, queue=queue)

    async def run():
        pub.publish("result", payload={"id": "q1"}, sidecars={"verification_trail": [1, 2, 3]})
        await asyncio.sleep(0)
        return await queue.get()

    envelope = loop.run_until_complete(run())
    loop.close()
    assert "verification_trail" in envelope, f"sidecar missing from envelope: {envelope}"
    assert envelope["verification_trail"] == [1, 2, 3]
