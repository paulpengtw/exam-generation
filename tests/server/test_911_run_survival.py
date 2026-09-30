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


def test_stale_run_claimed_before_fresh(tmp_path: Path) -> None:
    """A stale running run is preferred over a fresh queued run (stale-first policy)."""

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})

        # Create a stale run for owner.
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

        # Create a second user to own a fresh queued run.
        import uuid as _uuid
        other = _uuid.uuid4()
        async with env.sessions() as session:
            session.add(User(id=other, email="other@example.com"))
            await session.commit()
        accepted_fresh = await env.accept(params, other)
        run_id_fresh = uuid.UUID(accepted_fresh.run_id)

        # Stale-first policy: stale run must be claimed before the fresh queued run.
        claimed = await claim_next_run(env.sessions, host_id="live-host")
        assert claimed is not None
        assert claimed.run_id == run_id_stale, (
            f"Expected stale run {run_id_stale} to be claimed first; "
            f"got {claimed.run_id} (fresh run {run_id_fresh})"
        )
        assert claimed.attempt == 2

        # Second claim should get the fresh run.
        claimed2 = await claim_next_run(env.sessions, host_id="live-host")
        assert claimed2 is not None
        assert claimed2.run_id == run_id_fresh

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
# Item 1 — exhausted / time-limit stale runs must be finalised, not stuck
# ---------------------------------------------------------------------------

def test_exhausted_stale_run_is_finalized_by_claim(tmp_path: Path) -> None:
    """claim_next_run finalizes (not reclaims) a stale run that has used all attempts."""

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        # Make the run stale with attempts == MAX_ATTEMPTS (exhausted).
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD_S + 60)
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(
                    status="running",
                    attempts=MAX_ATTEMPTS,
                    claimed_by="dead-host",
                    heartbeat_at=stale_time,
                    started_at=stale_time,
                )
            )
            await session.commit()

        # claim_next_run must finalize the exhausted run and return None.
        result = await claim_next_run(env.sessions, host_id="live-host")
        assert result is None, "exhausted stale run must be finalized, not returned"

        # The run must be marked failed.
        async with env.sessions() as session:
            log = await session.get(GenerationLog, run_id)
        assert log.status == "failed"
        assert log.error == "recovery_exhausted"

        # All unfinished questions must get a terminal with recovery_exhausted.
        async with env.sessions() as session:
            states = (
                await session.execute(
                    select(GenerationQuestionState)
                    .where(GenerationQuestionState.generation_log_id == run_id)
                )
            ).scalars().all()
        for state in states:
            assert state.termination_reason == "failed"
            assert state.terminal_json is not None
            assert state.terminal_json.get("unknown_reason") == "recovery_exhausted"

    asyncio.run(_run())


def test_time_limit_stale_run_is_finalized_by_claim(tmp_path: Path) -> None:
    """claim_next_run finalizes a stale run whose wall-clock limit has been exceeded."""

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        # Make the run stale AND past the 2h limit (but attempts == 1, not exhausted).
        past = datetime.now(timezone.utc) - timedelta(seconds=TIME_LIMIT_S + 60)
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
                    started_at=past,
                )
            )
            await session.commit()

        result = await claim_next_run(env.sessions, host_id="live-host")
        assert result is None, "time-limit stale run must be finalized, not returned"

        async with env.sessions() as session:
            log = await session.get(GenerationLog, run_id)
        assert log.status == "failed"
        assert log.error == "time_limit"

        async with env.sessions() as session:
            states = (
                await session.execute(
                    select(GenerationQuestionState)
                    .where(GenerationQuestionState.generation_log_id == run_id)
                )
            ).scalars().all()
        for state in states:
            assert state.termination_reason == "failed"
            assert state.terminal_json is not None
            assert state.terminal_json.get("unknown_reason") == "time_limit"

    asyncio.run(_run())


