"""Tests for issue #946 gap fixes in run.py and service.py.

Covers three gaps:
1. Run-level failure emits an SSE `error` event (code ``stream_failed``) with
   a taxonomy ``failure_class`` to live observers before the ``done`` sentinel.
2. ``failure_class`` is persisted on ``generation_logs`` and returned by the
   snapshot/read_run API; the migration adds a nullable ``failure_class`` column.
3. ``started_invalid`` in service.py carries ``failure_class="unknown"``.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql.dml import Update

from server.config import ServerConfig
from server.generate.run import (
    _live_observers,
    _QuestionStateRecorder,
    accept_run,
    claim_next_run,
    execute_run,
    read_run,
)
from server.models import Base, GenerationLog, GenerationQuestionState, LLMExchange, User
from tests.server.generate_test_utils import resolved_generate_params

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_BASE_PARAMS: dict[str, Any] = {
    "subject": "math",
    "seed": 77,
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
    "count": 1,
}


@pytest.fixture(autouse=True)
def _clean_registry():
    _live_observers.clear()
    yield
    _live_observers.clear()


@pytest.fixture(autouse=True)
def _quiet_metric():
    with patch("server.observability.record_generation_outcome"):
        yield


def _app_state() -> Any:
    state = MagicMock()
    state.renderer_pool = None
    return state


def _server_config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(
        api_key="x",
        gemini_api_key="x",
        output_dir=tmp_path / "out",
        data_dir=Path("data"),
    )


def test_question_recorder_coalesce_is_safe_with_loaded_state(tmp_path: Path) -> None:
    """A loaded ORM state must not make the first failure class update unevaluable."""
    async def _run() -> None:
        claimed, sessions, engine = await _setup_db_and_run(tmp_path, "loaded_state.db")
        session = sessions()
        synchronization_modes: list[Any] = []

        class _EvaluateDefaultSession:
            def __init__(self, wrapped: AsyncSession) -> None:
                self._wrapped = wrapped

            async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
                if isinstance(statement, Update):
                    mode = statement.get_execution_options().get("synchronize_session")
                    synchronization_modes.append(mode)
                    if mode is None:
                        statement = statement.execution_options(synchronize_session="evaluate")
                return await self._wrapped.execute(statement, *args, **kwargs)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._wrapped, name)

        evaluate_session = _EvaluateDefaultSession(session)

        @asynccontextmanager
        async def _session_scope():
            yield evaluate_session

        try:
            qid = f"q_{claimed.run_id}_001"
            state = (
                await session.execute(
                    select(GenerationQuestionState).where(
                        GenerationQuestionState.generation_log_id == claimed.run_id,
                        GenerationQuestionState.question_id == qid,
                    )
                )
            ).scalar_one()
            assert state.failure_class is None

            recorder = _QuestionStateRecorder(claimed.run_id, _session_scope)
            await recorder._update_unfinished(qid, failure_class="rate_limited")
            await recorder._update_unfinished(qid, failure_class="timeout")
            await session.refresh(state)

            assert synchronization_modes == [False, False]
            assert state.failure_class == "rate_limited"
        finally:
            await session.rollback()
            await session.close()
            await engine.dispose()

    asyncio.run(asyncio.wait_for(_run(), timeout=40.0))


async def _setup_db_and_run(
    tmp_path: Path, db_name: str = "test.db"
) -> tuple[Any, Any, Any]:
    """Create DB, accept a run, claim it; return (claimed, sessions, engine)."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / db_name}"
    engine = create_async_engine(db_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    owner = uuid.uuid4()
    async with sessions() as session:
        session.add(User(id=owner, email="fc_test@example.com"))
        await session.commit()

    params = resolved_generate_params(_BASE_PARAMS)
    async with sessions() as session:
        await accept_run(params, owner, session=session)

    claimed = await claim_next_run(sessions, host_id="fc-test-host")
    assert claimed is not None
    return claimed, sessions, engine


# ---------------------------------------------------------------------------
# Gap 1 – run-level failure emits error event with failure_class before done
# ---------------------------------------------------------------------------


def test_run_level_exception_publishes_error_event_before_done(tmp_path: Path) -> None:
    """Run-level exception (outside per-question workers) → live observers get
    an error event (code stream_failed, taxonomy failure_class) BEFORE done.

    We patch generate_question_stream to raise RuntimeError directly so the
    run-level ``except Exception as exc`` block (not the per-question worker) is hit.

    Issue #946 gap 1.
    """
    async def _run() -> None:
        claimed, sessions, engine = await _setup_db_and_run(tmp_path)
        run_str_id = str(claimed.run_id)

        observer_queue: asyncio.Queue = asyncio.Queue(maxsize=512)
        _live_observers[run_str_id] = [observer_queue]

        async def _failing_stream(*args: Any, **kwargs: Any):
            from src.llm_client import ProviderFailureContext

            exc = RuntimeError("injected stream-level failure")
            exc._provider_failure_context = ProviderFailureContext(  # type: ignore[attr-defined]
                provider="gemini",
                model="gemini-3.1-pro-preview",
                tier="execute",
                http_status=504,
                retry_after_seconds=8,
            )
            raise exc
            yield  # make it an async generator

        with patch(
            "server.generate.run.generate_question_stream",
            new=_failing_stream,
        ):
            await asyncio.wait_for(
                execute_run(
                    claimed,
                    app_state=_app_state(),
                    config=_server_config(tmp_path),
                    session_factory=sessions,
                    host_id="fc-test-host",
                    client_factory=None,
                    subjects=None,
                ),
                timeout=30.0,
            )

        events: list[dict] = []
        while not observer_queue.empty():
            events.append(observer_queue.get_nowait())

        event_names = [e.get("event") for e in events]
        assert "error" in event_names, f"no error event; events={event_names}"
        assert "done" in event_names, f"no done event; events={event_names}"

        error_idx = event_names.index("error")
        done_idx = event_names.index("done")
        assert error_idx < done_idx, (
            f"error ({error_idx}) must come before done ({done_idx})"
        )

        error_event = events[error_idx]
        payload = error_event.get("payload") or {}
        assert isinstance(payload, dict), f"payload must be dict: {payload}"
        assert payload.get("code") == "stream_failed", (
            f"expected code=stream_failed, got {payload.get('code')!r}"
        )
        fc = payload.get("failure_class")
        assert isinstance(fc, str) and fc, (
            f"failure_class must be a non-empty string, got {fc!r}"
        )
        _TAXONOMY = {
            "auth_config", "quota_billing_exhausted", "rate_limited", "overloaded",
            "timeout", "connection", "context_length", "content_filtered",
            "malformed_response", "unknown",
        }
        assert fc in _TAXONOMY, f"failure_class={fc!r} not in taxonomy"
        assert payload.get("provider") == "gemini"
        assert payload.get("model") == "gemini-3.1-pro-preview"
        assert payload.get("tier") == "execute"
        assert payload.get("http_status") == 504
        assert payload.get("retry_after_seconds") == 8

        await engine.dispose()

    asyncio.run(asyncio.wait_for(_run(), timeout=40.0))


# ---------------------------------------------------------------------------
# Gap 2 – failure_class persisted and returned by read_run
# ---------------------------------------------------------------------------


def test_run_level_failure_class_persisted(tmp_path: Path) -> None:
    """After a run-level exception, failure_class is persisted to generation_logs."""
    async def _run() -> None:
        claimed, sessions, engine = await _setup_db_and_run(tmp_path, "persist.db")
        run_id = claimed.run_id

        async def _failing_stream(*args: Any, **kwargs: Any):
            raise RuntimeError("injected stream-level failure")
            yield

        with patch("server.generate.run.generate_question_stream", new=_failing_stream):
            await asyncio.wait_for(
                execute_run(
                    claimed,
                    app_state=_app_state(),
                    config=_server_config(tmp_path),
                    session_factory=sessions,
                    host_id="fc-test-host",
                    client_factory=None,
                    subjects=None,
                ),
                timeout=30.0,
            )

        async with sessions() as session:
            log = (
                await session.execute(
                    select(GenerationLog).where(GenerationLog.id == run_id)
                )
            ).scalar_one_or_none()
            assert log is not None
            assert log.status == "failed"
            fc = log.failure_class
            assert isinstance(fc, str) and fc, (
                f"failure_class not persisted, got {fc!r}"
            )

        await engine.dispose()

    asyncio.run(asyncio.wait_for(_run(), timeout=40.0))


def test_per_question_error_failure_class_persisted(tmp_path: Path) -> None:
    """When a per-question error event carries failure_class, the first one
    is persisted to generation_logs.failure_class.

    We patch generate_question_stream to yield an error event with failure_class
    (simulating what service.py does for a per-question worker failure) and then
    yield done.
    """
    async def _run() -> None:
        claimed, sessions, engine = await _setup_db_and_run(tmp_path, "pqerr.db")
        run_id = claimed.run_id

        async def _error_then_done_stream(*args: Any, **kwargs: Any):
            yield {
                "event": "error",
                "context": {"run_id": str(run_id), "event_seq": 1},
                "payload": {
                    "code": "generation_failed",
                    "message": "Rate limit hit",
                    "failure_class": "rate_limited",
                },
            }
            yield {"event": "done", "payload": {}}

        with patch(
            "server.generate.run.generate_question_stream",
            new=_error_then_done_stream,
        ):
            await asyncio.wait_for(
                execute_run(
                    claimed,
                    app_state=_app_state(),
                    config=_server_config(tmp_path),
                    session_factory=sessions,
                    host_id="fc-test-host",
                    client_factory=None,
                    subjects=None,
                ),
                timeout=30.0,
            )

        async with sessions() as session:
            log = (
                await session.execute(
                    select(GenerationLog).where(GenerationLog.id == run_id)
                )
            ).scalar_one_or_none()
            assert log is not None
            assert log.status == "failed"
            fc = log.failure_class
            assert fc == "rate_limited", (
                f"expected failure_class=rate_limited from per-question error, got {fc!r}"
            )

        await engine.dispose()

    asyncio.run(asyncio.wait_for(_run(), timeout=40.0))


def test_per_question_failure_class_round_trips_through_snapshot(tmp_path: Path) -> None:
    """A question-scoped generation failure survives recorder persistence and read_run."""
    async def _run() -> None:
        claimed, sessions, engine = await _setup_db_and_run(tmp_path, "question_snapshot.db")
        run_id = claimed.run_id
        question_id = f"q_{run_id}_001"

        async def _error_then_done_stream(*args: Any, **kwargs: Any):
            yield {
                "event": "error",
                "context": {
                    "run_id": str(run_id),
                    "question_id": question_id,
                    "event_seq": 1,
                },
                "payload": {
                    "code": "generation_failed",
                    "message": "provider message must remain an error detail",
                    "failure_class": "rate_limited",
                },
            }
            yield {"event": "done", "payload": {}}

        with patch(
            "server.generate.run.generate_question_stream",
            new=_error_then_done_stream,
        ):
            await asyncio.wait_for(
                execute_run(
                    claimed,
                    app_state=_app_state(),
                    config=_server_config(tmp_path),
                    session_factory=sessions,
                    host_id="fc-test-host",
                    client_factory=None,
                    subjects=None,
                ),
                timeout=30.0,
            )

        async with sessions() as session:
            state = (
                await session.execute(
                    select(GenerationQuestionState).where(
                        GenerationQuestionState.generation_log_id == run_id,
                        GenerationQuestionState.question_id == question_id,
                    )
                )
            ).scalar_one()
            snapshot = await read_run(
                run_id,
                claimed.user_id,
                session=session,
                config=_server_config(tmp_path),
            )

        assert state.failure_class == "rate_limited"
        assert snapshot is not None
        assert snapshot["status"] == "failed"
        assert snapshot["questions"][0]["failure_class"] == "rate_limited"
        assert snapshot["questions"][0]["error"] == (
            "provider message must remain an error detail"
        )
        assert snapshot["questions"][0]["failure_class"] != snapshot["questions"][0]["error"]

        await engine.dispose()

    asyncio.run(asyncio.wait_for(_run(), timeout=40.0))


def test_read_run_returns_failure_class(tmp_path: Path) -> None:
    """read_run includes failure_class in its response dict when set."""
    async def _run() -> None:
        claimed, sessions, engine = await _setup_db_and_run(tmp_path, "readrun.db")
        run_id = claimed.run_id
        owner_id = claimed.user_id

        async def _failing_stream(*args: Any, **kwargs: Any):
            raise RuntimeError("injected stream-level failure")
            yield

        with patch("server.generate.run.generate_question_stream", new=_failing_stream):
            await asyncio.wait_for(
                execute_run(
                    claimed,
                    app_state=_app_state(),
                    config=_server_config(tmp_path),
                    session_factory=sessions,
                    host_id="fc-test-host",
                    client_factory=None,
                    subjects=None,
                ),
                timeout=30.0,
            )

        async with sessions() as session:
            result = await read_run(
                run_id, owner_id, session=session, config=_server_config(tmp_path)
            )
        assert result is not None
        assert result["status"] == "failed"
        assert "failure_class" in result, (
            f"failure_class missing from read_run result: {list(result.keys())}"
        )
        fc = result["failure_class"]
        assert isinstance(fc, str) and fc, (
            f"failure_class must be non-empty string: {fc!r}"
        )

        await engine.dispose()

    asyncio.run(asyncio.wait_for(_run(), timeout=40.0))


def test_read_run_returns_safe_provider_failure_context(tmp_path: Path) -> None:
    """A failed run exposes provider context without persisted sensitive detail."""
    async def _run() -> None:
        claimed, sessions, engine = await _setup_db_and_run(tmp_path, "context.db")
        async with sessions() as session:
            log = (
                await session.execute(
                    select(GenerationLog).where(GenerationLog.id == claimed.run_id)
                )
            ).scalar_one()
            log.status = "failed"
            log.failure_class = "rate_limited"
            session.add(LLMExchange(
                generation_log_id=claimed.run_id,
                exchange_order=1,
                agent="generator",
                purpose="generate",
                request_body={"messages": [{"role": "user", "content": "secret prompt"}]},
                response_body={"error": {
                    "provider": "gemini",
                    "model": "gemini-3.1-pro-preview",
                    "tier": "execute",
                    "http_status": 429,
                    "retry_after_seconds": 12,
                    "provider_message": "secret provider response",
                    "raw_body_truncated": "secret raw body",
                }},
                model_used="gemini-3.1-pro-preview",
            ))
            await session.commit()

            result = await read_run(
                claimed.run_id,
                claimed.user_id,
                session=session,
                config=_server_config(tmp_path),
            )

        assert result is not None
        assert result["failure_context"] == {
            "provider": "gemini",
            "model": "gemini-3.1-pro-preview",
            "tier": "execute",
            "http_status": 429,
            "retry_after_seconds": 12,
        }
        assert "secret" not in str(result["failure_context"])
        await engine.dispose()

    asyncio.run(asyncio.wait_for(_run(), timeout=40.0))


# ---------------------------------------------------------------------------
# Gap 3 – started_invalid carries failure_class="unknown"
# ---------------------------------------------------------------------------

def test_started_invalid_carries_unknown_failure_class() -> None:
    """build_sse_error call for started_invalid must include failure_class='unknown'.

    Issue #946 gap 3.  Direct unit test.
    """
    from server.generate.models import build_sse_error

    payload = build_sse_error(
        "started_invalid",
        "generation manifest validation failed",
        failure_class="unknown",
    )
    assert payload["code"] == "started_invalid"
    assert payload["failure_class"] == "unknown"


def test_started_invalid_event_in_stream_carries_failure_class(tmp_path: Path) -> None:
    """The SSE error event for started_invalid includes failure_class=unknown.

    Patches StartedPayload.model_validate to raise pydantic ValidationError so
    the started_invalid path in generate_question_stream is hit.
    """
    from pydantic import ValidationError as PydanticValidationError

    from server.generate.event_protocol import StartedPayload
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS as _SUBJECTS

    params = resolved_generate_params(_BASE_PARAMS)
    config = _server_config(tmp_path)

    def _raise_validation_error(*args: Any, **kwargs: Any) -> Any:
        # Create a real pydantic ValidationError without calling model_validate again.
        from pydantic import TypeAdapter
        try:
            TypeAdapter(StartedPayload).validate_python({})
        except PydanticValidationError as exc:
            raise exc
        raise PydanticValidationError.from_exception_data("StartedPayload", [])

    async def _collect() -> list[dict]:
        events: list[dict] = []
        with patch(
            "server.generate.service.StartedPayload.model_validate",
            side_effect=_raise_validation_error,
        ):
            async for ev in generate_question_stream(
                params,
                config,
                _app_state(),
                user_id=uuid.uuid4(),
                generation_log_id=uuid.uuid4(),
                subjects=_SUBJECTS,
                session_factory=None,
                client_factory=None,
                confirmed_cancel_event=None,
                attempt=1,
            ):
                events.append(ev)
        return events

    events = asyncio.run(_collect())
    error_events = [e for e in events if e.get("event") == "error"]
    assert error_events, (
        f"no error event emitted; events={[e.get('event') for e in events]}"
    )
    payload = error_events[0].get("payload") or {}
    assert payload.get("failure_class") == "unknown", (
        f"expected failure_class=unknown, got {payload.get('failure_class')!r}"
    )
    assert payload.get("code") == "started_invalid", (
        f"expected code=started_invalid, got {payload.get('code')!r}"
    )


# ---------------------------------------------------------------------------
# Fix: error and failure_class must come from the same (first) error event
# ---------------------------------------------------------------------------


def test_two_error_events_persist_first_message_and_first_failure_class(
    tmp_path: Path,
) -> None:
    """When two question-scoped error events arrive with different messages and
    different failure_class values, both persisted fields must belong to the
    FIRST event — they must not be mismatched (last message with first class).

    This is the regression test for the issue where ``error`` was overwritten by
    every error event (keeping LAST) while ``failure_class`` was captured only
    from the first, so after a reconnect the snapshot could show one error's
    message with another error's failure_class.
    """
    async def _run() -> None:
        claimed, sessions, engine = await _setup_db_and_run(tmp_path, "two_err.db")
        run_id = claimed.run_id

        async def _two_error_stream(*args: Any, **kwargs: Any):
            # First error event
            yield {
                "event": "error",
                "context": {"run_id": str(run_id), "event_seq": 1},
                "payload": {
                    "code": "generation_failed",
                    "message": "First error message",
                    "failure_class": "rate_limited",
                },
            }
            # Second error event with a different message AND a different failure_class
            yield {
                "event": "error",
                "context": {"run_id": str(run_id), "event_seq": 2},
                "payload": {
                    "code": "generation_failed",
                    "message": "Second error message",
                    "failure_class": "timeout",
                },
            }
            yield {"event": "done", "payload": {}}

        with patch(
            "server.generate.run.generate_question_stream",
            new=_two_error_stream,
        ):
            await asyncio.wait_for(
                execute_run(
                    claimed,
                    app_state=_app_state(),
                    config=_server_config(tmp_path),
                    session_factory=sessions,
                    host_id="fc-test-host",
                    client_factory=None,
                    subjects=None,
                ),
                timeout=30.0,
            )

        async with sessions() as session:
            log = (
                await session.execute(
                    select(GenerationLog).where(GenerationLog.id == run_id)
                )
            ).scalar_one_or_none()
            assert log is not None
            assert log.status == "failed"
            assert log.error == "First error message", (
                f"error must come from the first event, got {log.error!r}"
            )
            assert log.failure_class == "rate_limited", (
                f"failure_class must come from the first event, got {log.failure_class!r}"
            )
            # Guard against the regression: error and failure_class must not be
            # from different events (e.g. last message + first class).
            assert log.error != "Second error message", (
                "error must not be overwritten by the second event"
            )
            assert log.failure_class != "timeout", (
                "failure_class must not be overwritten by the second event"
            )

        await engine.dispose()

    asyncio.run(asyncio.wait_for(_run(), timeout=40.0))
