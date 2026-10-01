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
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from server.generate.marshalling import EMITTED_EVENT_NAMES, SSEEventName
from server.generate.publisher import GenerationPublisher
from server.generate.subjects import SUBJECTS
from src.common.generation_events import QuestionContext, new_operation_scope
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
        pub.publish(
            "question_terminal",
            question_id="myrun_001",
            index=0,
            payload={
                "termination_reason": "normal",
                "has_final": True,
                "final_revision": 1,
                "delivery_status": "complete",
                "expected": [],
                "delivered": [],
                "missing": [],
                "review": {"status": "skipped", "content_revision": 1},
            },
        )
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
    assert envelope["payload"]["termination_reason"] == "normal"


def test_publisher_seal_rejects_new_work_and_conflicting_terminal() -> None:
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pub = GenerationPublisher(run_id="RUN", loop=loop, queue=queue)
    terminal = {
        "termination_reason": "normal",
        "has_final": True,
        "final_revision": 2,
        "delivery_status": "complete",
        "expected": [],
        "delivered": [],
        "missing": [],
        "review": {"status": "skipped", "content_revision": 2},
    }

    async def _run() -> list[dict[str, Any]]:
        pub.publish("question_terminal", question_id="RUN_001", index=0, payload=terminal)
        await asyncio.sleep(0)
        events = [await queue.get()]
        with pytest.raises(RuntimeError):
            pub.publish(
                "question_terminal",
                question_id="RUN_001",
                index=0,
                payload={**terminal, "termination_reason": "failed"},
            )
        with pytest.raises(RuntimeError):
            pub.publish(
                "stage",
                question_id="RUN_001",
                index=0,
                payload={"status": "start"},
            )
        pub.publish(
            "result",
            question_id="RUN_001",
            index=0,
            content_revision=2,
            payload={"id": "RUN_001"},
        )
        await asyncio.sleep(0)
        events.append(await queue.get())
        return events

    try:
        events = loop.run_until_complete(_run())
    finally:
        loop.close()

    assert [event["event"] for event in events] == ["question_terminal", "result"]


def test_publisher_carries_operation_and_call_scope_and_supersedes_marker() -> None:
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pub = GenerationPublisher(run_id="RUN", loop=loop, queue=queue)
    question = QuestionContext(run_id="RUN", question_id="q-1", index=0)
    scope = new_operation_scope(
        question,
        kind="subquestion",
        subquestion_index=1,
        supersedes_operation_id="RUN:operation:old",
    )
    try:
        async def _drain() -> dict:
            pub.publish(
                "stage",
                scope=scope,
                call_id="RUN:call:1",
                payload={"status": "start"},
            )
            await asyncio.sleep(0)
            return await queue.get()

        envelope = loop.run_until_complete(_drain())
    finally:
        loop.close()

    assert envelope["context"]["operation_id"] == scope.operation_id
    assert envelope["context"]["call_id"] == "RUN:call:1"
    assert envelope["context"]["subquestion_index"] == 1
    assert envelope["payload"]["supersedes_operation_id"] == "RUN:operation:old"


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


# ---------------------------------------------------------------------------
# Slice 4b: RED tests — all generation events through publisher
# ---------------------------------------------------------------------------