def test_exhausted_stale_run_unblocks_teachers_queued_run(tmp_path: Path) -> None:
    """After claim_next_run finalizes an exhausted stale run, the same teacher's
    queued run becomes claimable on the next claim attempt."""

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})

        # Create and exhaust a running run.
        accepted_stale = await env.accept(params, owner)
        run_id_stale = uuid.UUID(accepted_stale.run_id)
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD_S + 60)
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id_stale)
                .values(
                    status="running",
                    attempts=MAX_ATTEMPTS,
                    claimed_by="dead-host",
                    heartbeat_at=stale_time,
                    started_at=stale_time,
                )
            )
            await session.commit()

        # Directly insert a queued run for the same teacher (bypassing accept_run
        # so we don't hit the queue-limit check against the running run).
        from server.models import GenerationQuestionState as _GQS  # noqa: PLC0415
        queued_run_id = uuid.uuid4()
        qid = f"q_{str(queued_run_id).replace('-', '')}_001"
        async with env.sessions() as session:
            session.add(GenerationLog(
                id=queued_run_id,
                user_id=owner,
                status="queued",
                params_json=params.model_dump(),
                submission_key=str(uuid.uuid4()),
                started_at=datetime.now(timezone.utc),
                heartbeat_at=datetime.now(timezone.utc),
                attempts=0,
            ))
            await session.flush()
            session.add(_GQS(
                generation_log_id=queued_run_id,
                question_id=qid,
                index=0,
                processing="waiting",
            ))
            await session.commit()

        # First claim: finalizes the stale exhausted run, returns None.
        result1 = await claim_next_run(env.sessions, host_id="live-host")
        assert result1 is None, "first claim should finalize exhausted run and return None"

        # Second claim: the queued run should now be claimable.
        result2 = await claim_next_run(env.sessions, host_id="live-host")
        assert result2 is not None, "second claim should find the teacher's queued run"
        assert result2.run_id == queued_run_id

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Item 4 — fake-clock boundary tests
# ---------------------------------------------------------------------------

def test_stale_boundary_at_exactly_threshold(tmp_path: Path) -> None:
    """A run is stale at exactly STALE_THRESHOLD_S seconds, not at STALE_THRESHOLD_S - 1."""

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        now = datetime.now(timezone.utc)
        # Exactly at threshold: heartbeat_at = now - STALE_THRESHOLD_S.
        at_threshold = now - timedelta(seconds=STALE_THRESHOLD_S)
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(
                    status="running",
                    attempts=1,
                    claimed_by="dead-host",
                    heartbeat_at=at_threshold,
                    started_at=at_threshold,
                )
            )
            await session.commit()

        # claim_next_run uses now=datetime.now() by default.
        # At exactly the threshold (<=), the run should be found as stale.
        claimed = await claim_next_run(env.sessions, host_id="live-host", now=now)
        assert claimed is not None, "run at exactly STALE_THRESHOLD_S should be stale"
        assert claimed.run_id == run_id

    asyncio.run(_run())


def test_not_stale_at_one_second_before_threshold(tmp_path: Path) -> None:
    """A run is NOT stale at STALE_THRESHOLD_S - 1 seconds."""

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        now = datetime.now(timezone.utc)
        # One second before threshold: run is NOT yet stale.
        just_before = now - timedelta(seconds=STALE_THRESHOLD_S - 1)
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(
                    status="running",
                    attempts=1,
                    claimed_by="live-host",
                    heartbeat_at=just_before,
                    started_at=just_before,
                )
            )
            await session.commit()

        claimed = await claim_next_run(env.sessions, host_id="other-host", now=now)
        assert claimed is None, "run at STALE_THRESHOLD_S - 1 s should not be stale"

    asyncio.run(_run())


