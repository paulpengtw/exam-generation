"""Issue #855 — started event contract validation before emission.

Tests:
- StartedPayload direct unit tests: valid and invalid manifests via pytest.raises(ValidationError)
- StartedPayload.generation_log_id declared as optional (str, None, absent)
- Service rejects invalid started payload via real allocate_manifest injection:
  no started emitted, zero workers/model calls, error payload has no question content,
  no events emitted after the error
- Valid list: started at event_seq=1, before planner events
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from pydantic import ValidationError

from server.config import ServerConfig
from server.generate.event_protocol import StartedPayload
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from src.common.generation_events import QuestionContext
from tests.server.generate_test_utils import resolved_generate_params

# ---------------------------------------------------------------------------
# StartedPayload.generation_log_id contract
# ---------------------------------------------------------------------------


def test_started_payload_accepts_string_generation_log_id() -> None:
    p = StartedPayload.model_validate({
        "protocol_version": 2,
        "total": 1,
        "questions": [{"index": 0, "question_id": "q_001"}],
        "generation_log_id": "abc123",
    })
    assert p.generation_log_id == "abc123"


def test_started_payload_accepts_null_generation_log_id() -> None:
    p = StartedPayload.model_validate({
        "protocol_version": 2,
        "total": 1,
        "questions": [{"index": 0, "question_id": "q_001"}],
        "generation_log_id": None,
    })
    assert p.generation_log_id is None


def test_started_payload_generation_log_id_defaults_to_none() -> None:
    p = StartedPayload.model_validate({
        "protocol_version": 2,
        "total": 1,
        "questions": [{"index": 0, "question_id": "q_001"}],
    })
    assert p.generation_log_id is None


# ---------------------------------------------------------------------------
# StartedPayload direct unit tests: invalid manifests raise ValidationError
# ---------------------------------------------------------------------------


def test_started_payload_rejects_length_mismatch() -> None:
    """total=1 but questions has 2 entries — length mismatch."""
    with pytest.raises(ValidationError):
        StartedPayload.model_validate({
            "protocol_version": 2,
            "total": 1,
            "questions": [
                {"index": 0, "question_id": "q_001"},
                {"index": 1, "question_id": "q_002"},
            ],
        })


def test_started_payload_rejects_noncontiguous_index() -> None:
    """Questions with indices 0, 2 — gap at position 1."""
    with pytest.raises(ValidationError):
        StartedPayload.model_validate({
            "protocol_version": 2,
            "total": 2,
            "questions": [
                {"index": 0, "question_id": "q_001"},
                {"index": 2, "question_id": "q_003"},
            ],
        })


def test_started_payload_rejects_duplicate_question_id() -> None:
    """Two questions with the same question_id."""
    with pytest.raises(ValidationError):
        StartedPayload.model_validate({
            "protocol_version": 2,
            "total": 2,
            "questions": [
                {"index": 0, "question_id": "q_dup"},
                {"index": 1, "question_id": "q_dup"},
            ],
        })


# ---------------------------------------------------------------------------
# Service seam: started validation gate — real invalid manifest injection
# ---------------------------------------------------------------------------


def _make_params(count: int = 1) -> Any:
    return resolved_generate_params({
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
        "count": count,
        "skip_verify": True,
    })


def _make_counting_spec(call_counter: list) -> Any:
    """Return a math-like spec whose do_generate appends to call_counter."""
    original = SUBJECTS["math"]
    call_counter.clear()

    def _fake_do_generate(**kwargs: Any) -> Any:
        call_counter.append(1)
        q = MagicMock()
        q.__class__ = original.exam_question_cls
        qid = kwargs.get("question_id", "q_unknown")
        q.model_dump_json.return_value = json.dumps({"id": qid})
        q.圖片 = None
        q.subquestions = []
        q.chart_spec = None
        q.verification = None
        return q

    return dataclasses.replace(original, do_generate=_fake_do_generate)


# Bad manifest factories: each receives (prefix, run_id, count) and returns
# a tuple of QuestionContext objects that will cause StartedPayload validation
# to fail.


def _bad_length_mismatch(prefix: str, run_id: str, count: int) -> tuple[QuestionContext, ...]:
    """Return 2 items regardless of count (intended for count=1)."""
    return (
        QuestionContext(run_id=run_id, question_id=f"{prefix}{run_id}_001", index=0),
        QuestionContext(run_id=run_id, question_id=f"{prefix}{run_id}_002", index=1),
    )


def _bad_noncontiguous_index(prefix: str, run_id: str, count: int) -> tuple[QuestionContext, ...]:
    """Return items with indices 0, 2 — gap at position 1 (intended for count=2)."""
    return (
        QuestionContext(run_id=run_id, question_id=f"{prefix}{run_id}_001", index=0),
        QuestionContext(run_id=run_id, question_id=f"{prefix}{run_id}_003", index=2),
    )


def _bad_duplicate_question_id(prefix: str, run_id: str, count: int) -> tuple[QuestionContext, ...]:
    """Return two items with the same question_id (intended for count=2)."""
    return (
        QuestionContext(run_id=run_id, question_id=f"{prefix}{run_id}_dup", index=0),
        QuestionContext(run_id=run_id, question_id=f"{prefix}{run_id}_dup", index=1),
    )


# (bad_manifest_factory, params_count) pairs
_BAD_MANIFEST_CASES = [
    pytest.param(_bad_length_mismatch, 1, id="length_mismatch"),
    pytest.param(_bad_noncontiguous_index, 2, id="noncontiguous_index"),
    pytest.param(_bad_duplicate_question_id, 2, id="duplicate_question_id"),
]


def _run_with_bad_manifest(
    bad_factory: Any,
    params: Any,
    fake_spec: Any,
    tmp_path: Path,
) -> list[dict]:
    """Run stream while patching allocate_manifest to return a bad manifest."""
    config = ServerConfig(api_key="x", output_dir=tmp_path)
    app_state = MagicMock()
    app_state.renderer_pool = None
    events: list[dict] = []

    with patch(
        "server.generate.service.allocate_manifest",
        side_effect=bad_factory,
    ):
        async def _run() -> None:
            async for ev in generate_question_stream(
                params, config, app_state,
                subjects={"math": fake_spec},
            ):
                events.append(ev)

        asyncio.run(_run())
    return events


@pytest.mark.parametrize("bad_factory,count", _BAD_MANIFEST_CASES)
def test_invalid_started_emits_error_not_started(
    bad_factory: Any, count: int, tmp_path: Path
) -> None:
    """Invalid started payload: error event emitted, no started event."""
    call_counter: list = []
    fake_spec = _make_counting_spec(call_counter)
    events = _run_with_bad_manifest(bad_factory, _make_params(count), fake_spec, tmp_path)

    names = [e.get("event") for e in events]
    assert "started" not in names, f"started must not appear: {names}"
    assert "error" in names, f"error event expected: {names}"


@pytest.mark.parametrize("bad_factory,count", _BAD_MANIFEST_CASES)
def test_invalid_started_zero_model_calls(
    bad_factory: Any, count: int, tmp_path: Path
) -> None:
    """Invalid started payload: no workers started, zero LLM calls."""
    call_counter: list = []
    fake_spec = _make_counting_spec(call_counter)
    _run_with_bad_manifest(bad_factory, _make_params(count), fake_spec, tmp_path)

    assert len(call_counter) == 0, f"expected 0 LLM calls, got {len(call_counter)}"


@pytest.mark.parametrize("bad_factory,count", _BAD_MANIFEST_CASES)
def test_invalid_started_error_payload_has_no_question_content(
    bad_factory: Any, count: int, tmp_path: Path
) -> None:
    """Error event must carry only code+message, no question/prompt content."""
    call_counter: list = []
    fake_spec = _make_counting_spec(call_counter)
    events = _run_with_bad_manifest(bad_factory, _make_params(count), fake_spec, tmp_path)

    error_events = [e for e in events if e.get("event") == "error"]
    assert error_events, "at least one error event expected"
    for ev in error_events:
        payload = ev.get("payload", ev.get("data", {}))
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict):
            # issue #946: failure_class and other structured error fields are allowed;
            # the invariant is that no question/prompt content leaks, not that only
            # code+message are present.
            allowed_keys = {
                "code", "message", "failure_class",
                "provider", "model", "tier", "http_status", "retry_after_seconds",
            }
            extra = set(payload.keys()) - allowed_keys
            assert not extra, f"error payload has unexpected keys: {extra}"
            msg = str(payload.get("message", ""))
            assert "題目" not in msg, "error message must not contain question content"
            assert "prompt" not in msg.lower(), "error message must not mention prompt"


@pytest.mark.parametrize("bad_factory,count", _BAD_MANIFEST_CASES)
def test_no_events_after_error_on_invalid_started(
    bad_factory: Any, count: int, tmp_path: Path
) -> None:
    """After emitting the error event the stream must not emit any further events."""
    call_counter: list = []
    fake_spec = _make_counting_spec(call_counter)
    events = _run_with_bad_manifest(bad_factory, _make_params(count), fake_spec, tmp_path)

    names = [e.get("event") for e in events]
    assert "error" in names, f"error event expected: {names}"
    error_idx = next(i for i, n in enumerate(names) if n == "error")
    events_after_error = names[error_idx + 1:]
    assert not events_after_error, f"unexpected events after error: {events_after_error}"


# ---------------------------------------------------------------------------
# Service seam: valid started path
# ---------------------------------------------------------------------------


def test_valid_started_is_event_seq_1_before_planner(tmp_path: Path) -> None:
    """Valid list: started event has event_seq=1 and precedes planner stage events."""
    original = SUBJECTS["math"]

    def _fake_do_generate(**kwargs: Any) -> Any:
        q = MagicMock()
        q.__class__ = original.exam_question_cls
        q.model_dump_json.return_value = json.dumps({"id": kwargs.get("question_id", "q")})
        q.圖片 = None
        q.subquestions = []
        q.chart_spec = None
        q.verification = None
        return q

    fake_spec = dataclasses.replace(original, do_generate=_fake_do_generate)
    params = _make_params(count=1)
    config = ServerConfig(api_key="x", output_dir=tmp_path)
    app_state = MagicMock()
    app_state.renderer_pool = None
    events: list[dict] = []

    async def _run() -> None:
        async for ev in generate_question_stream(
            params, config, app_state,
            subjects={"math": fake_spec},
        ):
            events.append(ev)

    asyncio.run(_run())

    assert events, "stream must produce at least one event"
    first = events[0]
    assert first.get("event") == "started", (
        f"first event must be 'started', got {first.get('event')}"
    )
    assert first.get("context", {}).get("event_seq") == 1, (
        f"started must have event_seq=1, got {first.get('context', {}).get('event_seq')}"
    )

    started_idx = next(i for i, e in enumerate(events) if e.get("event") == "started")
    planner_idxs = [
        i for i, e in enumerate(events)
        if e.get("event") == "stage"
        and isinstance(e.get("payload"), dict)
        and e["payload"].get("agent") == "planner"
    ]
    if planner_idxs:
        assert started_idx < min(planner_idxs), "started must precede planner stage events"
