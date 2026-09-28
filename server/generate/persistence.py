"""Persistence helpers for the generate SSE stream.

Owns all concerns related to writing generation records and LLM exchanges to the
database.  Both functions follow the ``exchange_recorder.py`` pattern: the write
sink is INJECTED (never imported from ``server.db`` directly) so tests can pass a
fake session factory without touching the module.

All failures are logged-and-swallowed; persistence must never break generation.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import CancelledError, Future
from typing import Any

import sentry_sdk
from sqlalchemy import select, update

from server.generate.exchange_recorder import ExchangeRecorder
from server.generate.marshalling import extract_image_files, strip_image_base64
from server.models import GenerationLog, GenerationRecord, LLMExchange

logger = logging.getLogger(__name__)

# Bound worker waiting without cancelling an exchange that may still commit.
EXCHANGE_WRITE_TIMEOUT_SECONDS = 10.0

# Maximum number of attempts when saving the per-question generation record in
# the worker thread before publishing RESULT (issue #904).  Each failure after
# the first is preceded by an exponential-backoff sleep unless a custom
# backoff_fn is injected (e.g. instant sleep in tests).
SAVE_MAX_ATTEMPTS: int = 3


class FigurePolicyTrailRecorder:
    """Serialize each policy callback and update its live generation log."""

    _MAX_STAGE_ATTEMPTS = 2

    def __init__(
        self,
        generation_log_id: uuid.UUID,
        loop: asyncio.AbstractEventLoop,
        session_factory: Any,
    ) -> None:
        self._generation_log_id = generation_log_id
        self._loop = loop
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._write_lock = asyncio.Lock()
        self._trail: list[dict[str, Any]] = []

    def __call__(self, entry: Any) -> None:
        payload = entry.model_dump(mode="json") if hasattr(entry, "model_dump") else entry
        with self._lock:
            self._trail.append(payload)
            snapshot = list(self._trail)
            self._stage_snapshot(snapshot)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._trail)

    def _stage_snapshot(self, trail: list[dict[str, Any]]) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self._persist_with_retries(trail),
            self._loop,
        )
        try:
            future.result(timeout=10)
        except Exception as exc:  # noqa: BLE001 — policy persistence is best effort
            logger.warning("figure policy trail staging deferred: %s", exc)

    async def flush(self) -> None:
        """Retry the latest prefix after all workers have stopped emitting."""
        snapshot = self.snapshot()
        if not snapshot:
            return
        await self._persist_with_retries(snapshot)

    async def _persist_with_retries(self, trail: list[dict[str, Any]]) -> None:
        """Replace the staging prefix in callback order, retrying transient failures."""
        async with self._write_lock:
            for attempt in range(self._MAX_STAGE_ATTEMPTS):
                try:
                    await self._persist(trail)
                    return
                except Exception as exc:  # noqa: BLE001 — policy persistence is best effort
                    if attempt == self._MAX_STAGE_ATTEMPTS - 1:
                        logger.warning("figure policy trail staging failed: %s", exc)

    async def _persist(self, trail: list[dict[str, Any]]) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == self._generation_log_id)
                .values(figure_policy_trail_json=trail)
            )
            await session.commit()


def make_figure_policy_trail_recorder(
    *,
    generation_log_id: uuid.UUID | None,
    loop: asyncio.AbstractEventLoop,
    session_factory: Any,
) -> FigurePolicyTrailRecorder | None:
    """Create the incremental recorder, or disable it for log-less runs."""
    if generation_log_id is None:
        return None
    return FigurePolicyTrailRecorder(generation_log_id, loop, session_factory)


async def _staged_figure_policy_trail(
    generation_log_id: uuid.UUID | None,
    session_factory: Any,
) -> list[dict[str, Any]] | None:
    if generation_log_id is None:
        return None
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(GenerationLog).where(GenerationLog.id == generation_log_id)
            )
            row = result.scalar_one_or_none()
            return row.figure_policy_trail_json if row is not None else None
    except Exception as exc:  # noqa: BLE001 — tombstone persistence is best effort
        logger.warning("failed to read staged figure policy trail: %s", exc)
        return None



class ReferenceExampleRecordRecorder:
    """Serialize each reference example callback and update its live generation log."""

    _MAX_STAGE_ATTEMPTS = 2

    def __init__(
        self,
        generation_log_id: uuid.UUID,
        loop: asyncio.AbstractEventLoop,
        session_factory: Any,
        disabled: bool = False,
    ) -> None:
        self._generation_log_id = generation_log_id
        self._loop = loop
        self._session_factory = session_factory
        self._disabled = disabled
        self._lock = threading.Lock()
        self._write_lock = asyncio.Lock()
        self._entries: list[dict[str, Any]] = []

    def __call__(self, entry: Any) -> None:
        payload = entry.model_dump(mode="json") if hasattr(entry, "model_dump") else entry
        with self._lock:
            self._entries.append(payload)
            snapshot = list(self._entries)
            self._stage_snapshot(snapshot)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)

    def _stage_snapshot(self, entries: list[dict[str, Any]]) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self._persist_with_retries(entries),
            self._loop,
        )
        try:
            future.result(timeout=10)
        except Exception as exc:  # noqa: BLE001 — persistence is best effort
            logger.warning("reference example record staging deferred: %s", exc)

    async def flush(self) -> None:
        """Retry the latest snapshot after all workers have stopped emitting."""
        snapshot = self.snapshot()
        if not snapshot:
            return
        await self._persist_with_retries(snapshot)

    async def _persist_with_retries(self, entries: list[dict[str, Any]]) -> None:
        async with self._write_lock:
            for attempt in range(self._MAX_STAGE_ATTEMPTS):
                try:
                    await self._persist(entries)
                    return
                except Exception as exc:  # noqa: BLE001 — persistence is best effort
                    if attempt == self._MAX_STAGE_ATTEMPTS - 1:
                        logger.warning("reference example record staging failed: %s", exc)

    async def _persist(self, entries: list[dict[str, Any]]) -> None:
        record = {"disabled": self._disabled, "entries": entries}
        async with self._session_factory() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == self._generation_log_id)
                .values(reference_example_record_json=record)
            )
            await session.commit()


def make_reference_example_record_recorder(
    *,
    generation_log_id: uuid.UUID | None,
    loop: asyncio.AbstractEventLoop,
    session_factory: Any,
    disabled: bool = False,
) -> ReferenceExampleRecordRecorder | None:
    """Create the incremental recorder, or disable it for log-less runs."""
    if generation_log_id is None:
        return None
    return ReferenceExampleRecordRecorder(
        generation_log_id, loop, session_factory, disabled=disabled
    )


async def _staged_reference_example_record(
    generation_log_id: uuid.UUID | None,
    session_factory: Any,
) -> list[dict[str, Any]] | None:
    if generation_log_id is None:
        return None
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(GenerationLog).where(GenerationLog.id == generation_log_id)
            )
            row = result.scalar_one_or_none()
            return row.reference_example_record_json if row is not None else None
    except Exception as exc:  # noqa: BLE001 — tombstone persistence is best effort
        logger.warning("failed to read staged reference example record: %s", exc)
        return None


async def persist_generation_record(
    *,
    user_id: uuid.UUID,
    generation_log_id: uuid.UUID | None,
    subject: str,
    params: Any,
    payload: dict[str, Any],
    session_factory: Any,
    parent_record_id: uuid.UUID | None = None,
    annotations_json: dict[str, Any] | None = None,
    verification_trail_json: list[dict[str, Any]] | None = None,
    figure_policy_trail_json: list[dict[str, Any]] | None = None,
    reference_example_record_json: list[dict[str, Any]] | None = None,
) -> uuid.UUID | None:
    """Insert one generation_records row and return its id on success.

    Persistence is best effort so a database failure must never break the
    generation stream; callers can use the id to continue a persisted record
    chain when it is available.
    """
    try:
        record = GenerationRecord(
            user_id=user_id,
            generation_log_id=generation_log_id,
            parent_record_id=parent_record_id,
            subject=subject,
            question_id=payload.get("id", ""),
            params_json=(
                params.model_dump(mode="json")
                if hasattr(params, "model_dump")
                else dict(params)
            ),
            annotations_json=annotations_json,
            question_json=strip_image_base64(payload),
            verification_trail_json=verification_trail_json,
            figure_policy_trail_json=figure_policy_trail_json,
            reference_example_record_json=reference_example_record_json,
            image_files=extract_image_files(payload),
            status="completed",
        )
        async with session_factory() as session:
            session.add(record)
            await session.commit()
            return record.id
    except Exception as exc:  # noqa: BLE001 — best-effort persistence
        logger.warning("failed to persist generation_record: %s", exc)
        return None


async def save_generation_record_with_retries(
    *,
    user_id: uuid.UUID,
    generation_log_id: uuid.UUID | None,
    subject: str,
    params: Any,
    payload: dict[str, Any],
    session_factory: Any,
    verification_trail_json: list[dict[str, Any]] | None = None,
    figure_policy_trail_json: list[dict[str, Any]] | None = None,
    reference_example_record_json: Any | None = None,
    max_attempts: int = SAVE_MAX_ATTEMPTS,
    backoff_fn: Callable[[int], Any] | None = None,
) -> uuid.UUID | None:
    """Insert the generation record with bounded retry + Sentry on exhaustion.

    Mirrors the retry loop in ReferenceExampleRecordRecorder._persist_with_retries
    but is used from the worker thread via asyncio.run_coroutine_threadsafe so
    the record is committed BEFORE the RESULT event is published (issue #904).

    The ``backoff_fn(attempt)`` coroutine is called between attempts; it defaults
    to an exponential ``asyncio.sleep`` (2**attempt seconds).  Pass an instant
    no-op in tests to keep them fast.

    Returns the new record's UUID on success, or None after exhaustion (Sentry
    has been notified).
    """
    if backoff_fn is None:

        async def _default_backoff(attempt: int) -> None:
            await asyncio.sleep(2**attempt)

        backoff_fn = _default_backoff

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            record = GenerationRecord(
                user_id=user_id,
                generation_log_id=generation_log_id,
                subject=subject,
                question_id=payload.get("id", ""),
                params_json=(
                    params.model_dump(mode="json")
                    if hasattr(params, "model_dump")
                    else dict(params)
                ),
                question_json=strip_image_base64(payload),
                verification_trail_json=verification_trail_json,
                figure_policy_trail_json=figure_policy_trail_json,
                reference_example_record_json=reference_example_record_json,
                image_files=extract_image_files(payload),
                status="completed",
            )
            async with session_factory() as session:
                session.add(record)
                await session.commit()
                return record.id
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "persist_generation_record attempt %d/%d failed: %s",
                attempt + 1,
                max_attempts,
                type(exc).__name__,
            )
            if attempt < max_attempts - 1:
                await backoff_fn(attempt)

    # All retries exhausted: report to Sentry so the failure is visible.
    sentry_sdk.capture_exception(last_exc)
    logger.error(
        "persist_generation_record exhausted %d attempts; reported to Sentry",
        max_attempts,
    )
    return None


async def persist_failed_generation_record(
    *,
    user_id: uuid.UUID,
    generation_log_id: uuid.UUID | None,
    subject: str,
    params: Any,
    error: str,
    session_factory: Any,
) -> None:
    """Insert one failed-run tombstone without a question payload.

    Failed-run history is best effort for the same reason as successful result
    persistence: a database problem must not prevent the stream from reporting
    its server-side error to the caller.
    """
    try:
        figure_policy_trail_json = await _staged_figure_policy_trail(
            generation_log_id,
            session_factory,
        )
        reference_example_record_json = await _staged_reference_example_record(
            generation_log_id,
            session_factory,
        )
        record = GenerationRecord(
            user_id=user_id,
            generation_log_id=generation_log_id,
            subject=subject,
            question_id="",
            params_json=params.model_dump(mode="json"),
            question_json=None,
            verification_trail_json=None,
            figure_policy_trail_json=figure_policy_trail_json,
            reference_example_record_json=reference_example_record_json,
            image_files=[],
            status="failed",
            error=error,
        )
        async with session_factory() as session:
            session.add(record)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort persistence
        logger.warning("failed to persist failed generation_record: %s", exc)


async def persist_aborted_generation_record(
    *,
    user_id: uuid.UUID,
    generation_log_id: uuid.UUID | None,
    subject: str,
    params: Any,
    session_factory: Any,
) -> None:
    """Insert one user-aborted run tombstone without a question payload."""
    try:
        figure_policy_trail_json = await _staged_figure_policy_trail(
            generation_log_id,
            session_factory,
        )
        reference_example_record_json = await _staged_reference_example_record(
            generation_log_id,
            session_factory,
        )
        record = GenerationRecord(
            user_id=user_id,
            generation_log_id=generation_log_id,
            subject=subject,
            question_id="",
            params_json=params.model_dump(mode="json"),
            question_json=None,
            verification_trail_json=None,
            figure_policy_trail_json=figure_policy_trail_json,
            reference_example_record_json=reference_example_record_json,
            image_files=[],
            status="aborted",
        )
        async with session_factory() as session:
            session.add(record)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort persistence
        logger.warning("failed to persist aborted generation_record: %s", exc)


def make_exchange_recorder(
    *,
    generation_log_id: uuid.UUID | None,
    retention_days: int,
    loop: asyncio.AbstractEventLoop,
    session_factory: Any,
    next_order: Any,
) -> ExchangeRecorder | None:
    """Return an ExchangeRecorder wired to *session_factory*, or None when disabled.

    Returns None when *generation_log_id* is None or *retention_days* is ≤ 0,
    matching the production disable logic.

    The write sink runs ``asyncio.run_coroutine_threadsafe`` so it is safe to
    call from background ThreadPoolExecutor workers. A wait timeout leaves the
    insert running and reports its eventual outcome; the returned recorder
    retains that future for its caller's ``flush()`` barrier. Failures never
    propagate.
    """
    if generation_log_id is None or retention_days <= 0:
        return None

    async def _insert(row: dict[str, Any]) -> None:
        async with session_factory() as sess:
            # Operation/call identity is persisted inside the JSON bodies for
            # schema compatibility; the recorder also exposes the flat fields
            # to in-process sinks and tests.
            db_row = {
                key: value
                for key, value in row.items()
                if key not in {"run_id", "call_id", "operation_id", "retry_of_call_id"}
            }
            sess.add(LLMExchange(**db_row))
            await sess.commit()

    def _write_row(row: dict[str, Any]) -> Future[None] | None:
        metadata = {
            "generation_log_id": str(generation_log_id),
            "agent": row["agent"],
            "exchange_order": row["exchange_order"],
        }

        def report(outcome: str, error: Exception | None = None) -> None:
            # Exception strings/tracebacks can contain SQL parameters and exam content.
            # Late success also needs WARNING: ADR 0004 forwards only WARNING+.
            error_type = type(error).__name__ if error is not None else None
            logger.warning(
                "llm_exchanges insert %s (%s)", outcome, error_type,
                extra={
                    **metadata,
                    "outcome": outcome,
                    "error_type": error_type,
                    "error_module": type(error).__module__ if error is not None else None,
                },
            )

        def report_completion(completed: Future[None]) -> None:
            try:
                completed.result()
            except CancelledError as exc:
                report("cancelled", exc)
            except Exception as exc:  # noqa: BLE001 — best-effort persistence
                report("failed", exc)
            else:
                report("committed")

        insertion = _insert(row)
        try:
            future = asyncio.run_coroutine_threadsafe(insertion, loop)
        except Exception as exc:  # noqa: BLE001 — best-effort persistence
            insertion.close()
            report("not_scheduled", exc)
            return None
        try:
            future.result(timeout=EXCHANGE_WRITE_TIMEOUT_SECONDS)
        except CancelledError as exc:
            report("cancelled", exc)
        except TimeoutError as exc:
            if future.done():
                # Commit/cancellation/failure may race with timeout handling.
                # Also distinguishes a TimeoutError raised by the DB itself.
                report_completion(future)
            else:
                report("pending", exc)
                # Runs immediately if completion races with callback registration.
                # Keep the insert alive; retain only non-content metadata here.
                future.add_done_callback(report_completion)
        except Exception as exc:  # noqa: BLE001 — best-effort persistence
            report("failed", exc)
        return future

    return ExchangeRecorder(generation_log_id, _write_row, next_order=next_order)
