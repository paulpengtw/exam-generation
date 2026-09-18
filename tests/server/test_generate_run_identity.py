"""Slice 3 – run identity and manifest tests.

Tests ensure that:
1. _build_run_context computes a manifest via allocate_manifest.
2. _RunContext exposes run_id and manifest fields.
3. Workers use ctx.manifest[i].question_id instead of the old timestamp formula.
4. All question_ids in a batch share the same run_id.
5. question_ids are stable (same between two calls, if same run_id/prefix/count).
"""
from __future__ import annotations

import asyncio
import dataclasses
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from server.generate.subjects import SUBJECTS
from src.common.generation_events import QuestionContext, allocate_manifest, new_run_id
from src.social_studies.schemas import (
    ExamQuestion,
    QuestionMetadata,
    QuestionType,
)
from tests.server.generate_test_utils import resolved_generate_params
from tests.server.generate_test_utils import resolved_generate_params as _rgp

# ---------------------------------------------------------------------------
# allocate_manifest correctness
# ---------------------------------------------------------------------------


def test_manifest_length() -> None:
    rid = new_run_id()
    manifest = allocate_manifest("q_", rid, 3)
    assert len(manifest) == 3


def test_manifest_question_id_format() -> None:
    rid = "abc123"
    manifest = allocate_manifest("q_", rid, 2)
    assert manifest[0].question_id == "q_abc123_001"
    assert manifest[1].question_id == "q_abc123_002"


def test_manifest_all_share_run_id() -> None:
    rid = new_run_id()
    manifest = allocate_manifest("q_", rid, 4)
    assert all(q.run_id == rid for q in manifest)


def test_manifest_indices_are_zero_based() -> None:
    rid = new_run_id()
    manifest = allocate_manifest("q_", rid, 3)
    assert [q.index for q in manifest] == [0, 1, 2]


def test_manifest_is_tuple() -> None:
    manifest = allocate_manifest("q_", new_run_id(), 2)
    assert isinstance(manifest, tuple)


def test_manifest_elements_are_question_context() -> None:
    manifest = allocate_manifest("q_", new_run_id(), 2)
    assert all(isinstance(q, QuestionContext) for q in manifest)


# ---------------------------------------------------------------------------
# _RunContext has run_id and manifest fields (structural tests via dataclass)
# ---------------------------------------------------------------------------


def test_run_context_has_run_id_field() -> None:
    """_RunContext must expose a run_id string field."""
    from server.generate.service import _RunContext

    fields = {f.name for f in dataclasses.fields(_RunContext)}
    assert "run_id" in fields


def test_run_context_has_manifest_field() -> None:
    """_RunContext must expose a manifest field (tuple of QuestionContext)."""
    from server.generate.service import _RunContext

    fields = {f.name for f in dataclasses.fields(_RunContext)}
    assert "manifest" in fields


# ---------------------------------------------------------------------------
# _build_run_context correctly fills run_id and manifest
# ---------------------------------------------------------------------------


def test_build_run_context_populates_manifest() -> None:
    """_build_run_context should produce a manifest with count=1 for a math request."""
    from server.config import ServerConfig
    from server.generate.service import _build_run_context
    from server.generate.subjects import SUBJECTS

    params = resolved_generate_params(
        {
            "subject": "math",
            "seed": 41,
            "grade": 8,
            "context": ["個人"],
            "set_type": "單一題",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "math_thinking": ["形成"],
            "learning_content": ["A-7-7"],
            "learning_performance": ["s-IV-12"],
            "core_competency": ["數-J-A2"],
            "content_type": "純文字",
            "count": 1,
        }
    )
    spec = SUBJECTS["math"]
    loop = asyncio.new_event_loop()
    try:
        queue: asyncio.Queue = asyncio.Queue()
        config = ServerConfig(api_key="x", gemini_api_key="x")
        app_state = MagicMock()
        ctx = _build_run_context(
            params,
            config,
            app_state=app_state,
            spec=spec,
            session_factory=None,
            generation_log_id=None,
            loop=loop,
            queue=queue,
            html_renderer=None,
        )
    finally:
        loop.close()

    assert ctx.run_id, "run_id must be a non-empty string"
    assert re.match(r"^[0-9a-f]{32}$", ctx.run_id), "run_id should be 32 hex chars"
    assert len(ctx.manifest) == 1
    assert ctx.manifest[0].run_id == ctx.run_id
    # question_id should use manifest format: q_<run_id>_001
    assert ctx.manifest[0].question_id == f"q_{ctx.run_id}_001"


# ---------------------------------------------------------------------------
# Slice 3 additions: v2 started event and run_id identity
# ---------------------------------------------------------------------------


