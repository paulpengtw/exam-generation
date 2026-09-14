"""Unit tests for server.generate.marshalling — no threads, no database.

Covers:
  - SSEEventName vocabulary completeness (all 14 event names present)
  - question_to_event: PNG embedding, missing-file skip, subquestion embedding
  - extract_image_files / strip_image_base64
  - make_queue_observer: mapped events enqueued, unknown events dropped
  - make_combined_observer: both halves called; individual failures swallowed
  - make_pipeline_emitter: direct and threadsafe paths
  - make_question_update_emitter: payload shape
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from server.config import ServerConfig
from server.generate.marshalling import (
    EMITTED_EVENT_NAMES,
    SSEEventName,
    extract_image_files,
    make_combined_observer,
    make_pipeline_emitter,
    make_question_update_emitter,
    make_queue_observer,
    question_to_event,
    strip_image_base64,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers / canonical event-name sets
# ─────────────────────────────────────────────────────────────────────────────

# Event names the server actually emits at runtime — imported from the source
# of truth in marshalling.py (issue #162). This replaces the previously local
# constant so tests and the TS generator both draw from the same definition.
_EMITTED_EVENTS: frozenset[str] = EMITTED_EVENT_NAMES

# Declared in SSEEventName for wire-contract completeness (issue #162 TypeScript
# generation must see the full vocabulary) but never emitted by server code.
# "progress" is handled by the frontend (web/src/hooks/useGenerate.ts:386) even
# though the server currently produces no such event.
_DECLARED_ONLY: frozenset[str] = frozenset({"progress"})

# Full canonical vocabulary = emitted ∪ declared-only (must match SSEEventName exactly).
_ALL_DECLARED: frozenset[str] = _EMITTED_EVENTS | _DECLARED_ONLY


class _FlatQuestion(BaseModel):
    """Minimal model satisfying question_to_event (no subquestions)."""

    id: str
    圖片: str | None = None

    def model_dump_json(self, **kwargs: Any) -> str:
        import json
        return json.dumps(self.model_dump(**kwargs))


class _QuestionWithSubs(BaseModel):
    """Minimal model with subquestions for subquestion-PNG tests."""

    id: str
    圖片: str | None = None
    subquestions: list[Any] = []

    def model_dump_json(self, **kwargs: Any) -> str:
        import json
        return json.dumps(self.model_dump(**kwargs))


class _Sub(BaseModel):
    圖片: str | None = None
    text: str = "sub"


def _make_config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))


# ─────────────────────────────────────────────────────────────────────────────
# SSEEventName vocabulary
# ─────────────────────────────────────────────────────────────────────────────

def test_sse_event_name_declared_vocabulary_matches_canonical_sets() -> None:
    """SSEEventName must be exactly _EMITTED_EVENTS ∪ _DECLARED_ONLY."""
    actual = {e.value for e in SSEEventName}
    assert actual == _ALL_DECLARED, (
        f"SSEEventName mismatch.\n"
        f"Expected: {sorted(_ALL_DECLARED)}\n"
        f"Got:      {sorted(actual)}"
    )


def test_sse_event_name_has_exactly_fifteen_members() -> None:
    assert len(SSEEventName) == 15


def test_sse_event_name_values_are_strings() -> None:
    """str-mixin: every member must compare equal to its string value."""
    for member in SSEEventName:
        assert member == member.value, f"{member!r} != {member.value!r}"
        assert isinstance(member, str)


def test_progress_is_declared_but_never_emitted() -> None:
    """PROGRESS must stay in SSEEventName (TypeScript contract for #162) but must
    NOT appear in the server's emitted-event set.

    The frontend branches on it in web/src/hooks/useGenerate.ts:386.
    If the server starts emitting it, move "progress" from _DECLARED_ONLY to
    _EMITTED_EVENTS in this file.
    """
    assert "progress" in {e.value for e in SSEEventName}, (
        "SSEEventName.PROGRESS was removed — it must stay for wire-contract completeness"
    )
    assert "progress" not in _EMITTED_EVENTS, (
        '"progress" appeared in _EMITTED_EVENTS — remove it from _DECLARED_ONLY too '
        "and update the frontend reference comment"
    )
    assert "progress" in _DECLARED_ONLY


def test_emitted_events_are_all_declared() -> None:
    """Every server-emitted event name must be a member of SSEEventName."""
    all_values = {e.value for e in SSEEventName}
    undeclared = _EMITTED_EVENTS - all_values
    assert not undeclared, (
        f"Emitted event names missing from SSEEventName: {sorted(undeclared)}"
    )


def test_plan_is_an_emitted_event() -> None:
    assert "plan" in EMITTED_EVENT_NAMES


# ─────────────────────────────────────────────────────────────────────────────
# question_to_event
# ─────────────────────────────────────────────────────────────────────────────

def test_question_to_event_no_image(tmp_path: Path) -> None:
    q = _FlatQuestion(id="q1")
    result = question_to_event(q, _make_config(tmp_path))
    assert result["id"] == "q1"
    assert "image_base64" not in result


def test_question_to_event_embeds_existing_png(tmp_path: Path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\nfake"
    (tmp_path / "q1.png").write_bytes(png_bytes)
    q = _FlatQuestion(id="q1", 圖片="q1.png")
    result = question_to_event(q, _make_config(tmp_path))
    assert "image_base64" in result
    assert base64.b64decode(result["image_base64"]) == png_bytes


def test_question_to_event_skips_missing_png(tmp_path: Path) -> None:
    q = _FlatQuestion(id="q1", 圖片="missing.png")
    result = question_to_event(q, _make_config(tmp_path))
    assert "image_base64" not in result


def test_question_to_event_embeds_subquestion_png(tmp_path: Path) -> None:
    sq_bytes = b"SUBPNG"
    (tmp_path / "q1_sq1.png").write_bytes(sq_bytes)
    sub = _Sub(圖片="q1_sq1.png")
    q = _QuestionWithSubs(id="q1", subquestions=[sub])
    result = question_to_event(q, _make_config(tmp_path))
    assert result["subquestions"][0]["image_base64"] == base64.b64encode(sq_bytes).decode("ascii")


def test_question_to_event_skips_subquestion_with_no_image(tmp_path: Path) -> None:
    sub = _Sub()
    q = _QuestionWithSubs(id="q1", subquestions=[sub])
    result = question_to_event(q, _make_config(tmp_path))
    assert "image_base64" not in result["subquestions"][0]


# ─────────────────────────────────────────────────────────────────────────────
# extract_image_files
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_image_files_empty_payload() -> None:
    assert extract_image_files({}) == []


def test_extract_image_files_top_level_only() -> None:
    assert extract_image_files({"圖片": "q1.png"}) == ["q1.png"]


def test_extract_image_files_subquestions_only() -> None:
    payload = {"subquestions": [{"圖片": "sq1.png"}, {"other": "x"}, {"圖片": "sq3.png"}]}
    assert extract_image_files(payload) == ["sq1.png", "sq3.png"]


def test_extract_image_files_both_levels() -> None:
    payload = {"圖片": "top.png", "subquestions": [{"圖片": "sq1.png"}]}
    assert extract_image_files(payload) == ["top.png", "sq1.png"]


def test_extract_image_files_ignores_none_subquestion_entries() -> None:
    payload = {"subquestions": [None, {"圖片": "sq2.png"}]}
    assert extract_image_files(payload) == ["sq2.png"]


# ─────────────────────────────────────────────────────────────────────────────
# strip_image_base64
# ─────────────────────────────────────────────────────────────────────────────

def test_strip_image_base64_removes_top_level_field() -> None:
    payload = {"id": "q1", "image_base64": "abc==", "text": "hi"}
    result = strip_image_base64(payload)
    assert "image_base64" not in result
    assert result["id"] == "q1"
    assert result["text"] == "hi"


def test_strip_image_base64_removes_from_subquestions() -> None:
    payload = {"subquestions": [{"image_base64": "abc==", "id": "s1"}, {"id": "s2"}]}
    result = strip_image_base64(payload)
    assert all("image_base64" not in sub for sub in result["subquestions"])
    assert result["subquestions"][0]["id"] == "s1"


def test_strip_image_base64_returns_copy_not_mutating_original() -> None:
    payload = {"image_base64": "abc==", "x": 1}
    result = strip_image_base64(payload)
    assert "image_base64" in payload  # original untouched
    assert "image_base64" not in result


# ─────────────────────────────────────────────────────────────────────────────
# make_queue_observer
# ─────────────────────────────────────────────────────────────────────────────

def test_make_queue_observer_enqueues_mapped_events() -> None:
    loop = asyncio.new_event_loop()
    try:
        queue: asyncio.Queue = asyncio.Queue()
        observer = make_queue_observer(loop, queue)

        observer({"type": "llm_request"})

        async def drain() -> dict:
            return await asyncio.wait_for(queue.get(), timeout=1.0)

        item = loop.run_until_complete(drain())
        assert item["event"] == SSEEventName.LLM_REQUEST
        assert item["data"]["type"] == "llm_request"
    finally:
        loop.close()


def test_make_queue_observer_maps_all_observer_types() -> None:
    loop = asyncio.new_event_loop()
    try:
        queue: asyncio.Queue = asyncio.Queue()
        observer = make_queue_observer(loop, queue)

        pairs = [
            ("llm_request", SSEEventName.LLM_REQUEST),
            ("llm_reasoning_delta", SSEEventName.LLM_THINKING),
            ("llm_content_delta", SSEEventName.LLM_CONTENT),
            ("llm_response", SSEEventName.LLM_RESPONSE),
            ("stage", SSEEventName.STAGE),
            ("plan", SSEEventName.PLAN),
        ]
        for input_type, expected_event in pairs:
            observer({"type": input_type})

        async def drain_all() -> list:
            items = []
            for _ in pairs:
                items.append(await asyncio.wait_for(queue.get(), timeout=1.0))
            return items

        items = loop.run_until_complete(drain_all())
        assert [it["event"] for it in items] == [e for _, e in pairs]
    finally:
        loop.close()


def test_make_queue_observer_ignores_unknown_event_types() -> None:
    loop = asyncio.new_event_loop()
    try:
        queue: asyncio.Queue = asyncio.Queue()
        observer = make_queue_observer(loop, queue)
        observer({"type": "unknown_type"})
        observer({"type": ""})
        # Queue must remain empty.
        assert queue.empty()
    finally:
        loop.close()


# ─────────────────────────────────────────────────────────────────────────────
# make_combined_observer
# ─────────────────────────────────────────────────────────────────────────────

def test_make_combined_observer_calls_both_halves() -> None:
    seen_q: list[dict] = []
    seen_r: list[dict] = []

    def queue_obs(event: dict) -> None:
        seen_q.append(event)

    def recorder(event: dict) -> None:
        seen_r.append(event)

    obs = make_combined_observer(queue_obs, recorder)
    evt = {"type": "llm_request"}
    obs(evt)
    assert seen_q == [evt]
    assert seen_r == [evt]


def test_make_combined_observer_swallows_queue_obs_error() -> None:
    seen: list[dict] = []

    def boom(event: dict) -> None:
        raise RuntimeError("queue_obs crashed")

    def recorder(event: dict) -> None:
        seen.append(event)

    obs = make_combined_observer(boom, recorder)
    obs({"type": "llm_request"})  # must not raise
    # recorder still called after the error in queue_obs
    assert len(seen) == 1


def test_make_combined_observer_swallows_recorder_error() -> None:
    seen: list[dict] = []

    def queue_obs(event: dict) -> None:
        seen.append(event)

    def boom(event: dict) -> None:
        raise RuntimeError("recorder crashed")

    obs = make_combined_observer(queue_obs, boom)
    obs({"type": "llm_request"})  # must not raise
    assert len(seen) == 1


def test_make_combined_observer_none_recorder_is_safe() -> None:
    seen: list[dict] = []

    def queue_obs(event: dict) -> None:
        seen.append(event)

    obs = make_combined_observer(queue_obs, None)
    obs({"type": "stage"})
    assert len(seen) == 1


# ─────────────────────────────────────────────────────────────────────────────
# make_pipeline_emitter
# ─────────────────────────────────────────────────────────────────────────────

def test_make_pipeline_emitter_direct_path(tmp_path: Path) -> None:
    loop = asyncio.new_event_loop()
    try:
        queue: asyncio.Queue = asyncio.Queue()
        _emit_pipeline = make_pipeline_emitter(loop, queue)

        async def run() -> None:
            _emit_pipeline("pipeline_start", _direct=True, total=3)
            item = queue.get_nowait()
            assert item["event"] == SSEEventName.PIPELINE
            assert item["data"]["event_name"] == "pipeline_start"
            assert item["data"]["total"] == 3
            assert "ts" in item["data"]

        loop.run_until_complete(run())
    finally:
        loop.close()


def test_make_pipeline_emitter_threadsafe_path() -> None:
    loop = asyncio.new_event_loop()
    try:
        queue: asyncio.Queue = asyncio.Queue()
        _emit_pipeline = make_pipeline_emitter(loop, queue)

        # Calling without _direct=True uses call_soon_threadsafe.
        _emit_pipeline("question_end", index=0, total=1)

        async def drain() -> dict:
            return await asyncio.wait_for(queue.get(), timeout=1.0)

        item = loop.run_until_complete(drain())
        assert item["event"] == SSEEventName.PIPELINE
        assert item["data"]["event_name"] == "question_end"
        assert item["data"]["index"] == 0
    finally:
        loop.close()


def test_make_pipeline_emitter_ts_is_a_float() -> None:
    loop = asyncio.new_event_loop()
    try:
        queue: asyncio.Queue = asyncio.Queue()
        _emit_pipeline = make_pipeline_emitter(loop, queue)

        async def run() -> None:
            _emit_pipeline("done", _direct=True)
            item = queue.get_nowait()
            assert isinstance(item["data"]["ts"], float)

        loop.run_until_complete(run())
    finally:
        loop.close()


# ─────────────────────────────────────────────────────────────────────────────
# make_question_update_emitter
# ─────────────────────────────────────────────────────────────────────────────

def test_make_question_update_emitter_payload_shape(tmp_path: Path) -> None:
    loop = asyncio.new_event_loop()
    try:
        queue: asyncio.Queue = asyncio.Queue()
        config = _make_config(tmp_path)
        q = _FlatQuestion(id="q42")
        emitter = make_question_update_emitter(3, loop, queue, config)

        async def run() -> None:
            emitter(q, "draft")
            item = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert item["event"] == SSEEventName.QUESTION_UPDATE
            assert item["data"]["index"] == 3
            assert item["data"]["phase"] == "draft"
            assert item["data"]["question"]["id"] == "q42"

        loop.run_until_complete(run())
    finally:
        loop.close()
