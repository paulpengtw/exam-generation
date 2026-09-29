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