def _fake_do_generate_s3(rng_params, overrides, **kwargs):
    return ExamQuestion(
        id=kwargs["question_id"],
        情境=[c for c in rng_params.情境],
        題型種類=rng_params.題型種類,
        題型=rng_params.題型[0] if rng_params.題型 else QuestionType("選擇題"),
        題目內容類型=rng_params.題目內容類型,
        取材來源=list(rng_params.學習內容_pool),
        metadata=QuestionMetadata(grade=rng_params.grade, model="test-model"),
    )


_fake_ss_s3 = dataclasses.replace(SUBJECTS["social_studies"], do_generate=_fake_do_generate_s3)


def _ss_params(**kw):
    return _rgp({"subject": "social_studies", "skip_verify": True, "count": 1, **kw})


def _run_stream_s3(params, tmp_path, generation_log_id=None):
    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    events = []
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    app_state = SimpleNamespace(renderer_pool=None)

    async def collect():
        async for ev in generate_question_stream(
            params, config, app_state,
            subjects={"social_studies": _fake_ss_s3},
            generation_log_id=generation_log_id,
        ):
            events.append(ev)

    asyncio.run(collect())
    return events


def test_started_is_first_event(tmp_path) -> None:
    """started must be the very first yielded event."""
    params = _ss_params()
    events = _run_stream_s3(params, tmp_path)
    assert events, "stream produced no events"
    assert events[0].get("event") == "started", (
        f"first event was {events[0].get('event')!r}, expected 'started'"
    )


def test_started_has_context_with_run_id_and_event_seq_1(tmp_path) -> None:
    """started context must have run_id and event_seq=1, no question_id/index/'event'."""
    params = _ss_params()
    events = _run_stream_s3(params, tmp_path)
    started = events[0]
    assert started.get("event") == "started"
    ctx = started.get("context", {})
    assert "run_id" in ctx, f"context missing run_id: {ctx}"
    assert ctx.get("event_seq") == 1, f"expected event_seq=1, got {ctx.get('event_seq')}"
    assert "question_id" not in ctx, f"started context must not have question_id: {ctx}"
    assert "index" not in ctx, f"started context must not have index: {ctx}"
    assert "event" not in ctx, f"context must not contain 'event' key: {ctx}"


def test_started_payload_has_protocol_version_2(tmp_path) -> None:
    """started payload must have protocol_version == 2."""
    params = _ss_params()
    events = _run_stream_s3(params, tmp_path)
    started = events[0]
    payload = started.get("payload", {})
    assert payload.get("protocol_version") == 2, f"payload: {payload}"


def test_started_payload_total_equals_count(tmp_path) -> None:
    """started payload.total must equal request count."""
    params = _ss_params()
    events = _run_stream_s3(params, tmp_path)
    started = events[0]
    payload = started.get("payload", {})
    assert payload.get("total") == 1, f"payload: {payload}"


def test_started_payload_questions_list(tmp_path) -> None:
    """started payload.questions must be [{index, question_id}] with correct format."""
    params = _ss_params()
    events = _run_stream_s3(params, tmp_path)
    started = events[0]
    payload = started.get("payload", {})
    ctx = started.get("context", {})
    run_id = ctx.get("run_id", "")
    questions = payload.get("questions", [])
    assert len(questions) == 1
    q = questions[0]
    assert q.get("index") == 0
    assert run_id in q.get("question_id", ""), (
        f"question_id {q.get('question_id')!r} must contain run_id {run_id!r}"
    )
    assert q.get("question_id", "").endswith("_001"), (
        f"question_id must end with _001: {q.get('question_id')!r}"
    )


def test_run_id_uses_generation_log_id_when_provided(tmp_path) -> None:
    """When generation_log_id is given, run_id must equal str(generation_log_id)."""
    log_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    params = _ss_params()
    events = _run_stream_s3(params, tmp_path, generation_log_id=log_id)
    started = events[0]
    ctx = started.get("context", {})
    assert ctx.get("run_id") == str(log_id), (
        f"run_id={ctx.get('run_id')!r}, expected {str(log_id)!r}"
    )


def test_run_id_is_fresh_uuid_when_none(tmp_path) -> None:
    """When generation_log_id is None, run_id must be a fresh UUID hex string."""
    params = _ss_params()
    events = _run_stream_s3(params, tmp_path)
    started = events[0]
    ctx = started.get("context", {})
    run_id = ctx.get("run_id", "")
    assert re.match(r"^[0-9a-f]{32}$", run_id), (
        f"run_id not a 32-hex uuid: {run_id!r}"
    )


def test_two_runs_with_identical_params_have_different_run_ids(tmp_path) -> None:
    """Two runs with the same params must produce distinct run_ids."""
    params = _ss_params()
    events1 = _run_stream_s3(params, tmp_path)
    events2 = _run_stream_s3(params, tmp_path)
    rid1 = events1[0].get("context", {}).get("run_id")
    rid2 = events2[0].get("context", {}).get("run_id")
    assert rid1 != rid2, f"run_ids must differ between runs: {rid1}"


