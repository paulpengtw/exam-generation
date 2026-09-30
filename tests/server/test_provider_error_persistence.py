"""Server integration test for provider-error persistence (Task 6.1).

Drives an ExchangeRecorder through a real DB write path with an llm_failure
event and asserts the row lands in the DB with ProviderErrorDetail fields.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.generate import persistence
from server.generate.exchange_recorder import ExchangeRecorder
from server.models import Base, GenerationLog, LLMExchange, User


@asynccontextmanager
async def _db_store(tmp_path: Path):
    """Create a real SQLite DB with a GenerationLog row and yield (sessions, log_id)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, log_id = uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(User(id=user_id, email="test@example.com"))
            session.add(GenerationLog(
                id=log_id, user_id=user_id, params_json={}, status="started",
            ))
            await session.commit()
        yield sessions, log_id
    finally:
        await engine.dispose()


def _make_recorder(
    log_id: uuid.UUID,
    loop: asyncio.AbstractEventLoop,
    sessions: async_sessionmaker[AsyncSession],
) -> ExchangeRecorder:
    return persistence.make_exchange_recorder(
        generation_log_id=log_id,
        retention_days=30,
        loop=loop,
        session_factory=sessions,
        next_order=None,
    )


def _anthropic_spend_cap_failure_event(
    *,
    run_id: str | None = "run-test",
    call_id: str | None = "call-test",
    agent: str = "generator",
) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "type": "llm_failure",
        "agent": agent,
        "purpose": "generate",
        "model": "claude-opus-4-6",
        "provider": "anthropic",
        "http_status": 429,
        "provider_error_type": "rate_limit_error",
        "provider_error_code": "enforced_spend_limit_reached",
        "provider_error_status": None,
        "provider_message": "You have reached your API usage limits",
        "request_id": None,
        "retry_after_seconds": None,
        "raw_body_truncated": (
            '{"type":"error","error":'
            '{"type":"rate_limit_error","code":"enforced_spend_limit_reached"}}'
        ),
        "error_type": "RateLimitError",
    }
    if run_id is not None and call_id is not None:
        ev["context"] = {"run_id": run_id, "call_id": call_id}
    return ev


def _request_event(
    *,
    run_id: str | None = "run-test",
    call_id: str | None = "call-test",
    agent: str = "generator",
) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "type": "llm_request",
        "agent": agent,
        "purpose": "generate",
        "model": "claude-opus-4-6",
        "messages": [{"role": "user", "content": "generate a question"}],
        "params": {"max_tokens": 8192},
    }
    if run_id is not None and call_id is not None:
        ev["context"] = {"run_id": run_id, "call_id": call_id}
    return ev


class TestProviderErrorPersistence:
    """Task 6.1 — llm_failure rows land in llm_exchanges table."""

    def test_failure_row_persisted_with_provider_error_code(self, tmp_path: Path) -> None:
        """llm_failure event → one LLMExchange row with provider_error_code in response_body."""

        async def run() -> list[dict[str, Any]]:
            async with _db_store(tmp_path) as (sessions, log_id):
                loop = asyncio.get_running_loop()
                recorder = _make_recorder(log_id, loop, sessions)
                assert recorder is not None

                # Emit request then failure
                await asyncio.to_thread(recorder, _request_event())
                await asyncio.to_thread(recorder, _anthropic_spend_cap_failure_event())
                await recorder.flush()

                # Read back rows directly
                async with sessions() as session:
                    from sqlalchemy import select
                    result = await session.execute(
                        select(LLMExchange).where(LLMExchange.generation_log_id == log_id)
                    )
                    rows = result.scalars().all()
                    return [
                        {
                            "agent": r.agent,
                            "response_body": r.response_body,
                            "request_body": r.request_body,
                            "prompt_tokens": r.prompt_tokens,
                            "completion_tokens": r.completion_tokens,
                        }
                        for r in rows
                    ]

        rows = asyncio.run(run())
        assert len(rows) == 1, f"expected 1 row, got {len(rows)}: {rows}"
        row = rows[0]

        # response_body["error"]["provider_error_code"] == "enforced_spend_limit_reached"
        resp = row["response_body"]
        assert isinstance(resp, dict), f"response_body not dict: {resp!r}"
        err = resp.get("error")
        assert isinstance(err, dict), f"response_body.error not dict: {err!r}"
        assert err.get("provider_error_code") == "enforced_spend_limit_reached", (
            f"provider_error_code mismatch: {err.get('provider_error_code')!r}"
        )

    def test_failure_row_has_populated_request_body(self, tmp_path: Path) -> None:
        """request_body is populated from the matching llm_request event."""

        async def run() -> dict[str, Any] | None:
            async with _db_store(tmp_path) as (sessions, log_id):
                loop = asyncio.get_running_loop()
                recorder = _make_recorder(log_id, loop, sessions)
                assert recorder is not None

                await asyncio.to_thread(recorder, _request_event())
                await asyncio.to_thread(recorder, _anthropic_spend_cap_failure_event())
                await recorder.flush()

                async with sessions() as session:
                    from sqlalchemy import select
                    result = await session.execute(
                        select(LLMExchange).where(LLMExchange.generation_log_id == log_id)
                    )
                    rows = result.scalars().all()
                    if not rows:
                        return None
                    return {
                        "request_body": rows[0].request_body,
                        "prompt_tokens": rows[0].prompt_tokens,
                        "completion_tokens": rows[0].completion_tokens,
                    }

        result = asyncio.run(run())
        assert result is not None, "no row found"
        assert result["request_body"] is not None, "request_body should be populated"
        assert result["prompt_tokens"] is None, "prompt_tokens must be None for failures"
        assert result["completion_tokens"] is None, "completion_tokens must be None for failures"

    def test_no_recorder_when_retention_zero(self, tmp_path: Path) -> None:
        """retention_days=0 → make_exchange_recorder returns None → no rows written."""

        async def run() -> int:
            async with _db_store(tmp_path) as (sessions, log_id):
                loop = asyncio.get_running_loop()
                recorder = persistence.make_exchange_recorder(
                    generation_log_id=log_id,
                    retention_days=0,
                    loop=loop,
                    session_factory=sessions,
                    next_order=None,
                )
                # Should be None — no recorder
                assert recorder is None, "expected None when retention_days=0"

                async with sessions() as session:
                    from sqlalchemy import func, select
                    result = await session.execute(
                        select(func.count()).select_from(LLMExchange)
                    )
                    return result.scalar() or 0

        count = asyncio.run(run())
        assert count == 0