def _make_s4b_fake_spec():
    """Fake social-studies spec for slice 4b tests."""
    import threading

    barrier = threading.Barrier(2)
    returned_questions: list = []

    def _fake_do_generate(rng_params, overrides, **kwargs):
        question_id = kwargs["question_id"]
        client = kwargs["client"]
        observer = client.get_observer()

        # (1) Call observer with stage/llm events carrying 'marker' = question_id
        if observer:
            for ev in [
                {
                    "type": "stage",
                    "agent": "generator",
                    "stage": "llm_generate",
                    "status": "start",
                    "ts": 1.0,
                    "marker": question_id,
                },
                {
                    "type": "llm_request",
                    "purpose": "generate",
                    "agent": "generator",
                    "messages": [],
                    "marker": question_id,
                },
                {
                    "type": "llm_response",
                    "purpose": "generate",
                    "agent": "generator",
                    "content": "x",
                    "marker": question_id,
                },
                {
                    "type": "stage",
                    "agent": "generator",
                    "stage": "llm_generate",
                    "status": "end",
                    "ts": 2.0,
                    "marker": question_id,
                },
            ]:
                observer(ev)

        question = ExamQuestion(
            id=question_id,
            情境=[c for c in rng_params.情境],
            題型種類=rng_params.題型種類,
            題型=rng_params.題型[0] if rng_params.題型 else QuestionType("選擇題"),
            取材來源=[question_id],
            metadata=QuestionMetadata(grade=rng_params.grade, model="test-model"),
        )

        # (2) Emit draft update
        kwargs["on_question_update"](question, "draft")
        # (3) Barrier ensures concurrent workers
        try:
            barrier.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
        # (4) Emit verified update
        kwargs["on_question_update"](question, "verified")
        # (5) Keep reference for mutation test
        returned_questions.append(question)
        return question

    return dataclasses.replace(
        SUBJECTS["social_studies"], do_generate=_fake_do_generate
    ), returned_questions


