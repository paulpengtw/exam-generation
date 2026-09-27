"""Issue #855 — started event contract validation before emission.

Tests:
- StartedPayload.generation_log_id declared as optional (str, None, absent)
- Service rejects invalid started payload: no started emitted, zero workers/model calls,
  error payload contains no question or prompt content
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

from server.config import ServerConfig
from server.generate.event_protocol import StartedPayload
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
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
# Service seam: started validation gate
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


def _run_with_invalid_started(params: Any, fake_spec: Any, tmp_path: Path) -> list[dict]:
    """Run stream while forcing StartedPayload.model_validate to raise ValueError."""
    config = ServerConfig(api_key="x", output_dir=tmp_path)
    app_state = MagicMock()
    app_state.renderer_pool = None
    events: list[dict] = []

    with patch(
        "server.generate.service.StartedPayload.model_validate",
        side_effect=ValueError("injected: manifest validation error"),
    ):
        async def _run() -> None:
            async for ev in generate_question_stream(
                params, config, app_state,
                subjects={"math": fake_spec},
            ):
                events.append(ev)

        asyncio.run(_run())
    return events


def test_invalid_started_emits_error_not_started(tmp_path: Path) -> None:
    """Invalid started payload: error event emitted, no started event."""
    call_counter: list = []
    fake_spec = _make_counting_spec(call_counter)
    events = _run_with_invalid_started(_make_params(1), fake_spec, tmp_path)

    names = [e.get("event") for e in events]
    assert "started" not in names, f"started must not appear: {names}"
    assert "error" in names, f"error event expected: {names}"


def test_invalid_started_zero_model_calls(tmp_path: Path) -> None:
    """Invalid started payload: no workers started, zero LLM calls."""
    call_counter: list = []
    fake_spec = _make_counting_spec(call_counter)
    _run_with_invalid_started(_make_params(2), fake_spec, tmp_path)

    assert len(call_counter) == 0, f"expected 0 LLM calls, got {len(call_counter)}"


def test_invalid_started_error_payload_has_no_question_content(tmp_path: Path) -> None:
    """Error event must carry only code+message, no question/prompt content."""
    call_counter: list = []
    fake_spec = _make_counting_spec(call_counter)
    events = _run_with_invalid_started(_make_params(1), fake_spec, tmp_path)

    error_events = [e for e in events if e.get("event") == "error"]
    assert error_events, "at least one error event expected"
    for ev in error_events:
        payload = ev.get("payload", ev.get("data", {}))
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict):
            allowed_keys = {"code", "message"}
            extra = set(payload.keys()) - allowed_keys
            assert not extra, f"error payload has unexpected keys: {extra}"
            msg = str(payload.get("message", ""))
            assert "題目" not in msg, "error message must not contain question content"
            assert "prompt" not in msg.lower(), "error message must not mention prompt"


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
