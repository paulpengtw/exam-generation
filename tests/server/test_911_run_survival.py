"""Issue #911 – runs survive host failure: stale detection, attempt limit, time limit,
and resume.

These tests exercise the behaviour added for issue #911 (stale-run requeue, attempt
exhaustion, 2 h time limit, and resume skipping already-ended questions).  Generation
is stubbed at the subject-spec seam.  Postgres-marked tests drive the concurrent-claim
logic that requires FOR UPDATE SKIP LOCKED.
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.config import ServerConfig
from server.generate.run import (
    MAX_ATTEMPTS,
    STALE_THRESHOLD_S,
    TIME_LIMIT_S,
    ClaimedRun,
    accept_run,
    claim_next_run,
    execute_run,
)
from server.generate.subjects import SUBJECTS
from server.models import Base, GenerationLog, GenerationQuestionState, User
from tests.server.generate_test_utils import resolved_generate_params

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
}


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class _FakeClient:
    def __init__(self, config: Any) -> None:
        self._observer: Any = None

    def set_observer(self, cb: Any) -> None:
        self._observer = cb

    def clear_observer(self) -> None:
        self._observer = None

    def emit(self, event: dict) -> None:
        if self._observer is not None:
            self._observer(event)


def _question(qid: str) -> Any:
    from src.schemas import ExamQuestion

    return ExamQuestion(
        id=qid,
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[{"編碼": "A-7-7", "說明": "lc"}],
        題目=[f"stem {qid}"],
        正確解題分析=["answer"],
        核心素養=["數-J-A2"],
        學習表現=[{"編碼": "s-IV-12", "說明": "lp"}],
    )


def _spec(do_generate: Any) -> dict[str, Any]:
    return {"math": dataclasses.replace(SUBJECTS["math"], do_generate=do_generate)}


def _ok_generate(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
    client: _FakeClient = kwargs["client"]
    client.emit(
        {"type": "stage", "agent": "generator", "stage": "llm_generate",
         "status": "start", "ts": time.time()}
    )
    return _question(kwargs["question_id"])


class _Env:
    def __init__(self, tmp_path: Path) -> None:
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
        self.sessions = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )
        self.config = ServerConfig(
            api_key="x", gemini_api_key="x", output_dir=tmp_path / "out", data_dir=Path("data")
        )
        self.app_state = MagicMock()
        self.app_state.renderer_pool = None

    async def setup(self) -> uuid.UUID:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        owner = uuid.uuid4()
        async with self.sessions() as session:
            session.add(User(id=owner, email="owner@example.com"))
            await session.commit()
        return owner

    async def accept(self, params: Any, user_id: uuid.UUID) -> Any:
        async with self.sessions() as session:
            return await accept_run(params, user_id, session=session)

    async def execute(
        self,
        claimed: ClaimedRun,
        do_generate: Any = _ok_generate,
        *,
        clock: Any = None,
        time_limit_s: float = TIME_LIMIT_S,
    ) -> None:
        kw: dict[str, Any] = {
            "app_state": self.app_state,
            "config": self.config,
            "session_factory": self.sessions,
            "host_id": "test-host",
            "client_factory": _FakeClient,
            "subjects": _spec(do_generate),
            "heartbeat_interval": 0.05,
            "time_limit_s": time_limit_s,
        }
        if clock is not None:
            kw["clock"] = clock
        await execute_run(claimed, **kw)


@pytest.fixture(autouse=True)
def _quiet_outcome_metric():
    with patch("server.observability.record_generation_outcome"):
        yield


# ---------------------------------------------------------------------------
# Stale detection and requeue
# ---------------------------------------------------------------------------

def test_stale_run_is_reclaimed(tmp_path: Path) -> None:
    """A running run whose heartbeat is too old is reclaimed by claim_next_run."""

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        # Simulate the run being claimed by a host that then crashed:
        # set status="running", heartbeat_at stale.
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD_S + 60)
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(
                    status="running",
                    attempts=1,
                    claimed_by="dead-host",
                    heartbeat_at=stale_time,
                    started_at=stale_time,
                )
            )
            await session.commit()

        # Claim should find the stale run and re-claim it.
        claimed = await claim_next_run(env.sessions, host_id="live-host")
        assert claimed is not None
        assert claimed.run_id == run_id
        assert claimed.attempt == 2  # incremented

        async with env.sessions() as session:
            log = await session.get(GenerationLog, run_id)
        assert log.claimed_by == "live-host"
        assert log.status == "running"

    asyncio.run(_run())


def test_fresh_run_claimed_before_stale(tmp_path: Path) -> None:
    """A fresh queued run is preferred over a stale running run."""

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})

        # Create a stale run.
        accepted_stale = await env.accept(params, owner)
        run_id_stale = uuid.UUID(accepted_stale.run_id)
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD_S + 60)
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id_stale)
                .values(
                    status="running",
                    attempts=1,
                    claimed_by="dead-host",
                    heartbeat_at=stale_time,
                    started_at=stale_time,
                )
            )
            await session.commit()

        # Create a second user to own a fresh queued run
        # (first user's run would be blocked by owner_is_running constraint).
        import uuid as _uuid
        other = _uuid.uuid4()
        async with env.sessions() as session:
            session.add(User(id=other, email="other@example.com"))
            await session.commit()
        accepted_fresh = await env.accept(params, other)
        run_id_fresh = uuid.UUID(accepted_fresh.run_id)

        claimed = await claim_next_run(env.sessions, host_id="live-host")
        assert claimed is not None
        assert claimed.run_id == run_id_fresh

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Attempt limit / recovery_exhausted
# ---------------------------------------------------------------------------

def test_attempt_limit_marks_run_failed_with_recovery_exhausted(tmp_path: Path) -> None:
    """A run with attempt > MAX_ATTEMPTS is marked failed without execution."""

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        # Force attempts to MAX_ATTEMPTS + 1.
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(status="running", attempts=MAX_ATTEMPTS, claimed_by="host")
            )
            await session.commit()

        # Build a ClaimedRun with attempt > MAX_ATTEMPTS.
        over_limit = ClaimedRun(
            run_id=run_id,
            user_id=owner,
            params_json=accepted.questions,  # not used when over limit
            attempt=MAX_ATTEMPTS + 1,
        )
        # Need valid params_json.
        over_limit = dataclasses.replace(over_limit, params_json=dict(params.model_dump()))
        await env.execute(over_limit)

        async with env.sessions() as session:
            log = await session.get(GenerationLog, run_id)
            states = (
                await session.execute(
                    select(GenerationQuestionState)
                    .where(GenerationQuestionState.generation_log_id == run_id)
                )
            ).scalars().all()

        assert log.status == "failed"
        assert log.error == "recovery_exhausted"
        for state in states:
            assert state.termination_reason == "failed"
            assert state.terminal_json is not None
            assert state.terminal_json.get("unknown_reason") == "recovery_exhausted"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 2-hour time limit
# ---------------------------------------------------------------------------

def test_time_limit_terminates_run(tmp_path: Path) -> None:
    """A run that started more than TIME_LIMIT_S seconds ago is terminated."""

    env = _Env(tmp_path)

    started_at_past = datetime.now(timezone.utc) - timedelta(seconds=TIME_LIMIT_S + 60)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        # Backdate started_at so time limit is already exceeded.
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(
                    status="running",
                    attempts=1,
                    claimed_by="host",
                    started_at=started_at_past,
                    heartbeat_at=started_at_past,
                )
            )
            await session.commit()

        claimed = ClaimedRun(
            run_id=run_id,
            user_id=owner,
            params_json=dict(params.model_dump()),
            attempt=1,
        )
        await env.execute(claimed)

        async with env.sessions() as session:
            log = await session.get(GenerationLog, run_id)
            states = (
                await session.execute(
                    select(GenerationQuestionState)
                    .where(GenerationQuestionState.generation_log_id == run_id)
                )
            ).scalars().all()

        assert log.status == "failed"
        assert log.error == "time_limit"
        for state in states:
            assert state.termination_reason == "failed"
            assert state.terminal_json is not None
            assert state.terminal_json.get("unknown_reason") == "time_limit"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Resume: skip already-ended questions
# ---------------------------------------------------------------------------

def test_resume_skips_already_ended_questions(tmp_path: Path) -> None:
    """On a resumed run, questions whose termination_reason is set are skipped.

    We set one question as already ended, then run the host against the same
    run. The ended question must not receive a new generation_record, while
    the unfinished question does get processed.
    """
    from server.generate.persistence import persist_generation_record  # noqa: PLC0415

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 2})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        # Mark question 0 as already ended with a terminal.
        question_0_id = accepted.questions[0]["question_id"]
        async with env.sessions() as session:
            await session.execute(
                update(GenerationQuestionState)
                .where(
                    GenerationQuestionState.generation_log_id == run_id,
                    GenerationQuestionState.question_id == question_0_id,
                )
                .values(
                    processing="ended",
                    termination_reason="normal",
                    terminal_json={
                        "termination_reason": "normal",
                        "has_final": True,
                        "final_revision": 1,
                        "delivery_status": "complete",
                        "expected": [],
                        "delivered": [],
                        "missing": [],
                        "review": {"status": "unknown", "reason": "no final content"},
                    },
                )
            )
            await session.commit()

        # Track which question IDs get generated.
        generated_ids: list[str] = []
        original_ok = _ok_generate

        def _tracking_generate(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
            generated_ids.append(kwargs["question_id"])
            return original_ok(rng_params, overrides, **kwargs)

        claimed = ClaimedRun(
            run_id=run_id,
            user_id=owner,
            params_json=dict(params.model_dump()),
            attempt=2,
        )
        await env.execute(claimed, do_generate=_tracking_generate)

        # question_0_id must NOT have been regenerated.
        assert question_0_id not in generated_ids
        # question 1 should have been generated.
        question_1_id = accepted.questions[1]["question_id"]
        assert question_1_id in generated_ids

        async with env.sessions() as session:
            state_0 = (
                await session.execute(
                    select(GenerationQuestionState)
                    .where(
                        GenerationQuestionState.generation_log_id == run_id,
                        GenerationQuestionState.question_id == question_0_id,
                    )
                )
            ).scalar_one()
        # The already-ended question must retain its original termination_reason.
        assert state_0.termination_reason == "normal"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

def test_stale_threshold_is_at_least_three_heartbeat_intervals() -> None:
    """STALE_THRESHOLD_S must be >= 3× HEARTBEAT_INTERVAL_S to give the heartbeat
    a fair chance to update before a live run is wrongly treated as stale."""
    from server.generate.run import HEARTBEAT_INTERVAL_S  # noqa: PLC0415

    assert STALE_THRESHOLD_S >= 3 * HEARTBEAT_INTERVAL_S


def test_max_attempts_is_three() -> None:
    assert MAX_ATTEMPTS == 3


def test_time_limit_is_two_hours() -> None:
    assert TIME_LIMIT_S == 7200.0