def test_result_payload_id_equals_manifest_question_id(tmp_path) -> None:
    """result payload 'id' must equal the manifest question_id for that worker."""
    params = _ss_params()
    events = _run_stream_s3(params, tmp_path)
    started = events[0]
    ctx = started.get("context", {})
    run_id = ctx.get("run_id")
    # payload may be in "data" (v1) or "payload" (v2)
    results = [e for e in events if e.get("event") == "result"]
    assert results, "no result events found"
    result = results[0]
    result_data = result.get("data", result.get("payload", {}))
    result_id = result_data.get("id", "")
    assert run_id in result_id, (
        f"result id {result_id!r} must contain run_id {run_id!r}"
    )


# ---------------------------------------------------------------------------
# Slice 5 – content_revision wired via QuestionSnapshotLedger
# ---------------------------------------------------------------------------


def _build_math_question(question_id: str, 題目_text: str = "original question") -> Any:
    """Build a minimal math ExamQuestion for service-level ledger tests."""
    from src.schemas import ExamQuestion

    return ExamQuestion(
        id=question_id,
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[{"編碼": "A-7-1", "說明": "test"}],
        題目=[題目_text],
        正確解題分析=["answer"],
        核心素養=["數-J-A2"],
        學習表現=[{"編碼": "s-IV-1", "說明": "test"}],
    )


def _run_stream_math(fake_do_generate, tmp_path) -> list[dict]:
    """Run generate_question_stream for math with a fake do_generate."""
    import asyncio
    import dataclasses
    from pathlib import Path

    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from tests.server.generate_test_utils import resolved_generate_params

    params = resolved_generate_params({
        "subject": "math",
        "seed": 41,
        "grade": 8,
        "context": ["個人"],
        "set_type": "單一題",
        "q_type": ["選擇題"],
        "style": ["text_only"],
        "math_thinking": ["形成"],
        "learning_content": ["A-7-7"],
        "learning_performance": ["s-IV-12"],
        "core_competency": ["數-J-A2"],
        "content_type": "純文字",
        "count": 1,
        "skip_verify": True,
    })
    spec = dataclasses.replace(SUBJECTS["math"], do_generate=fake_do_generate)
    config = ServerConfig(
        api_key="x", gemini_api_key="x", output_dir=tmp_path, data_dir=Path("data")
    )
    app_state = MagicMock()
    app_state.renderer_pool = None
    events = []

    async def collect():
        async for ev in generate_question_stream(
            params, config, app_state,
            subjects={"math": spec},
        ):
            events.append(ev)

    asyncio.run(collect())
    return events


def test_content_revision_same_question_stays_at_1(tmp_path) -> None:
    """question_update revisions [1,1] and result content_revision=1 when content unchanged."""
    import unittest.mock as mock

    def fake_do_generate(rng_params, overrides, **kwargs):
        qid = kwargs["question_id"]
        on_update = kwargs["on_question_update"]
        q = _build_math_question(qid)
        on_update(q, "draft")
        on_update(q, "verified")
        return q

    with mock.patch("server.observability.record_generation_outcome"):
        events = _run_stream_math(fake_do_generate, tmp_path)

    updates = [e for e in events if e.get("event") == "question_update"]
    results = [e for e in events if e.get("event") == "result"]

    # Both question_updates should have content_revision=1 (same content)
    update_revisions = [u["context"].get("content_revision") for u in updates]
    assert update_revisions == [1, 1], f"expected [1,1] got {update_revisions}"

    # Result should also have content_revision=1
    assert results, "no result events"
    result_ctx = results[0].get("context", {})
    assert result_ctx.get("content_revision") == 1, (
        f"result content_revision={result_ctx.get('content_revision')!r}"
    )


def test_content_revision_increments_on_mutation(tmp_path) -> None:
    """question_update revisions [1,2] and result content_revision=2 when 題目 changes."""
    import unittest.mock as mock

    def fake_do_generate(rng_params, overrides, **kwargs):
        qid = kwargs["question_id"]
        on_update = kwargs["on_question_update"]
        q = _build_math_question(qid)
        on_update(q, "draft")
        # Mutate 題目 to simulate a correction pass
        q.題目 = ["corrected question text"]
        on_update(q, "corrected")
        return q

    with mock.patch("server.observability.record_generation_outcome"):
        events = _run_stream_math(fake_do_generate, tmp_path)

    updates = [e for e in events if e.get("event") == "question_update"]
    results = [e for e in events if e.get("event") == "result"]

    update_revisions = [u["context"].get("content_revision") for u in updates]
    assert update_revisions == [1, 2], f"expected [1,2] got {update_revisions}"

    assert results, "no result events"
    result_ctx = results[0].get("context", {})
    assert result_ctx.get("content_revision") == 2, (
        f"result content_revision={result_ctx.get('content_revision')!r}"
    )