def test_slice4b_full_stream_all_v2_envelopes(tmp_path, monkeypatch) -> None:  # noqa: PLR0912,PLR0915
    """Slice 4b: every yielded event must be a v2 {event, context, payload} envelope."""
    from pathlib import Path
    from types import SimpleNamespace

    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from tests.server.generate_test_utils import resolved_generate_params

    fake_spec, returned_questions = _make_s4b_fake_spec()
    params = resolved_generate_params(
        {"subject": "social_studies", "skip_verify": True, "count": 2}
    )
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    app_state = SimpleNamespace(renderer_pool=None)
    test_user_id = uuid.uuid4()

    persist_payloads: list[dict] = []

    async def _fake_persist(
        *,
        user_id,
        generation_log_id,
        subject,
        params,
        payload,
        session_factory,
        **_kwargs,
    ):
        persist_payloads.append(payload)

    monkeypatch.setattr(
        "server.generate.service.persist_generation_record", _fake_persist
    )

    events: list[dict] = []

    async def collect() -> None:
        async for ev in generate_question_stream(
            params,
            config,
            app_state,
            user_id=test_user_id,
            subjects={"social_studies": fake_spec},
        ):
            events.append(ev)

    asyncio.run(collect())

    # (a) Every item has event, context, payload; NO data key.
    for i, item in enumerate(events):
        assert "event" in item, f"item {i} missing 'event': {list(item.keys())}"
        assert "context" in item, f"item {i} missing 'context': {item}"
        assert "payload" in item, f"item {i} missing 'payload': {item}"
        assert "data" not in item, f"item {i} still has old 'data' key: {list(item.keys())}"

    # (b) item 0 is started with exactly {run_id, event_seq: 1}
    assert events[0]["event"] == "started", f"first event must be 'started'; got {events[0]['event']}"  # noqa: E501
    started_ctx = events[0]["context"]
    run_id = started_ctx["run_id"]
    assert started_ctx == {"run_id": run_id, "event_seq": 1}, (
        f"started context must be exactly {{run_id, event_seq: 1}}; got {started_ctx}"
    )

    # (c) event_seq is exactly 1..N in send order, no gaps or duplicates
    seqs = [e["context"]["event_seq"] for e in events]
    assert seqs == list(range(1, len(events) + 1)), (
        f"event_seqs must be 1..{len(events)}, no gaps or duplicates; got {seqs}"
    )

    # (d) marker events: context question_id == payload marker, index matches manifest
    manifest_map = {
        q["question_id"]: q["index"]
        for q in events[0]["payload"]["questions"]
    }
    marker_events = [e for e in events if "marker" in e.get("payload", {})]
    assert marker_events, "no marker events found (observer events not reaching publisher)"
    for e in marker_events:
        marker = e["payload"]["marker"]
        ctx = e["context"]
        assert "question_id" in ctx, f"marker event missing question_id in context: {ctx}"
        assert ctx["question_id"] == marker, (
            f"context question_id {ctx['question_id']!r} != marker {marker!r}"
        )
        assert "index" in ctx, f"marker event missing index in context: {ctx}"
        assert ctx["index"] == manifest_map[marker], (
            f"context index {ctx['index']} != manifest index {manifest_map[marker]}"
        )

    # (e) question_update events have correct context and payload shape
    update_events = [e for e in events if e["event"] == "question_update"]
    assert update_events, "no question_update events found"
    for e in update_events:
        ctx = e["context"]
        assert "question_id" in ctx, f"question_update missing question_id: {ctx}"
        assert "index" in ctx, f"question_update missing index: {ctx}"
        p = e["payload"]
        assert p["question"]["id"] == ctx["question_id"], (
            f"question.id {p['question']['id']!r} != context question_id {ctx['question_id']!r}"
        )
        assert p["phase"] in ("draft", "verified"), f"unexpected phase: {p['phase']!r}"

    # (f) pipeline events: question_start/end have question scope; pipeline_start/end have batch scope  # noqa: E501
    pipeline_events = [e for e in events if e["event"] == "pipeline"]
    for e in pipeline_events:
        ename = e["payload"].get("event_name", "")
        ctx = e["context"]
        if ename in ("question_start", "question_end"):
            assert "question_id" in ctx, f"{ename} missing question_id: {ctx}"
            assert "index" in ctx, f"{ename} missing index: {ctx}"
            assert e["payload"]["index"] == ctx["index"], (
                f"{ename} payload['index'] {e['payload']['index']} != context['index'] {ctx['index']}"  # noqa: E501
            )
        elif ename in ("pipeline_start", "pipeline_end"):
            assert "question_id" not in ctx, f"{ename} should not have question_id: {ctx}"
            assert "index" not in ctx, f"{ename} should not have index: {ctx}"

    # (g) result events: context question_id/index, payload['id'] matches, no transport keys
    result_events = [e for e in events if e["event"] == "result"]
    assert len(result_events) == 2, f"expected 2 result events; got {len(result_events)}"
    for e in result_events:
        ctx = e["context"]
        assert "question_id" in ctx
        assert "index" in ctx
        p = e["payload"]
        assert p.get("id") == ctx["question_id"], (
            f"result payload['id'] {p.get('id')!r} != context question_id {ctx['question_id']!r}"
        )
        for transport_key in ("context", "payload", "event_seq", "run_id"):
            assert transport_key not in p, (
                f"result payload must not contain transport key {transport_key!r}"
            )

    # (h) last item is done with batch scope and empty payload
    last = events[-1]
    assert last["event"] == "done", f"last event must be 'done'; got {last['event']}"
    assert "question_id" not in last["context"], "done must be batch scope (no question_id)"
    assert "index" not in last["context"], "done must be batch scope (no index)"
    assert last["payload"] == {}, f"done payload must be empty; got {last['payload']}"

    # (i) persist received payload == bare question dict (no transport envelope keys)
    assert len(persist_payloads) == 2, (
        f"expected 2 persist calls; got {len(persist_payloads)}"
    )
    for pp in persist_payloads:
        assert "id" in pp, f"persist payload missing 'id': {list(pp.keys())}"
        for transport_key in ("context", "payload", "event_seq", "run_id", "event"):
            assert transport_key not in pp, (
                f"persist payload must not contain transport key {transport_key!r}"
            )

    # (j) mutating returned question does not change collected result payload
    for q in returned_questions:
        q.取材來源 = ["MUTATED_BY_TEST"]
    for e in result_events:
        assert e["payload"].get("取材來源") != ["MUTATED_BY_TEST"], (
            "publisher deepcopy failed: mutation of returned question changed collected result"
        )


