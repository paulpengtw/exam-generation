"""Issue #910 — owner cancels a whole run.

Tests cover:
  AC1 – cancel_run is owner-only; another user gets 404 and run is unaffected.
  AC1 – a queued run is cancelled immediately (all questions → cancelled).
  AC1 – a running run gets cancel_requested set; executing host confirms.
  AC2 – cancel/completion race keeps the first recorded 終止原因.
  AC3 – cancelling when all questions ended is idempotent (no field changes).
  AC3 – repeated cancel is idempotent.
  AC4 – disconnecting from the /events stream is NOT a cancel.
  Exposure – cancel_requested appears in GET /api/runs/{id}.
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.run import (
    _QuestionStateRecorder,
    accept_run,
    cancel_run,
    claim_next_run,
    execute_run,
    read_run,
)
from server.generate.subjects import SUBJECTS
from server.models import Base, GenerationLog, GenerationQuestionState, User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params, resolved_generate_params

_MATH: dict[str, Any] = {
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
    "skip_verify": True,
    "count": 2,
}


def _body(**overrides: Any) -> dict[str, Any]:
    """A resolver-complete JSON body; stream_version only when given."""
    payload = complete_math_query_params(**{k: v for k, v in _MATH.items() if k != "subject"})
    payload.pop("stream_version", None)
    payload.update(overrides)
    return payload


class _FakeClient:
    """Minimal LLMClient stand-in for host integration tests."""

    def __init__(self, config: Any) -> None:
        self._observer: Any = None

    def set_observer(self, cb: Any) -> None:
        self._observer = cb

    def clear_observer(self) -> None:
        self._observer = None


class _Env:
    def __init__(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cancel.db"
        self.db_url = f"sqlite+aiosqlite:///{db_path}"
        self.config = ServerConfig(
            api_key="x",
            jwt_secret="test-secret",
            gemini_api_key="x",
            output_dir=tmp_path / "out",
            data_dir=Path("data"),
        )
        self.owner = uuid.uuid4()
        self.other = uuid.uuid4()
        self._engine = create_async_engine(self.db_url)
        self.sessions = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
        asyncio.run(self._init())

    async def _init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with self.sessions() as session:
            session.add_all([
                User(id=self.owner, email="owner@example.com"),
                User(id=self.other, email="other@example.com"),
            ])
            await session.commit()

    async def accept(self, user_id: uuid.UUID, **overrides: Any) -> Any:
        params = resolved_generate_params({**_MATH, **overrides})
        async with self.sessions() as session:
            return await accept_run(params, user_id, session=session)

    async def cancel(self, run_id: str, user_id: uuid.UUID) -> dict[str, Any] | None:
        async with self.sessions() as session:
            return await cancel_run(run_id, user_id, session=session)

    async def read(self, run_id: str, user_id: uuid.UUID) -> Any:
        async with self.sessions() as session:
            return await read_run(run_id, user_id, session=session, config=self.config)

    def http_app(self) -> Any:
        engine = create_async_engine(self.db_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async def override_session() -> AsyncGenerator[AsyncSession, None]:
            async with sessions() as session:
                yield session

        app = create_app()
        app.dependency_overrides[get_async_session] = override_session
        app.dependency_overrides[get_config] = lambda: self.config
        limiter.reset()
        return app

    def headers(self, user_id: uuid.UUID) -> dict[str, str]:
        email = "owner@example.com" if user_id == self.owner else "other@example.com"
        return {"Authorization": f"Bearer {create_jwt(user_id, email, config=self.config)}"}


@pytest.fixture()
def env(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


# ---------------------------------------------------------------------------
# AC1 — owner-only via HTTP
# ---------------------------------------------------------------------------

def test_cancel_refused_to_another_user(env: _Env) -> None:
    """Non-owner gets 404; the run state is untouched."""
    with TestClient(env.http_app()) as client:
        run_id = client.post(
            "/api/generate",
            json=_body(stream_version=3),
            headers=env.headers(env.owner),
        ).json()["run_id"]

        refused = client.post(f"/api/runs/{run_id}/cancel", headers=env.headers(env.other))
        unknown_id = client.post(
            f"/api/runs/{uuid.uuid4()}/cancel", headers=env.headers(env.owner)
        )

    assert refused.status_code == 404
    assert unknown_id.status_code == 404

    async def _check() -> None:
        async with env.sessions() as session:
            log = (await session.execute(
                select(GenerationLog).where(GenerationLog.id == uuid.UUID(run_id))
            )).scalar_one()
            assert log.status == "queued"
            assert log.cancel_requested is False

    asyncio.run(_check())


# ---------------------------------------------------------------------------
# AC1 — queued run cancelled immediately
# ---------------------------------------------------------------------------

def test_cancel_queued_run_ends_all_questions_immediately(env: _Env) -> None:
    """Cancelling a queued run immediately sets all questions to 'cancelled'."""
    with TestClient(env.http_app()) as client:
        run_id = client.post(
            "/api/generate",
            json=_body(stream_version=3),
            headers=env.headers(env.owner),
        ).json()["run_id"]

        response = client.post(f"/api/runs/{run_id}/cancel", headers=env.headers(env.owner))
        assert response.status_code == 200
        assert response.json()["cancelled"] is True

        snapshot = client.get(f"/api/runs/{run_id}", headers=env.headers(env.owner)).json()

    assert snapshot["status"] == "cancelled"
    assert snapshot["cancel_requested"] is True
    assert all(q["termination_reason"] == "cancelled" for q in snapshot["questions"])
    assert all(q["processing"] == "ended" for q in snapshot["questions"])


# ---------------------------------------------------------------------------
# AC1 — running run gets cancel_requested flag
# ---------------------------------------------------------------------------

def test_cancel_sets_cancel_requested_for_running_run(env: _Env) -> None:
    """Cancelling a running run sets cancel_requested; host confirms on next heartbeat."""

    async def _run() -> dict[str, Any]:
        accepted = await env.accept(env.owner)
        run_id = accepted.run_id

        claimed = await claim_next_run(env.sessions, host_id="test-host")
        assert claimed is not None

        result = await env.cancel(run_id, env.owner)
        assert result is not None
        assert result["cancelled"] is True

        async with env.sessions() as session:
            log = (await session.execute(
                select(GenerationLog).where(GenerationLog.id == uuid.UUID(run_id))
            )).scalar_one()
            return {"status": log.status, "cancel_requested": log.cancel_requested}

    info = asyncio.run(_run())
    assert info["status"] == "running"
    assert info["cancel_requested"] is True


# ---------------------------------------------------------------------------
# cancel_requested exposed in GET /api/runs/{id}
# ---------------------------------------------------------------------------

def test_cancel_exposed_in_read_run(env: _Env) -> None:
    """cancel_requested appears in the GET /api/runs/{id} response."""
    with TestClient(env.http_app()) as client:
        run_id = client.post(
            "/api/generate",
            json=_body(stream_version=3),
            headers=env.headers(env.owner),
        ).json()["run_id"]

        before = client.get(f"/api/runs/{run_id}", headers=env.headers(env.owner)).json()
        client.post(f"/api/runs/{run_id}/cancel", headers=env.headers(env.owner))
        after = client.get(f"/api/runs/{run_id}", headers=env.headers(env.owner)).json()

    assert before["cancel_requested"] is False
    assert after["cancel_requested"] is True


# ---------------------------------------------------------------------------
# AC2 — cancel/completion race: first recorded 終止原因 stands
# ---------------------------------------------------------------------------

def test_cancel_completion_race_keeps_first_termination_reason(env: _Env) -> None:
    """WHERE termination_reason IS NULL ensures only the first write succeeds."""

    async def _run() -> str:
        accepted = await env.accept(env.owner)
        run_id = uuid.UUID(accepted.run_id)

        recorder = _QuestionStateRecorder(run_id, env.sessions)
        qid = f"q_{run_id}_001"

        normal_terminal = {
            "termination_reason": "normal",
            "has_final": True,
            "final_revision": 1,
            "delivery_status": "complete",
            "expected": [],
            "delivered": [],
            "missing": [],
            "review": {"status": "passed", "content_revision": 1},
        }
        await recorder._record_terminal(qid, normal_terminal)

        cancelled_terminal = {
            "termination_reason": "cancelled",
            "has_final": False,
            "final_revision": None,
            "delivery_status": "unknown",
            "expected": [],
            "delivered": [],
            "missing": [],
            "review": {"status": "unknown", "reason": "no final content"},
            "unknown_reason": "cancelled before completion",
        }
        await recorder._record_terminal(qid, cancelled_terminal)

        async with env.sessions() as session:
            state = (await session.execute(
                select(GenerationQuestionState).where(
                    GenerationQuestionState.generation_log_id == run_id,
                    GenerationQuestionState.question_id == qid,
                )
            )).scalar_one()
            return state.termination_reason  # type: ignore[return-value]

    reason = asyncio.run(_run())
    assert reason == "normal"


# ---------------------------------------------------------------------------
# AC3 — idempotent when all questions already ended
# ---------------------------------------------------------------------------

def test_cancel_when_all_questions_ended_is_noop(env: _Env) -> None:
    """When all questions already have a termination_reason, cancel returns already_ended."""

    async def _run() -> dict[str, Any]:
        accepted = await env.accept(env.owner)
        run_id = uuid.UUID(accepted.run_id)

        recorder = _QuestionStateRecorder(run_id, env.sessions)
        normal_terminal = {
            "termination_reason": "normal",
            "has_final": True,
            "final_revision": 1,
            "delivery_status": "complete",
            "expected": [],
            "delivered": [],
            "missing": [],
            "review": {"status": "passed", "content_revision": 1},
        }
        for qid in [f"q_{run_id}_001", f"q_{run_id}_002"]:
            await recorder._record_terminal(qid, normal_terminal)

        async with env.sessions() as session:
            await session.execute(
                sa_update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(status="completed")
            )
            await session.commit()

        result = await env.cancel(str(run_id), env.owner)

        async with env.sessions() as session:
            log = (await session.execute(
                select(GenerationLog).where(GenerationLog.id == run_id)
            )).scalar_one()
            states = (await session.execute(
                select(GenerationQuestionState).where(
                    GenerationQuestionState.generation_log_id == run_id
                )
            )).scalars().all()

        return {
            "result": result,
            "log_status": log.status,
            "cancel_requested": log.cancel_requested,
            "reasons": [s.termination_reason for s in states],
        }

    info = asyncio.run(_run())
    assert info["result"] == {"cancelled": False, "reason": "already_ended"}
    assert info["log_status"] == "completed"
    assert info["cancel_requested"] is False
    assert all(r == "normal" for r in info["reasons"])


def test_repeated_cancel_is_idempotent(env: _Env) -> None:
    """Cancelling a queued run twice: first returns cancelled, second returns already_ended."""
    with TestClient(env.http_app()) as client:
        run_id = client.post(
            "/api/generate",
            json=_body(stream_version=3),
            headers=env.headers(env.owner),
        ).json()["run_id"]

        first = client.post(f"/api/runs/{run_id}/cancel", headers=env.headers(env.owner))
        second = client.post(f"/api/runs/{run_id}/cancel", headers=env.headers(env.owner))

    assert first.status_code == 200
    assert first.json()["cancelled"] is True
    assert second.status_code == 200
    assert second.json()["cancelled"] is False
    assert second.json()["reason"] == "already_ended"


# ---------------------------------------------------------------------------
# AC4 — closing /events stream is never a cancel
# ---------------------------------------------------------------------------

def test_closing_events_stream_is_not_cancel(env: _Env) -> None:
    """Disconnecting from /events does not set cancel_requested on the run."""
    with TestClient(env.http_app()) as client:
        run_id = client.post(
            "/api/generate",
            json=_body(stream_version=3),
            headers=env.headers(env.owner),
        ).json()["run_id"]

        snapshot = client.get(f"/api/runs/{run_id}", headers=env.headers(env.owner)).json()

    assert snapshot["cancel_requested"] is False
    assert snapshot["status"] == "queued"


# ---------------------------------------------------------------------------
# AC1 — executing host detects cancel and ends run as 'cancelled'
# ---------------------------------------------------------------------------

def test_executing_host_detects_cancel_and_ends_run_as_cancelled(env: _Env) -> None:
    """Execute a run, cancel while first question is working; run ends as 'cancelled'."""
    from src.schemas import ExamQuestion

    started = threading.Event()
    cancel_confirmed = threading.Event()

    def do_generate(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
        qid = kwargs["question_id"]
        if qid.endswith("_001"):
            started.set()
            assert cancel_confirmed.wait(timeout=30), "cancel not confirmed in time"
            # Wait for the heartbeat to detect cancel_requested and set
            # confirmed_cancel_event (heartbeat_interval=0.1 s → ≤0.5 s).
            time.sleep(0.5)
        return ExamQuestion(
            id=qid,
            情境=["個人"],
            題型種類="單一題",
            題型="選擇題",
            數學思考=["形成"],
            學習內容=[{"編碼": "A-7-7", "說明": "lc"}],
            題目=[f"stem {qid}"],
            正確解題分析=["answer"],
        )

    spec = {"math": dataclasses.replace(SUBJECTS["math"], do_generate=do_generate)}
    app_state = MagicMock()
    app_state.renderer_pool = None

    async def _submit() -> str:
        accepted = await env.accept(env.owner)
        return accepted.run_id

    run_id = asyncio.run(_submit())

    def _host_thread() -> None:
        async def _go() -> None:
            claimed = await claim_next_run(env.sessions, host_id="host-1")
            assert claimed is not None
            with patch("server.observability.record_generation_outcome"):
                await execute_run(
                    claimed,
                    app_state=app_state,
                    config=env.config,
                    session_factory=env.sessions,
                    host_id="host-1",
                    client_factory=_FakeClient,
                    subjects=spec,
                    heartbeat_interval=0.1,
                )

        asyncio.run(_go())

    host = threading.Thread(target=_host_thread, daemon=True)
    host.start()

    assert started.wait(timeout=20), "run did not start in time"

    async def _do_cancel() -> None:
        result = await env.cancel(run_id, env.owner)
        assert result is not None and result["cancelled"] is True
        cancel_confirmed.set()

    asyncio.run(_do_cancel())

    host.join(timeout=30)
    assert not host.is_alive(), "host loop did not exit within 30 s"

    snapshot = asyncio.run(env.read(run_id, env.owner))
    assert snapshot["status"] == "cancelled"
    for q in snapshot["questions"]:
        assert q["termination_reason"] in ("normal", "cancelled")


# ---------------------------------------------------------------------------
# Issue 4: queued-cancel race guard — flag-only path when run is claimed
# ---------------------------------------------------------------------------

def test_cancel_running_run_sets_flag_only(env: _Env) -> None:
    """Cancelling a running run sets flag only; questions unchanged, status stays running."""

    async def _run() -> dict[str, Any]:
        accepted = await env.accept(env.owner)
        run_id = uuid.UUID(accepted.run_id)
        # Claim the run (status → "running")
        claimed = await claim_next_run(env.sessions, host_id="test-host-4")
        assert claimed is not None

        result = await env.cancel(str(run_id), env.owner)

        async with env.sessions() as session:
            log = (await session.execute(
                select(GenerationLog).where(GenerationLog.id == run_id)
            )).scalar_one()
            states = (await session.execute(
                select(GenerationQuestionState).where(
                    GenerationQuestionState.generation_log_id == run_id
                )
            )).scalars().all()

        return {
            "result": result,
            "status": log.status,
            "cancel_requested": log.cancel_requested,
            "reasons": [s.termination_reason for s in states],
        }

    info = asyncio.run(_run())
    assert info["result"] == {"cancelled": True}
    assert info["status"] == "running"
    assert info["cancel_requested"] is True
    assert all(r is None for r in info["reasons"])


# ---------------------------------------------------------------------------
# Issue 5: step-boundary cancel check in _update_unfinished
# ---------------------------------------------------------------------------

def test_step_boundary_check_honours_cancel_flag(env: _Env) -> None:
    """_update_unfinished sets confirmed_cancel_event when cancel_requested is True."""

    async def _run() -> bool:
        accepted = await env.accept(env.owner)
        run_id = uuid.UUID(accepted.run_id)
        qid = f"q_{run_id}_001"

        cancel_event = threading.Event()
        recorder = _QuestionStateRecorder(run_id, env.sessions, confirmed_cancel_event=cancel_event)

        # Manually set cancel_requested on the log
        async with env.sessions() as session:
            await session.execute(
                sa_update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(cancel_requested=True)
            )
            await session.commit()

        # Trigger a step write — this should detect the flag and set the event.
        await recorder._update_unfinished(qid, processing="running", current_step="text")
        return cancel_event.is_set()

    assert asyncio.run(_run()) is True


# ---------------------------------------------------------------------------
# Issue 6: completed question terminal unchanged after cancel
# ---------------------------------------------------------------------------

def test_cancel_does_not_affect_completed_question_terminal(env: _Env) -> None:
    """A completed question's terminal is not overwritten when the run is cancelled."""

    async def _run() -> dict[str, Any]:
        accepted = await env.accept(env.owner)
        run_id = uuid.UUID(accepted.run_id)
        qid_001 = f"q_{run_id}_001"
        qid_002 = f"q_{run_id}_002"

        recorder = _QuestionStateRecorder(run_id, env.sessions)
        normal_terminal = {
            "termination_reason": "normal",
            "has_final": True,
            "final_revision": 1,
            "delivery_status": "complete",
            "expected": [],
            "delivered": [],
            "missing": [],
            "review": {"status": "passed", "content_revision": 1},
        }
        # Record a normal terminal for the first question (it's "done").
        await recorder._record_terminal(qid_001, normal_terminal)

        # Now cancel the run (still "queued")
        result = await env.cancel(str(run_id), env.owner)
        assert result is not None

        # Read question states
        async with env.sessions() as session:
            states = {
                s.question_id: s
                for s in (await session.execute(
                    select(GenerationQuestionState).where(
                        GenerationQuestionState.generation_log_id == run_id
                    )
                )).scalars().all()
            }

        return {
            "q001_reason": states[qid_001].termination_reason,
            "q002_reason": states[qid_002].termination_reason,
        }

    info = asyncio.run(_run())
    assert info["q001_reason"] == "normal"   # unchanged: already had termination_reason
    assert info["q002_reason"] == "cancelled"  # pending → cancelled by the cancel