def test_time_limit_via_heartbeat_stops_run(tmp_path: Path) -> None:
    """When the heartbeat detects the time limit, the run is terminated with time_limit."""

    env = _Env(tmp_path)

    # Fake clock: starts at a time that will exceed the limit on the first heartbeat.
    # We back-date started_at to TIME_LIMIT_S + 60 seconds ago.
    start_time = datetime.now(timezone.utc) - timedelta(seconds=TIME_LIMIT_S + 60)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        # Pre-set started_at to back in time so heartbeat detects time limit.
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(
                    status="running",
                    attempts=1,
                    claimed_by="host",
                    heartbeat_at=start_time,
                    started_at=start_time,
                )
            )
            await session.commit()

        claimed = ClaimedRun(
            run_id=run_id,
            user_id=owner,
            params_json=dict(params.model_dump()),
            attempt=1,
        )
        await env.execute(claimed, time_limit_s=1.0)  # tight limit so heartbeat triggers quickly

        async with env.sessions() as session:
            log = await session.get(GenerationLog, run_id)
        assert log.status == "failed"
        assert log.error == "time_limit"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Item 2 — reason plumbing: read_run returns termination data correctly
# ---------------------------------------------------------------------------

def test_read_run_exposes_recovery_exhausted_reason(tmp_path: Path) -> None:
    """read_run returns terminal.unknown_reason='recovery_exhausted' for exhausted runs."""
    from server.generate.run import read_run  # noqa: PLC0415

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        # Execute with attempt > MAX_ATTEMPTS → recovery_exhausted.
        over_limit = ClaimedRun(
            run_id=run_id,
            user_id=owner,
            params_json=dict(params.model_dump()),
            attempt=MAX_ATTEMPTS + 1,
        )
        await env.execute(over_limit)

        async with env.sessions() as session:
            snapshot = await read_run(run_id, owner, session=session, config=env.config)

        assert snapshot is not None
        assert snapshot["status"] == "failed"
        assert snapshot["error"] == "recovery_exhausted"
        for q in snapshot["questions"]:
            assert q["termination_reason"] == "failed"
            assert q["terminal"] is not None
            assert q["terminal"].get("unknown_reason") == "recovery_exhausted"

    asyncio.run(_run())


def test_read_run_exposes_time_limit_reason(tmp_path: Path) -> None:
    """read_run returns terminal.unknown_reason='time_limit' for time-limited runs."""
    from server.generate.run import read_run  # noqa: PLC0415

    env = _Env(tmp_path)

    started_at_past = datetime.now(timezone.utc) - timedelta(seconds=TIME_LIMIT_S + 60)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

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
            snapshot = await read_run(run_id, owner, session=session, config=env.config)

        assert snapshot is not None
        assert snapshot["status"] == "failed"
        assert snapshot["error"] == "time_limit"
        for q in snapshot["questions"]:
            assert q["terminal"] is not None
            assert q["terminal"].get("unknown_reason") == "time_limit"

    asyncio.run(_run())


def test_read_run_normal_question_keeps_normal_termination(tmp_path: Path) -> None:
    """A normally finished question retains termination_reason='normal' in read_run."""
    from server.generate.run import read_run  # noqa: PLC0415

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        claimed = ClaimedRun(
            run_id=run_id,
            user_id=owner,
            params_json=dict(params.model_dump()),
            attempt=1,
        )
        await env.execute(claimed)

        async with env.sessions() as session:
            snapshot = await read_run(run_id, owner, session=session, config=env.config)

        assert snapshot is not None
        assert snapshot["status"] == "completed"
        for q in snapshot["questions"]:
            assert q["termination_reason"] == "normal"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Item 5 — resume with saved record: exactly one generation_records row
# ---------------------------------------------------------------------------

