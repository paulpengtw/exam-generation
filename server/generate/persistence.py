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
import uuid
from typing import Any

from server.generate.exchange_recorder import ExchangeRecorder
from server.generate.marshalling import extract_image_files, strip_image_base64
from server.models import GenerationRecord, LLMExchange

logger = logging.getLogger(__name__)


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
        record = GenerationRecord(
            user_id=user_id,
            generation_log_id=generation_log_id,
            subject=subject,
            question_id="",
            params_json=params.model_dump(mode="json"),
            question_json=None,
            verification_trail_json=None,
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
        record = GenerationRecord(
            user_id=user_id,
            generation_log_id=generation_log_id,
            subject=subject,
            question_id="",
            params_json=params.model_dump(mode="json"),
            question_json=None,
            verification_trail_json=None,
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
    call from background ThreadPoolExecutor workers.  Write failures are logged
    as warnings and never raised.
    """
    if generation_log_id is None or retention_days <= 0:
        return None

    async def _insert(row: dict[str, Any]) -> None:
        async with session_factory() as sess:
            sess.add(LLMExchange(**row))
            await sess.commit()

    def _write_row(row: dict[str, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(_insert(row), loop)
        try:
            future.result(timeout=10)
        except Exception as exc:  # noqa: BLE001 — best-effort persistence
            logger.warning("llm_exchanges insert failed: %s", exc)

    return ExchangeRecorder(generation_log_id, _write_row, next_order=next_order)
