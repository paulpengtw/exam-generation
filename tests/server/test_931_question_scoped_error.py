"""Issue #931 – question-scoped ERROR events must not mark the whole run failed.

Only batch-scoped ERROR events (no question_id in context) make the run failed.
A run is also failed when ALL questions ended with no final result (has_final=False)
— the conservative all-question-fail policy.  When at least one question delivers
a final result the run is completed even if other questions failed.

These tests run on the default SQLite engine like the other test_908_* tests —
no Postgres required.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import MagicMock

from server.config import ServerConfig
from server.generate.run import (
    ClaimedRun,
    accept_run,
    claim_next_run,
    execute_run,
)
from server.models import Base, GenerationLog, GenerationQuestionState, GenerationRecord, User
from tests.server.generate_test_utils import resolved_generate_params


_MATH_PARAMS: dict[str, Any] = {
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


def _failed_terminal(*, unknown_reason: str = "no final content") -> dict[str, Any]:
    """A minimal question_terminal payload for a question that produced no result."""
    return {
        "termination_reason": "failed",
        "has_final": False,
        "final_revision": None,
        "delivery_status": "unknown",
        "expected": [],
        "delivered": [],
        "missing": [],
        "review": {"status": "unknown", "unknown_reason": unknown_reason},
    }


def _normal_terminal() -> dict[str, Any]:
    """A minimal question_terminal payload for a question that produced a result."""
    return {
        "termination_reason": "normal",
        "has_final": True,
        "final_revision": 1,
        "delivery_status": "complete",
        "expected": [],
        "delivered": [],
        "missing": [],
        "review": {"status": "unknown", "unknown_reason": "review_revision_mismatch"},
    }


class _Env:
    def __init__(self, tmp_path: Path) -> None:
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
        self.sessions = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )
        self.config = ServerConfig(
            api_key="x",
            gemini_api_key="x",
            output_dir=tmp_path / "out",
            data_dir=Path("data"),
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

    async def claim(self) -> ClaimedRun | None:
        return await claim_next_run(self.sessions, host_id="test-host")

    async def run_execute(self, claimed: ClaimedRun) -> None:
        await execute_run(
            claimed,
            app_state=self.app_state,
            config=self.config,
            session_factory=self.sessions,
            host_id="test-host",
        )

    async def get_log(self, run_uuid: uuid.UUID) -> GenerationLog | None:
        async with self.sessions() as session:
            return await session.get(GenerationLog, run_uuid)

    async def get_states(self, run_uuid: uuid.UUID) -> list[GenerationQuestionState]:
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(GenerationQuestionState).where(
                        GenerationQuestionState.generation_log_id == run_uuid
                    )
                )
            ).scalars().all()

    async def get_records(self, run_uuid: uuid.UUID) -> list[GenerationRecord]:
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(GenerationRecord).where(
                        GenerationRecord.generation_log_id == run_uuid
                    )
                )
            ).scalars().all()


# ---------------------------------------------------------------------------
# Test 1: batch-scoped ERROR (no question_id) → run failed
# ---------------------------------------------------------------------------

def test_batch_scoped_error_makes_run_failed(tmp_path: Path) -> None:
    """An ERROR event with no question_id in context (batch-scoped) marks the
    run as failed and writes a failure record."""
    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        accepted = await env.accept(
            resolved_generate_params({**_MATH_PARAMS, "count": 2}), owner
        )
        run_uuid = uuid.UUID(accepted.run_id)
        claimed = await env.claim()
        assert claimed is not None

        async def _batch_error_stream(*_args: Any, **_kwargs: Any):
            # Batch-scoped ERROR: context has no question_id.
            yield {
                "event": "error",
                "context": {"run_id": accepted.run_id, "event_seq": 1},
                "payload": {"code": "batch_generation_failed", "message": "batch failed"},
            }

        with patch("server.generate.run.generate_question_stream", _batch_error_stream):
            await env.run_execute(claimed)

        log = await env.get_log(run_uuid)
        assert log is not None
        assert log.status == "failed", f"expected failed, got {log.status}"

        # All questions must have a termination_reason (via fail_unfinished).
        states = await env.get_states(run_uuid)
        assert len(states) == 2
        for s in states:
            assert s.termination_reason is not None

        # Exactly one failure record must exist.
        records = await env.get_records(run_uuid)
        assert len(records) == 1, f"expected 1 failure record, got {len(records)}"
        assert records[0].status == "failed"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test 2: all questions fail via question-scoped ERROR, none have has_final
# → run failed (conservative all-question-fail)
# ---------------------------------------------------------------------------

def test_all_questions_fail_with_question_scoped_error_makes_run_failed(
    tmp_path: Path,
) -> None:
    """When all questions emit question-scoped ERROR events (question_id present)
    and none deliver a final result (has_final=False in every question_terminal),
    the run is still marked failed — conservative all-question-fail policy."""
    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        accepted = await env.accept(
            resolved_generate_params({**_MATH_PARAMS, "count": 2}), owner
        )
        run_uuid = uuid.UUID(accepted.run_id)
        question_ids = [q["question_id"] for q in accepted.questions]
        claimed = await env.claim()
        assert claimed is not None

        async def _all_question_errors(*_args: Any, **_kwargs: Any):
            for seq, qid in enumerate(question_ids, start=1):
                # Question-scoped ERROR: context carries a question_id.
                yield {
                    "event": "error",
                    "context": {"run_id": accepted.run_id, "event_seq": seq * 2 - 1, "question_id": qid},
                    "payload": {"code": "generation_failed", "message": "q failed"},
                }
                # Real service always follows ERROR with a question_terminal.
                yield {
                    "event": "question_terminal",
                    "context": {"run_id": accepted.run_id, "event_seq": seq * 2, "question_id": qid},
                    "payload": _failed_terminal(),
                }

        with patch("server.generate.run.generate_question_stream", _all_question_errors):
            await env.run_execute(claimed)

        log = await env.get_log(run_uuid)
        assert log is not None
        assert log.status == "failed", (
            f"expected failed (all questions had no final result), got {log.status}"
        )

        states = await env.get_states(run_uuid)
        assert len(states) == 2
        for s in states:
            assert s.termination_reason is not None
            # terminal_json was set by _record_terminal from the QUESTION_TERMINAL event.
            assert s.terminal_json is not None
            assert s.terminal_json.get("has_final") is False

        # A failure record must still be written (run produced no results).
        records = await env.get_records(run_uuid)
        assert len(records) == 1, f"expected 1 failure record, got {len(records)}"
        assert records[0].status == "failed"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test 3: one question succeeds (has_final=True), sibling fails (question-scoped)
# → run completed (at least one final result delivered)
# ---------------------------------------------------------------------------

def test_partial_question_success_makes_run_completed(tmp_path: Path) -> None:
    """When one question delivers a final result (has_final=True) and the other
    fails via a question-scoped ERROR, the run is completed — questions are
    independent and one good result is enough."""
    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        accepted = await env.accept(
            resolved_generate_params({**_MATH_PARAMS, "count": 2}), owner
        )
        run_uuid = uuid.UUID(accepted.run_id)
        q1, q2 = [q["question_id"] for q in accepted.questions]
        claimed = await env.claim()
        assert claimed is not None

        async def _mixed_stream(*_args: Any, **_kwargs: Any):
            # Question 1: succeeds, has_final=True.
            yield {
                "event": "question_terminal",
                "context": {"run_id": accepted.run_id, "event_seq": 1, "question_id": q1},
                "payload": _normal_terminal(),
            }
            # Question 2: fails via question-scoped ERROR, has_final=False.
            yield {
                "event": "error",
                "context": {"run_id": accepted.run_id, "event_seq": 2, "question_id": q2},
                "payload": {"code": "generation_failed", "message": "q2 failed"},
            }
            yield {
                "event": "question_terminal",
                "context": {"run_id": accepted.run_id, "event_seq": 3, "question_id": q2},
                "payload": _failed_terminal(),
            }

        with patch("server.generate.run.generate_question_stream", _mixed_stream):
            await env.run_execute(claimed)

        log = await env.get_log(run_uuid)
        assert log is not None
        assert log.status == "completed", (
            f"expected completed (q1 delivered final result), got {log.status}"
        )

        states = await env.get_states(run_uuid)
        assert len(states) == 2
        state_by_qid = {s.question_id: s for s in states}
        # q1 has has_final=True.
        assert state_by_qid[q1].terminal_json is not None
        assert state_by_qid[q1].terminal_json.get("has_final") is True
        # q2 has has_final=False.
        assert state_by_qid[q2].terminal_json is not None
        assert state_by_qid[q2].terminal_json.get("has_final") is False

        # No failure record: the run completed with partial results.
        records = await env.get_records(run_uuid)
        assert len(records) == 0, (
            f"expected no failure record for completed run, got {len(records)}"
        )

    asyncio.run(_run())