def test_resume_with_saved_record_no_duplicate(tmp_path: Path) -> None:
    """A question that already has a generation_record but no termination_reason
    must not get a second record after resume; exactly one row must remain."""
    from server.generate.persistence import persist_generation_record  # noqa: PLC0415
    from server.models import GenerationRecord  # noqa: PLC0415

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        q0_id = accepted.questions[0]["question_id"]

        # Persist a generation_record for the question (simulating partial progress).
        question = _question(q0_id)
        await persist_generation_record(
            user_id=owner,
            generation_log_id=run_id,
            subject="math",
            params=params,
            payload=question.model_dump(mode="json"),
            session_factory=env.sessions,
        )

        # Do NOT set termination_reason — the question is saved but not terminated.
        # Resume: the question is NOT in skip_question_ids (no termination_reason).
        claimed = ClaimedRun(
            run_id=run_id,
            user_id=owner,
            params_json=dict(params.model_dump()),
            attempt=2,
        )
        await env.execute(claimed)

        # Exactly one GenerationRecord row must exist for this question.
        async with env.sessions() as session:
            rows = (
                await session.execute(
                    select(GenerationRecord)
                    .where(
                        GenerationRecord.generation_log_id == run_id,
                        GenerationRecord.question_id == q0_id,
                    )
                )
            ).scalars().all()
        # The insert-or-ignore constraint means only one row survives.
        assert len(rows) == 1, f"expected 1 record, got {len(rows)}"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Item 6 — attempt number in trail entries
# ---------------------------------------------------------------------------

def test_attempt_number_tagged_in_trail_entries(tmp_path: Path) -> None:
    """execute_run with attempt=2 tags figure-policy trail entries with 'attempt': 2."""
    from server.generate.persistence import FigurePolicyTrailRecorder  # noqa: PLC0415

    env = _Env(tmp_path)

    # Track the `attempt` value the factory was called with.
    factory_calls: list[int] = []

    def _patched_make_recorder(  # noqa: ANN001, ANN202
        *, generation_log_id, loop, session_factory, attempt=1, prior_entries=None
    ):
        factory_calls.append(attempt)
        return FigurePolicyTrailRecorder(
            generation_log_id, loop, session_factory, attempt=attempt,
            prior_entries=prior_entries,
        )

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        claimed = ClaimedRun(
            run_id=run_id,
            user_id=owner,
            params_json=dict(params.model_dump()),
            attempt=2,  # second attempt — factory must receive attempt=2
        )

        import server.generate.service as _svc  # noqa: PLC0415
        with patch.object(_svc, "make_figure_policy_trail_recorder", _patched_make_recorder):
            await env.execute(claimed)

        # The factory must have been called with attempt=2 from _build_run_context.
        assert factory_calls, (
            "make_figure_policy_trail_recorder was never called; "
            "execute_run must call generate_question_stream which calls _build_run_context"
        )
        assert all(a == 2 for a in factory_calls), (
            f"make_figure_policy_trail_recorder was called with attempt={factory_calls!r}; "
            "all calls must receive attempt=claimed.attempt (2)"
        )

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


# ---------------------------------------------------------------------------
# Finding 1 — persist_failed_generation_record called at claim-time finalization
# ---------------------------------------------------------------------------

def test_claim_time_finalization_persists_failed_record(tmp_path: Path) -> None:
    """claim_next_run calls persist_failed_generation_record after finalizing a stale run."""
    from unittest.mock import patch  # noqa: PLC0415

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        accepted = await env.accept(params, owner)
        run_id = uuid.UUID(accepted.run_id)

        # Make the run stale with attempts == MAX_ATTEMPTS (will be finalized).
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD_S + 60)
        async with env.sessions() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(
                    status="running",
                    attempts=MAX_ATTEMPTS,
                    claimed_by="dead-host",
                    heartbeat_at=stale_time,
                    started_at=stale_time,
                )
            )
            await session.commit()

        persist_calls: list[dict] = []

        async def _mock_persist(**kwargs: object) -> None:
            persist_calls.append(dict(kwargs))

        with patch(
            "server.generate.run.persist_failed_generation_record",
            side_effect=_mock_persist,
        ):
            result = await claim_next_run(env.sessions, host_id="live-host")

        assert result is None, "exhausted stale run must be finalized, not returned"
        assert len(persist_calls) == 1, (
            f"persist_failed_generation_record must be called once; got {len(persist_calls)}"
        )
        call = persist_calls[0]
        assert call["user_id"] == owner
        assert call["generation_log_id"] == run_id
        assert call["error"] == "recovery_exhausted"

    asyncio.run(_run())
