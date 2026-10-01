"""Issue #754 — cross-layer compatibility matrix (backend assertions).

Uses a shared A/B interleaved case (math count=2, B finishes before A) identical
to the fixture in tests/fixtures/generation_v2/math_single_interleaved.jsonl.

Four-cell matrix:

  C0 = old frontend (no stream_version param)
  C1 = new frontend (stream_version=2)
  S0 = old backend (no version gate — represented here by bypassing the gate)
  S1 = new backend (version gate + v2 contract)

+-------+-----------+------------------------------------------------------+
| Combo | Operator  | This test verifies                                   |
+-------+-----------+------------------------------------------------------+
| C0/S0 | doc only  | Baseline defects documented below; no assertion on   |
|       |           | future S0 behaviour (unfixed, may vary).             |
+-------+-----------+------------------------------------------------------+
| C0/S1 | backend   | HTTP 426, CLIENT_UPDATE_REQUIRED, zero dispatch,     |
|       |           | zero model call, zero started event.                 |
+-------+-----------+------------------------------------------------------+
| C1/S0 | (frontend)| Backend side: stream_version param ignored on S0 →  |
|       |           | returns old-format events; tested via legacy fixture |
|       |           | in tests/fixtures/generation_legacy/math_single_.    |
|       |           | Frontend-side: legacyAdapter.test.ts + GeneratePage  |
|       |           | (test_754_generate_page_legacy_no_placeholders.tsx). |
+-------+-----------+------------------------------------------------------+
| C1/S1 | backend + | v2 stream: contiguous seq, question_terminal,        |
|       | frontend  | interleaved B before A, content_revision>=1.         |
+-------+-----------+------------------------------------------------------+

Documented C0/S0 defects (NOT fixed by this ticket):
 - C0 assigns card index by arrival order of 'result' events (nextFinalIndexRef++)
 - C0 does not deduplicate duplicate result events
 - C0 does not validate started manifest structure
 - C0 does not parse context/payload envelope; treats entire data as flat payload
 - C0 may let a later result overwrite an earlier draft at the same position
 - C0 has no per-question terminal evidence tracking
 - Mixed C0/S1 deployments must NOT be presented as publicly operable: S1 returns
   HTTP 426 before any SSE, so C0 users see a JSON error, not a generation stream.

Mixed deployments must NOT be publicly operable (per issue #733 resolution):
 - C0 × S1: users get 426 — no generations possible until upgrade
 - C1 × S0: users get legacy degraded view — NOT a supported production state
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Shared A/B fixture helpers (same logic as test_742_fixture.py but self-contained)
# ---------------------------------------------------------------------------


def _make_ab_question(qid: str, label: str) -> Any:
    from src.schemas import ExamQuestion

    return ExamQuestion(
        id=qid,
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[{"編碼": "A-7-7", "說明": "compat-matrix lc"}],
        題目=[f"compat-matrix {label}: {qid}"],
        正確解題分析=["answer"],
        核心素養=["數-J-A2"],
        學習表現=[{"編碼": "s-IV-12", "說明": "compat-matrix lp"}],
    )


class _FakeClient:
    def __init__(self, _config: Any) -> None:
        self._observer: Any = None

    def set_observer(self, cb: Any) -> None:
        self._observer = cb

    def clear_observer(self) -> None:
        self._observer = None

    def emit(self, event: dict[str, Any]) -> None:
        if self._observer is not None:
            self._observer(event)


def _run_ab_stream(tmp_path: Path) -> tuple[list[dict], str]:
    """Run a count=2 math stream (B finishes before A) — the shared A/B case.

    Returns (events, run_id).  Events have sidecar keys stripped for clarity.
    """
    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from tests.server.generate_test_utils import publisher_enqueue_gate, resolved_generate_params

    params = resolved_generate_params({
        "subject": "math",
        "seed": 754,  # distinct seed for compat-matrix fixture
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
        "count": 2,
        "skip_verify": True,
    })

    b_done = threading.Event()

    def fake_do_generate(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
        qid: str = kwargs["question_id"]
        is_b = qid.endswith("_002")
        label = "B" if is_b else "A"

        on_update = kwargs.get("on_question_update")
        client: _FakeClient = kwargs.get("client")
        ts = 0.0

        if client is not None:
            client.emit({
                "type": "stage", "agent": "execute",
                "stage": "generate", "status": "start", "ts": ts,
            })
            client.emit({
                "type": "llm_request", "agent": "execute",
                "model": "test-model", "ts": ts,
            })
            client.emit({
                "type": "llm_response", "agent": "execute",
                "model": "test-model", "ts": ts,
            })
            client.emit({
                "type": "stage", "agent": "execute",
                "stage": "generate", "status": "end", "ts": ts,
            })

        q = _make_ab_question(qid, label)
        if on_update:
            on_update(q, "draft")

        if not is_b:
            assert b_done.wait(timeout=10)

        return q

    _SIDECAR_KEYS = frozenset([
        "reference_example_record", "verification_trail", "figure_policy_trail",
    ])

    spec = dataclasses.replace(SUBJECTS["math"], do_generate=fake_do_generate)
    config = ServerConfig(
        api_key="x", gemini_api_key="x", output_dir=tmp_path, data_dir=Path("data"),
    )
    app_state = MagicMock()
    app_state.renderer_pool = None

    all_events: list[dict] = []

    async def collect() -> None:
        async for ev in generate_question_stream(
            params, config, app_state,
            subjects={"math": spec},
            client_factory=_FakeClient,
        ):
            all_events.append({k: v for k, v in ev.items() if k not in _SIDECAR_KEYS})

    with (
        patch("server.observability.record_generation_outcome"),
        publisher_enqueue_gate(b_done, question_index=1),
    ):
        asyncio.run(collect())

    run_id = all_events[0]["context"]["run_id"]
    return all_events, run_id


# ---------------------------------------------------------------------------
# C0 × S0 — documented defects (no runtime assertion; only commentary)
# ---------------------------------------------------------------------------


def test_c0_s0_defects_documented() -> None:
    """C0 × S0 baseline defects are documented in this module's docstring.

    This test asserts that the legacy fixture represents the S0 event format
    (no context/payload envelope, no run_id, no event_seq).
    """
    fixture_path = (
        Path(__file__).parents[1] / "fixtures" / "generation_legacy" / "math_single_legacy.jsonl"
    )
    assert fixture_path.exists(), "Legacy fixture missing — needed as C0/S0 evidence"

    events = [
        json.loads(line)
        for line in fixture_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    # S0 format: events have 'event' and 'data' keys, NO 'context' key
    for ev in events:
        assert "context" not in ev, (
            f"Legacy S0 fixture must not have 'context' key; found in: {ev.get('event')}"
        )
        assert "data" in ev, (
            f"Legacy S0 fixture must have 'data' key; missing in: {ev.get('event')}"
        )

    # No protocol_version field in started data
    started_data = json.loads(events[0]["data"])
    assert "protocol_version" not in started_data, (
        "S0 started data must not carry protocol_version"
    )
    assert "questions" not in started_data, (
        "S0 started data must not carry questions list"
    )

    # No question_terminal events in legacy format
    terminal_events = [ev for ev in events if ev.get("event") == "question_terminal"]
    assert len(terminal_events) == 0, (
        f"S0 legacy format must not have question_terminal events; found {len(terminal_events)}"
    )


# ---------------------------------------------------------------------------
# C0 × S1 — 426 zero dispatch (backend route test)
# ---------------------------------------------------------------------------


def _make_test_client():
    """Build a TestClient with auth overrides for route testing."""
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
    return app, TestClient(app, raise_server_exceptions=False)


def test_c0_s1_get_returns_426_zero_dispatch() -> None:
    """C0 × S1 (GET): missing stream_version → 426, no worker, no model call, no started."""
    generate_was_called = []

    from server.generate import service as svc_mod

    original_stream = svc_mod.generate_question_stream

    async def recording_stream(*args: Any, **kwargs: Any):
        generate_was_called.append(True)
        async for ev in original_stream(*args, **kwargs):
            yield ev

    app, client = _make_test_client()
    try:
        with patch.object(svc_mod, "generate_question_stream", new=recording_stream):
            # C0 client: no stream_version param
            response = client.get("/api/generate", params={"subject": "math"})
    finally:
        from server.generate.routes import limiter
        limiter.reset()

    # Must return 426
    assert response.status_code == 426, (
        f"Expected 426, got {response.status_code}: {response.text}"
    )

    # Response body must be CLIENT_UPDATE_REQUIRED with string detail
    body = response.json()
    assert body.get("code") == "CLIENT_UPDATE_REQUIRED", f"Unexpected body: {body}"
    assert isinstance(body.get("detail"), str), (
        "detail must be a string (C0 can display strings but not objects)"
    )
    assert 3 in body.get("supported_stream_versions", []), (
        "supported_stream_versions must include 3"
    )

    # Zero dispatch: generate_question_stream must NOT have been called
    assert not generate_was_called, (
        "generate_question_stream was called despite 426 gate; zero-dispatch violated"
    )


def test_c0_s1_post_returns_426_zero_dispatch() -> None:
    """C0 × S1 (POST): missing stream_version → 426, no dispatch."""
    generate_was_called = []

    from server.generate import service as svc_mod

    original_stream = svc_mod.generate_question_stream

    async def recording_stream(*args: Any, **kwargs: Any):
        generate_was_called.append(True)
        async for ev in original_stream(*args, **kwargs):
            yield ev

    app, client = _make_test_client()
    try:
        with patch.object(svc_mod, "generate_question_stream", new=recording_stream):
            # C0 POST: no stream_version in JSON body
            response = client.post("/api/generate", json={"subject": "math"})
    finally:
        from server.generate.routes import limiter
        limiter.reset()

    assert response.status_code == 426
    body = response.json()
    assert body.get("code") == "CLIENT_UPDATE_REQUIRED"
    assert not generate_was_called, "generate_question_stream must not run on 426"


def test_c0_s1_wrong_version_returns_426() -> None:
    """C0 × S1: stream_version=1 (unsupported) → 426."""
    app, client = _make_test_client()
    try:
        response = client.get(
            "/api/generate",
            params={"subject": "math", "stream_version": "1"},
        )
    finally:
        from server.generate.routes import limiter
        limiter.reset()

    assert response.status_code == 426
    body = response.json()
    assert body.get("code") == "CLIENT_UPDATE_REQUIRED"


def test_c0_s1_no_started_in_426_response() -> None:
    """C0 × S1: the 426 JSON response must NOT contain a 'started' SSE event."""
    app, client = _make_test_client()
    try:
        response = client.get("/api/generate", params={"subject": "math"})
    finally:
        from server.generate.routes import limiter
        limiter.reset()

    # 426 is a JSON response, not an SSE stream
    assert response.headers["content-type"].startswith("application/json"), (
        "426 response must be JSON, not SSE"
    )
    # Body is a JSON object, not event lines
    body = response.json()
    assert "event" not in body, "426 body must not look like an SSE event"
    # No "started" keyword in body
    assert "started" not in json.dumps(body), (
        "426 body must not contain 'started' event"
    )


# ---------------------------------------------------------------------------
# C1 × S1 — shared A/B interleaved case: new contract in place (backend)
# ---------------------------------------------------------------------------


def test_c1_s1_ab_interleaved_v2_contract(tmp_path: Path) -> None:
    """C1 × S1 (backend): shared A/B case produces a valid v2 stream.

    Validates:
     - started has protocol_version=2 with questions manifest
     - B's result arrives before A's (interleaving works)
     - Both questions have question_terminal
     - content_revision >= 1 on all question_update and result events
     - event_seq is contiguous starting at 1
     - question_terminal payload validates against protocol schema
    """
    from server.generate.event_protocol import QuestionTerminalPayload

    events, run_id = _run_ab_stream(tmp_path)

    # --- started ---
    assert events[0]["event"] == "started"
    assert events[0]["context"]["event_seq"] == 1
    payload = events[0]["payload"]
    assert payload.get("protocol_version") == 2
    manifest = {q["index"]: q["question_id"] for q in payload.get("questions", [])}
    assert set(manifest.keys()) == {0, 1}, f"Manifest must cover indices 0 and 1: {manifest}"

    # --- interleaving: B's result before A's ---
    results = {
        ev["context"]["index"]: ev
        for ev in events
        if ev["event"] == "result"
    }
    assert 0 in results and 1 in results, "Both questions must have result events"
    assert results[1]["context"]["event_seq"] < results[0]["context"]["event_seq"], (
        "B (index 1) must finish before A (index 0) — interleaving check"
    )

    # --- terminal after result for each question ---
    terminals = {
        ev["context"]["index"]: ev
        for ev in events
        if ev["event"] == "question_terminal"
    }
    assert set(terminals.keys()) == {0, 1}, "Both questions must have question_terminal"
    for idx in (0, 1):
        result_seq = results[idx]["context"]["event_seq"]
        terminal_seq = terminals[idx]["context"]["event_seq"]
        assert terminal_seq > result_seq, (
            f"Index {idx}: terminal (seq {terminal_seq}) must follow result (seq {result_seq})"
        )

    # --- content_revision >= 1 ---
    for ev in events:
        if ev["event"] in ("question_update", "result"):
            rev = ev["context"].get("content_revision")
            assert rev is not None and rev >= 1, (
                f"event {ev['event']} index={ev['context'].get('index')} has content_revision={rev}"
            )

    # --- contiguous seq ---
    seqs = sorted(ev["context"]["event_seq"] for ev in events if "context" in ev)
    assert seqs == list(range(1, len(seqs) + 1)), f"Seq must be contiguous: {seqs}"

    # --- terminal payload validates ---
    for ev in events:
        if ev["event"] == "question_terminal":
            QuestionTerminalPayload.model_validate(ev["payload"])

    # --- last event is done ---
    assert events[-1]["event"] == "done"


def test_c1_s1_question_ids_match_manifest(tmp_path: Path) -> None:
    """C1 × S1: every per-question event must use a question_id declared in started."""
    events, _ = _run_ab_stream(tmp_path)

    manifest_ids = {
        q["question_id"] for q in events[0]["payload"]["questions"]
    }

    for ev in events:
        qid = ev.get("context", {}).get("question_id")
        if qid is not None:
            assert qid in manifest_ids, (
                f"Event {ev['event']!r} carries question_id {qid!r} not in manifest"
            )


def test_c1_s1_result_payload_is_plain_question(tmp_path: Path) -> None:
    """C1 × S1: result payload must be the plain question dict (no envelope keys)."""
    events, _ = _run_ab_stream(tmp_path)

    for ev in events:
        if ev["event"] != "result":
            continue
        payload = ev["payload"]
        for forbidden in ("context", "event_seq", "payload", "protocol_version"):
            assert forbidden not in payload, (
                f"result payload must not contain envelope key {forbidden!r}"
            )
        assert "id" in payload, "result payload must have 'id'"


# ---------------------------------------------------------------------------
# Mixed-deployment note (assertion, not just documentation)
# ---------------------------------------------------------------------------


def test_mixed_deployment_c0_s1_produces_no_generation() -> None:
    """Mixed C0/S1 deployments: no generations can succeed until all clients upgrade.

    This asserts that a C0 request produces 426 — zero generations. The docstring
    makes clear this combination must NOT be presented as publicly operable.
    """
    app, client = _make_test_client()
    try:
        # A realistic C0 client: typical GET params, no stream_version
        response = client.get(
            "/api/generate",
            params={
                "subject": "math",
                "seed": "41",
                "grade": "8",
                "context": '["個人"]',
                "set_type": "單一題",
                "q_type": '["選擇題"]',
                "style": '["text_only"]',
                "math_thinking": '["形成"]',
                "learning_content": '["A-7-7"]',
                "learning_performance": '["s-IV-12"]',
                "core_competency": '["數-J-A2"]',
            },
        )
    finally:
        from server.generate.routes import limiter
        limiter.reset()

    assert response.status_code == 426, (
        "Mixed C0/S1 must return 426 — no generation stream produced. "
        "This combination is NOT publicly operable."
    )
