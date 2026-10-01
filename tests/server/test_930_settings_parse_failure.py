"""Issue #930 – execute_run writes exactly one failure record when params_json fails
GenerateParams.model_validate (schema drift scenario).

These tests run on the default SQLite engine like the other test_908_* tests —
no Postgres required.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.config import ServerConfig
from server.generate.run import (
    ClaimedRun,
    accept_run,
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


async def _run_execute(env: _Env, claimed: ClaimedRun) -> None:
    """Drive execute_run directly, bypassing run_host_loop."""
    await execute_run(
        claimed,
        app_state=env.app_state,
        config=env.config,
        session_factory=env.sessions,
        host_id="test-host",
    )


def test_settings_parse_failure_ends_run_failed_with_one_tombstone(
    tmp_path: Path,
) -> None:
    """A params_json that fails GenerateParams validation ends the run as failed
    and writes exactly one failure record.  Every question must have a
    termination_reason so history views can show something."""
    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        # Accept a well-formed run so the DB row + question states exist.
        accepted = await env.accept(
            resolved_generate_params({**_MATH_PARAMS, "count": 2}), owner
        )
        run_uuid = uuid.UUID(accepted.run_id)

        # Corrupt params_json to simulate schema drift after a deploy.
        # count="not_a_number" causes GenerateParams.model_validate to raise
        # ValidationError because count expects an int.
        bad_params: dict[str, Any] = {"subject": "math", "count": "not_a_number"}
        async with env.sessions() as session:
            await session.execute(
                __import__("sqlalchemy").update(GenerationLog)
                .where(GenerationLog.id == run_uuid)
                .values(params_json=bad_params)
            )
            await session.commit()

        # Claim and execute the run with the corrupted params.
        claimed = ClaimedRun(
            run_id=run_uuid,
            user_id=owner,
            params_json=bad_params,
            attempt=1,
        )
        await _run_execute(env, claimed)

        # Run must be failed.
        async with env.sessions() as session:
            log = await session.get(GenerationLog, run_uuid)
        assert log is not None
        assert log.status == "failed"
        assert log.error  # some generic message; not full validation detail

        # Every question must have a termination_reason.
        async with env.sessions() as session:
            states = (
                await session.execute(
                    select(GenerationQuestionState).where(
                        GenerationQuestionState.generation_log_id == run_uuid
                    )
                )
            ).scalars().all()
        assert len(states) == 2, "expected two question states"
        for state in states:
            assert state.termination_reason is not None, (
                f"question {state.question_id} has no termination_reason"
            )

        # Exactly one failure record.
        async with env.sessions() as session:
            records = (
                await session.execute(
                    select(GenerationRecord).where(
                        GenerationRecord.generation_log_id == run_uuid
                    )
                )
            ).scalars().all()
        assert len(records) == 1, f"expected 1 failure record, got {len(records)}"
        assert records[0].status == "failed"
        assert records[0].subject == "math"

    asyncio.run(_run())


def test_settings_parse_failure_is_idempotent_one_tombstone(tmp_path: Path) -> None:
    """Writing the failure record a second time (duplicate run) still leaves
    exactly one record — the unique constraint on (generation_log_id, question_id)
    absorbs the second insert."""
    from server.generate.persistence import persist_failed_generation_record

    env = _Env(tmp_path)

    async def _run() -> None:
        owner = await env.setup()
        accepted = await env.accept(
            resolved_generate_params({**_MATH_PARAMS, "count": 1}), owner
        )
        run_uuid = uuid.UUID(accepted.run_id)

        # Write the failure record twice (simulates running the failure path twice).
        raw: dict[str, Any] = {"subject": "math", "count": "not_a_number"}
        await persist_failed_generation_record(
            user_id=owner,
            generation_log_id=run_uuid,
            subject=raw.get("subject", ""),
            params_json_raw=raw,
            error="run_settings_parse_failure",
            session_factory=env.sessions,
        )
        await persist_failed_generation_record(
            user_id=owner,
            generation_log_id=run_uuid,
            subject=raw.get("subject", ""),
            params_json_raw=raw,
            error="run_settings_parse_failure",
            session_factory=env.sessions,
        )

        async with env.sessions() as session:
            records = (
                await session.execute(
                    select(GenerationRecord).where(
                        GenerationRecord.generation_log_id == run_uuid
                    )
                )
            ).scalars().all()
        assert len(records) == 1, f"expected 1 record after two identical writes, got {len(records)}"

    asyncio.run(_run())
