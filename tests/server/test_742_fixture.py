"""Slice 7 – Issue #742 fixture test.

Verifies the complete stream v2 protocol end-to-end:
- HTTP 426 gate (slice 2)
- manifest-format question_ids (slice 3)
- GenerationPublisher wired (slice 4)
- QuestionSnapshotLedger wired (slice 5)
- question_terminal events emitted (slice 6)

This is a fast structural test — it does not call real LLMs.
"""
from __future__ import annotations

import dataclasses

# ---------------------------------------------------------------------------
# All slice-level modules are importable
# ---------------------------------------------------------------------------


def test_event_protocol_importable() -> None:
    from server.generate.event_protocol import (
        PROTOCOL_VERSION,
        SUPPORTED_STREAM_VERSIONS,
    )

    assert PROTOCOL_VERSION == 2
    assert 2 in SUPPORTED_STREAM_VERSIONS


def test_generation_events_importable() -> None:
    from src.common.generation_events import (
        QuestionContext,
        RunContext,
        allocate_manifest,
        new_run_id,
    )

    run_id = new_run_id()
    assert len(run_id) == 32
    rc = RunContext(run_id=run_id)
    assert rc.run_id == run_id
    manifest = allocate_manifest("q_", run_id, 2)
    assert len(manifest) == 2
    assert isinstance(manifest[0], QuestionContext)


def test_publisher_importable() -> None:
    from server.generate.publisher import GenerationPublisher

    assert GenerationPublisher is not None


def test_snapshot_ledger_importable() -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    assert ledger.latest_revision("q_x_001") == 0


def test_question_terminal_in_marshalling() -> None:
    from server.generate.marshalling import EMITTED_EVENT_NAMES, SSEEventName

    assert SSEEventName.QUESTION_TERMINAL == "question_terminal"
    assert "question_terminal" in EMITTED_EVENT_NAMES


# ---------------------------------------------------------------------------
# _RunContext has all slice 3-5 fields
# ---------------------------------------------------------------------------


def test_run_context_has_all_new_fields() -> None:
    from server.generate.service import _RunContext

    field_names = {f.name for f in dataclasses.fields(_RunContext)}
    for required in ("run_id", "manifest", "publisher", "snapshot_ledger"):
        assert required in field_names, f"_RunContext missing field: {required}"


# ---------------------------------------------------------------------------
# 426 gate enforces stream_version for both GET and POST
# ---------------------------------------------------------------------------


def test_426_gate_get() -> None:
    import uuid

    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.auth.dependencies import get_async_session, get_config, get_current_user
    from server.config import ServerConfig
    from server.generate.routes import limiter
    from server.models import User

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/generate", params={"subject": "math"})
    finally:
        limiter.reset()

    assert response.status_code == 426
    body = response.json()
    assert body.get("code") == "CLIENT_UPDATE_REQUIRED"
    assert 2 in body.get("supported_stream_versions", [])


def test_426_gate_post() -> None:
    import uuid

    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.auth.dependencies import get_async_session, get_config, get_current_user
    from server.config import ServerConfig
    from server.generate.routes import limiter
    from server.models import User

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/api/generate", json={"subject": "math"})
    finally:
        limiter.reset()

    assert response.status_code == 426
