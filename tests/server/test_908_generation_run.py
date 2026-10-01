"""Issue #908 – the detached 生成執行: accept, execute on a host loop, read back.

These tests drive the run module's entry points (``accept_run``, ``read_run``,
``run_host_loop``) against a file-backed SQLite database.  Generation itself is
stubbed at the subject-spec seam (``subjects=``), the same seam the v2 fixture
tests use, so the real ``generate_question_stream`` bus, worker threads,
save-before-result and terminal logic all run.
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.config import ServerConfig
from server.generate.run import (
    accept_run,
    claim_next_run,
    read_run,
    run_host_loop,
)
from server.generate.subjects import SUBJECTS
from server.models import Base, GenerationLog, GenerationQuestionState, GenerationRecord, User
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


class _FakeClient:
    """LLMClient stand-in that forwards emitted events to the installed observer."""

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
    client.emit(
        {"type": "stage", "agent": "generator", "stage": "llm_generate",
         "status": "end", "ts": time.time()}
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

    async def setup(self) -> tuple[uuid.UUID, uuid.UUID]:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        owner, other = uuid.uuid4(), uuid.uuid4()
        async with self.sessions() as session:
            session.add_all([
                User(id=owner, email="owner@example.com"),
                User(id=other, email="other@example.com"),
            ])
            await session.commit()
        return owner, other

    async def accept(self, params: Any, user_id: uuid.UUID) -> Any:
        async with self.sessions() as session:
            return await accept_run(params, user_id, session=session)

    async def read(self, run_id: str, user_id: uuid.UUID) -> Any:
        async with self.sessions() as session:
            return await read_run(run_id, user_id, session=session, config=self.config)

    async def run_until_idle(self, do_generate: Any, *, timeout: float = 20.0) -> None:
        """Run the host loop until no run is queued or running, then stop it."""
        stop = asyncio.Event()
        loop_task = asyncio.create_task(
            run_host_loop(
                stop,
                app_state=self.app_state,
                config=self.config,
                session_factory=self.sessions,
                client_factory=_FakeClient,
                subjects=_spec(do_generate),
                idle_interval=0.05,
            )
        )
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                async with self.sessions() as session:
                    pending = (
                        await session.execute(
                            select(GenerationLog.id).where(
                                GenerationLog.status.in_(("queued", "running"))
                            )
                        )
                    ).first()
                if pending is None:
                    break
            else:
                raise AssertionError("runs did not finish in time")
        finally:
            stop.set()
            await asyncio.wait_for(loop_task, timeout=timeout)


@pytest.fixture(autouse=True)
def _quiet_outcome_metric():
    with patch("server.observability.record_generation_outcome"):
        yield


def test_accept_run_records_queued_run_and_waiting_questions(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    async def _run() -> None:
        owner, _ = await env.setup()
        accepted = await env.accept(resolved_generate_params({**_MATH, "count": 3}), owner)
        assert accepted.total == 3
        assert [q["index"] for q in accepted.questions] == [0, 1, 2]
        assert [q["question_id"] for q in accepted.questions] == [
            f"q_{accepted.run_id}_{n:03d}" for n in (1, 2, 3)
        ]
        assert accepted.to_response() == {
            "run_id": accepted.run_id,
            "protocol_version": 3,
            "total": 3,
            "questions": accepted.questions,
        }

        async with env.sessions() as session:
            log = await session.get(GenerationLog, uuid.UUID(accepted.run_id))
            states = (
                await session.execute(
                    select(GenerationQuestionState)
                    .where(GenerationQuestionState.generation_log_id == log.id)
                    .order_by(GenerationQuestionState.index)
                )
            ).scalars().all()
        assert log.status == "queued"
        assert log.params_json["count"] == 3
        assert [s.processing for s in states] == ["waiting"] * 3
        assert [s.termination_reason for s in states] == [None] * 3

    asyncio.run(_run())


def test_read_run_is_owner_only_and_shows_waiting_questions(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    async def _run() -> None:
        owner, other = await env.setup()
        accepted = await env.accept(resolved_generate_params({**_MATH, "count": 2}), owner)
        snapshot = await env.read(accepted.run_id, owner)
        assert snapshot is not None
        assert snapshot["run_id"] == accepted.run_id
        assert snapshot["status"] == "queued"
        assert snapshot["total"] == 2
        assert [q["processing"] for q in snapshot["questions"]] == ["waiting", "waiting"]
        assert all(q["result"] is None for q in snapshot["questions"])

        assert await env.read(accepted.run_id, other) is None
        assert await env.read("not-a-uuid", owner) is None

    asyncio.run(_run())


def test_host_loop_executes_run_and_persists_outcomes(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    async def _run() -> None:
        owner, _ = await env.setup()
        accepted = await env.accept(resolved_generate_params({**_MATH, "count": 2}), owner)
        await env.run_until_idle(_ok_generate)

        snapshot = await env.read(accepted.run_id, owner)
        assert snapshot["status"] == "completed"
        assert snapshot["completed_at"] is not None
        for question in snapshot["questions"]:
            assert question["processing"] == "ended"
            assert question["termination_reason"] == "normal"
            assert question["terminal"]["has_final"] is True
            assert question["terminal"]["review"]["status"] == "skipped"
            assert question["result"]["question"]["id"] == question["question_id"]
            assert question["result"]["record_id"]

        async with env.sessions() as session:
            log = await session.get(GenerationLog, uuid.UUID(accepted.run_id))
        assert log.attempts == 1
        assert log.claimed_by

    asyncio.run(_run())


def test_host_loop_records_current_step_while_running(tmp_path: Path) -> None:
    env = _Env(tmp_path)
    observed: list[Any] = []
    release = threading.Event()

    def _slow_generate(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
        client: _FakeClient = kwargs["client"]
        client.emit(
            {"type": "stage", "agent": "verifier", "stage": "verify",
             "status": "start", "ts": time.time()}
        )
        assert release.wait(timeout=10)
        return _question(kwargs["question_id"])

    async def _run() -> None:
        owner, _ = await env.setup()
        accepted = await env.accept(resolved_generate_params({**_MATH, "count": 1}), owner)
        runner = asyncio.create_task(env.run_until_idle(_slow_generate))
        try:
            for _ in range(200):
                await asyncio.sleep(0.05)
                snapshot = await env.read(accepted.run_id, owner)
                question = snapshot["questions"][0]
                if question["current_step"] == "verify":
                    observed.append(snapshot)
                    break
        finally:
            release.set()
            await runner

    asyncio.run(_run())
    assert observed, "current_step was never persisted as verify"
    assert observed[0]["status"] == "running"
    assert observed[0]["questions"][0]["processing"] == "running"


def test_one_failed_question_does_not_stop_its_sibling(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    def _half_fails(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
        if kwargs["question_id"].endswith("_001"):
            raise RuntimeError("provider exploded")
        return _question(kwargs["question_id"])

    async def _run() -> None:
        owner, _ = await env.setup()
        accepted = await env.accept(resolved_generate_params({**_MATH, "count": 2}), owner)
        await env.run_until_idle(_half_fails)
        snapshot = await env.read(accepted.run_id, owner)
        first, second = snapshot["questions"]
        assert first["termination_reason"] == "failed"
        assert first["error"]
        assert first["result"] is None
        assert second["termination_reason"] == "normal"
        assert second["result"] is not None

    asyncio.run(_run())


def test_claim_runs_one_run_per_teacher_at_a_time(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    async def _run() -> None:
        owner, other = await env.setup()
        params = resolved_generate_params({**_MATH, "count": 1})
        first = await env.accept(params, owner)
        second = await env.accept(params, owner)
        others = await env.accept(params, other)

        claimed = await claim_next_run(env.sessions, host_id="host-a")
        assert claimed is not None and str(claimed.run_id) == first.run_id
        claimed = await claim_next_run(env.sessions, host_id="host-a")
        assert claimed is not None and str(claimed.run_id) == others.run_id
        assert await claim_next_run(env.sessions, host_id="host-a") is None

        async with env.sessions() as session:
            waiting = await session.get(GenerationLog, uuid.UUID(second.run_id))
        assert waiting.status == "queued"

    asyncio.run(_run())


def test_a_crashed_execution_ends_unfinished_questions_as_failed(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    async def _run() -> None:
        owner, _ = await env.setup()
        accepted = await env.accept(resolved_generate_params({**_MATH, "count": 2}), owner)

        async def _broken_stream(*_args: Any, **_kwargs: Any):
            raise RuntimeError("bus broke")
            yield {}  # pragma: no cover

        with patch("server.generate.run.generate_question_stream", _broken_stream):
            await env.run_until_idle(_ok_generate)

        snapshot = await env.read(accepted.run_id, owner)
        assert snapshot["status"] == "failed"
        for question in snapshot["questions"]:
            assert question["processing"] == "ended"
            assert question["termination_reason"] == "failed"
            assert question["terminal"]["unknown_reason"]

    asyncio.run(_run())


def test_host_loop_stops_cleanly_when_idle(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    async def _run() -> None:
        await env.setup()
        stop = asyncio.Event()
        task = asyncio.create_task(
            run_host_loop(
                stop,
                app_state=env.app_state,
                config=env.config,
                session_factory=env.sessions,
                idle_interval=0.05,
            )
        )
        await asyncio.sleep(0.2)
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Ported from test_generate_routes.py (social-studies seam, #908 execute_run)
# ---------------------------------------------------------------------------

async def _run_ss_until_idle(env: _Env, subjects: dict, *, timeout: float = 20.0) -> None:
    """Run the host loop with custom subjects until no run is queued or running."""
    stop = asyncio.Event()
    loop_task = asyncio.create_task(
        run_host_loop(
            stop,
            app_state=env.app_state,
            config=env.config,
            session_factory=env.sessions,
            client_factory=_FakeClient,
            subjects=subjects,
            idle_interval=0.05,
        )
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        async with env.sessions() as session:
            pending = (
                await session.execute(
                    select(GenerationLog.id).where(
                        GenerationLog.status.in_(("queued", "running"))
                    )
                )
            ).first()
        if pending is None:
            break
    else:
        stop.set()
        await asyncio.wait_for(loop_task, timeout=5.0)
        raise AssertionError("runs did not finish in time")
    stop.set()
    await asyncio.wait_for(loop_task, timeout=5.0)


def test_ss_persists_one_failed_record_after_prior_success(tmp_path: Path) -> None:
    """Port of test_generate_route_persists_one_failed_record_after_prior_success.

    Issue #931: when q1 succeeds and q2 fails via a question-scoped error,
    the run is *completed* (at least one final result), not failed.  Only q1's
    completed GenerationRecord is written; no batch tombstone is created.
    The question states confirm q1 normal and q2 failed.
    """
    from src.social_studies.schemas import ExamQuestion

    env = _Env(tmp_path)
    calls = 0

    def _fake_do(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("scripted LLM failure")
        return ExamQuestion(
            id=kwargs["question_id"],
            核心問題="先完成的核心問題",
            文本="先完成的文本",
            subquestions=[],
            情境=[c.value for c in rng_params.情境],
            題型種類=rng_params.題型種類.value,
            題型=rng_params.題型[0].value,
            題目=["先完成的題目"],
            正確解題分析=["解析"],
        )

    fake_spec = {
        "social_studies": dataclasses.replace(SUBJECTS["social_studies"], do_generate=_fake_do),
    }

    async def _run() -> None:
        owner, _ = await env.setup()
        accepted = await env.accept(
            resolved_generate_params(
                {"subject": "social_studies", "count": 2, "seed": 41, "skip_verify": True}
            ),
            owner,
        )
        await _run_ss_until_idle(env, fake_spec)

        async with env.sessions() as session:
            rows = list(
                (
                    await session.execute(
                        select(GenerationRecord).order_by(GenerationRecord.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )

        # Issue #931: partial success → run completed; only q1's record exists.
        assert len(rows) == 1, f"expected 1 record (q1 success only), got {len(rows)}: {[r.status for r in rows]}"
        assert rows[0].status == "completed"

        # Check the GenerationLog directly for the run status.
        async with env.sessions() as session:
            log = await session.get(GenerationLog, uuid.UUID(accepted.run_id))
        assert log is not None
        assert log.status == "completed", f"expected completed, got {log.status}"

        # Both question states must have a termination_reason.
        async with env.sessions() as session:
            states = (
                await session.execute(
                    select(GenerationQuestionState).where(
                        GenerationQuestionState.generation_log_id == uuid.UUID(accepted.run_id)
                    )
                )
            ).scalars().all()
        assert len(states) == 2
        reasons = {s.termination_reason for s in states}
        assert "normal" in reasons, f"expected a normal terminal; got {reasons}"
        assert "failed" in reasons, f"expected a failed terminal; got {reasons}"

    asyncio.run(_run())


def test_ss_defers_failed_policy_tombstone_until_workers_finish(tmp_path: Path) -> None:
    """Port of test_generate_route_defers_failed_policy_tombstone_until_workers_finish.

    A failed tombstone includes policy events emitted by slower sibling workers.
    Uses execute_run path instead of SSE route.

    Issue #931: the tombstone is only written when ALL questions fail (no has_final=True).
    This scenario uses two failing questions so the conservative all-question-fail
    policy still triggers a tombstone, preserving the deferred-trail ordering test.
    """
    import datetime

    from src.common.figure_policy_trail import FigurePolicySpecEntry

    env = _Env(tmp_path)
    failure_started = threading.Event()

    def _fake_do(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
        question_id = kwargs["question_id"]
        kwargs["on_figure_policy_entry"](
            FigurePolicySpecEntry(
                question_id=question_id,
                label="題幹",
                effective_figure_kind="地圖",
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
        )
        if question_id.endswith("_001"):
            failure_started.set()
            raise RuntimeError("scripted policy failure q1")

        # q2 waits for q1 to fail, emits a late trail entry, then also fails.
        # This proves the tombstone is not written until q2 finishes.
        assert failure_started.wait(timeout=5)
        time.sleep(0.25)
        kwargs["on_figure_policy_entry"](
            FigurePolicySpecEntry(
                question_id=question_id,
                label="小題 1",
                effective_figure_kind="統計圖",
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
        )
        raise RuntimeError("scripted policy failure q2")

    fake_spec = {
        "social_studies": dataclasses.replace(SUBJECTS["social_studies"], do_generate=_fake_do),
    }

    async def _run() -> None:
        owner, _ = await env.setup()
        await env.accept(
            resolved_generate_params(
                {"subject": "social_studies", "count": 2, "seed": 41, "skip_verify": True}
            ),
            owner,
        )
        await _run_ss_until_idle(env, fake_spec)

        async with env.sessions() as session:
            rows = list((await session.execute(select(GenerationRecord))).scalars().all())

        failed = next(r for r in rows if r.status == "failed")
        assert failed.figure_policy_trail_json is not None
        assert len(failed.figure_policy_trail_json) == 3
        assert len({entry["question_id"] for entry in failed.figure_policy_trail_json}) == 2
        assert {entry["label"] for entry in failed.figure_policy_trail_json} == {"題幹", "小題 1"}

    asyncio.run(_run())


def test_host_loop_respects_max_concurrent_runs(tmp_path: Path) -> None:
    """run_host_loop with max_concurrent_runs=2 never starts more than 2 runs simultaneously.

    Three runs from three distinct teachers (so the one-run-per-teacher claim
    rule cannot artificially cap concurrency) are queued.  Each do_generate
    holds for a short interval so we can measure how many are in-flight at
    once.  With max_concurrent_runs=2 the observed peak must be ≤ 2.
    """
    env = _Env(tmp_path)

    async def _run() -> None:
        owner1, owner2 = await env.setup()
        owner3 = uuid.uuid4()
        async with env.sessions() as session:
            session.add(User(id=owner3, email="owner3@test.com"))
            await session.commit()

        params = resolved_generate_params({**_MATH, "count": 1})
        for owner in [owner1, owner2, owner3]:
            await env.accept(params, owner)

        concurrent = 0
        max_concurrent = 0
        lock = threading.Lock()

        def _slow_generate(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
            nonlocal concurrent, max_concurrent
            client: _FakeClient = kwargs["client"]
            client.emit(
                {"type": "stage", "agent": "generator", "stage": "llm_generate",
                 "status": "start", "ts": time.time()}
            )
            with lock:
                concurrent += 1
                if concurrent > max_concurrent:
                    max_concurrent = concurrent
            # Hold for a moment so the host loop can (fail to) pick up a third run.
            time.sleep(0.25)
            with lock:
                concurrent -= 1
            client.emit(
                {"type": "stage", "agent": "generator", "stage": "llm_generate",
                 "status": "end", "ts": time.time()}
            )
            return _question(kwargs["question_id"])

        stop = asyncio.Event()
        loop_task = asyncio.create_task(
            run_host_loop(
                stop,
                app_state=env.app_state,
                config=env.config,
                session_factory=env.sessions,
                client_factory=_FakeClient,
                subjects=_spec(_slow_generate),
                idle_interval=0.05,
                max_concurrent_runs=2,
            )
        )
        # Wait for all 3 runs to complete.
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            async with env.sessions() as session:
                pending = (
                    await session.execute(
                        select(GenerationLog.id).where(
                            GenerationLog.status.in_(("queued", "running"))
                        )
                    )
                ).first()
            if pending is None:
                break
        else:
            raise AssertionError("runs did not finish in time")
        stop.set()
        await asyncio.wait_for(loop_task, timeout=20.0)

        assert max_concurrent <= 2, (
            f"Expected max 2 concurrent runs but observed {max_concurrent}"
        )

    asyncio.run(_run())