def test_slice4b_error_event_has_v2_context(tmp_path) -> None:
    """One failing worker produces a v2 error envelope with question_id/index."""
    from pathlib import Path
    from types import SimpleNamespace

    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from tests.server.generate_test_utils import resolved_generate_params

    def _fake_do_generate(rng_params, overrides, **kwargs):
        # Index 1 is _002; raise there
        if kwargs["question_id"].endswith("_002"):
            from src.llm_client import ProviderFailureContext

            exc = RuntimeError("boom")
            exc._provider_failure_context = ProviderFailureContext(  # type: ignore[attr-defined]
                provider="gemini",
                model="gemini-3.1-pro-preview",
                tier="execute",
                http_status=429,
                retry_after_seconds=12,
            )
            raise exc
        return ExamQuestion(
            id=kwargs["question_id"],
            情境=[c for c in rng_params.情境],
            題型種類=rng_params.題型種類,
            題型=rng_params.題型[0] if rng_params.題型 else QuestionType("選擇題"),
            取材來源=[],
            metadata=QuestionMetadata(grade=rng_params.grade, model="test-model"),
        )

    fake_spec = dataclasses.replace(
        SUBJECTS["social_studies"], do_generate=_fake_do_generate
    )
    params = resolved_generate_params(
        {"subject": "social_studies", "skip_verify": True, "count": 2}
    )
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    app_state = SimpleNamespace(renderer_pool=None)

    events: list[dict] = []

    async def collect() -> None:
        async for ev in generate_question_stream(
            params, config, app_state,
            subjects={"social_studies": fake_spec},
        ):
            events.append(ev)

    asyncio.run(collect())

    error_events = [e for e in events if e["event"] == "error"]
    assert error_events, "expected at least one error event"
    err = error_events[0]

    # Error envelope must be v2
    assert "context" in err, f"error event missing 'context': {list(err.keys())}"
    assert "payload" in err, f"error event missing 'payload': {list(err.keys())}"
    assert "data" not in err, f"error event still has 'data': {list(err.keys())}"

    ctx = err["context"]
    assert "question_id" in ctx, f"error event missing question_id in context: {ctx}"
    assert "index" in ctx, f"error event missing index in context: {ctx}"

    # Failing worker is index 1 (question ending _002)
    manifest_questions = events[0]["payload"]["questions"]
    index_1_qid = manifest_questions[1]["question_id"]
    assert index_1_qid.endswith("_002"), f"unexpected manifest question_id: {index_1_qid}"
    assert ctx["question_id"] == index_1_qid, (
        f"error context question_id {ctx['question_id']!r} != {index_1_qid!r}"
    )
    assert ctx["index"] == 1, f"error context index must be 1; got {ctx['index']}"

    p = err["payload"]
    assert p.get("code") == "generation_failed", f"error code must be 'generation_failed'; got {p.get('code')!r}"  # noqa: E501
    assert "message" in p, f"error payload must have 'message': {p}"
    # issue #946: failure_class taxonomy code must be present
    assert "failure_class" in p, f"failure_class missing from generation_failed payload: {p!r}"
    from src.llm_client import _TAXONOMY_CODES
    assert p["failure_class"] in _TAXONOMY_CODES, (
        f"unexpected failure_class value {p['failure_class']!r}"
    )
    assert p["provider"] == "gemini"
    assert p["model"] == "gemini-3.1-pro-preview"
    assert p["tier"] == "execute"
    assert p["http_status"] == 429
    assert p["retry_after_seconds"] == 12
    assert "boom" not in p

    # Stream still ends (break on error behavior unchanged)
    assert events[-1]["event"] in ("done", "error"), (
        f"stream must end with done or error; last event: {events[-1]['event']}"
    )

