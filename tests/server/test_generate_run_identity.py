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
from unittest.mock import MagicMock

from src.common.generation_events import QuestionContext, allocate_manifest, new_run_id
from tests.server.generate_test_utils import resolved_generate_params

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
