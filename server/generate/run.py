"""The detached 生成執行 (generation run): 受理, host-loop execution and reads.

A run exists from 受理 until every manifest question has a 終止原因, whether or
not anyone is watching (openspec change ``detached-generation-runs``; ADR 0033,
ADR 0034).  The module's entry points are:

``accept_run``
    Durably record the run (``queued``) and one waiting 處理狀態 row per
    manifest question, and return the run identity and manifest.
``read_run``
    Owner-only read of the persisted run state, per question.
``claim_next_run``
    Claim the oldest eligible queued run with ``FOR UPDATE SKIP LOCKED``.
``run_host_loop``
    Claim and execute runs until stopped.  The backend's lifespan and
    ``python -m server.worker`` both call this one function (ADR 0034).

Execution reuses ``generate_question_stream`` as an in-process event bus: the
host is its only consumer, so no observer can close it, and each event is
translated into persisted per-question state.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import os
import socket
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from server.config import ServerConfig
from server.db import AsyncSessionLocal
from server.generate.event_protocol import QuestionTerminalPayload
from server.generate.marshalling import SSEEventName, embed_image_base64
from server.generate.models import SERVER_ONLY_GENERATE_FIELDS, GenerateParams
from server.generate.persistence import persist_failed_generation_record
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS, SubjectSpec
from server.models import GenerationLog, GenerationQuestionState, GenerationRecord, User
from src.common.generation_events import allocate_manifest

logger = logging.getLogger(__name__)

RUN_PROTOCOL_VERSION = 3
HEARTBEAT_INTERVAL_S = 30.0
IDLE_INTERVAL_S = 2.0
STALE_THRESHOLD_S = 180.0   # 3× heartbeat interval — stale after 3 minutes
MAX_ATTEMPTS = 3             # maximum host-loop retries before giving up
TIME_LIMIT_S = 7200.0        # 2-hour wall-clock limit per run (from started_at)

# Statuses a 生成執行 moves through; 人工審題修正 logs stay "started" and never
# enter this set, so the claim cannot pick them up.
UNFINISHED_RUN_STATUSES = ("queued", "running")

# ---------------------------------------------------------------------------
# Live observer registry (issue #909)
# ---------------------------------------------------------------------------

_live_observers: dict[str, list[asyncio.Queue]] = {}
_live_observers_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Return the module-level lock, creating it lazily in the running loop."""
    global _live_observers_lock  # noqa: PLW0603
    if _live_observers_lock is None:
        _live_observers_lock = asyncio.Lock()
    return _live_observers_lock


async def subscribe_live(run_id: str) -> asyncio.Queue:
    """Register a new observer queue for *run_id* and return it."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    async with _get_lock():
        _live_observers.setdefault(run_id, []).append(queue)
    return queue


async def unsubscribe_live(run_id: str, queue: asyncio.Queue) -> None:
    """Remove *queue* from the registry for *run_id*.

    The slot (key) is preserved so ``is_live_available`` keeps returning True
    while the run is executing.  Only ``execute_run``'s finally block removes
    the key.
    """
    async with _get_lock():
        observers = _live_observers.get(run_id, [])
        if queue in observers:
            observers.remove(queue)


def is_live_available(run_id: str) -> bool:
    """True when the run's observer slot exists (i.e. the run is executing in this process).

    Returns True even when no observer queues are currently connected.
    Availability means the slot was registered by ``execute_run``, not that
    anyone is watching.
    """
    return run_id in _live_observers


async def _publish_live(run_id: str, event: dict) -> None:
    """Broadcast *event* to all registered observers for *run_id*.

    Non-blocking: uses ``put_nowait`` so a slow or disconnected observer
    never blocks ``execute_run``.  Overflowing queues drop the event with a
    WARNING; any other exception is suppressed so the run is never affected.
    """
    try:
        async with _get_lock():
            observers = list(_live_observers.get(run_id, []))
        for queue in observers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "live observer queue full for run %s, dropping event", run_id
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "live observer put_nowait failed for run %s", run_id, exc_info=True
                )
    except Exception:  # noqa: BLE001
        logger.warning("_publish_live failed for run %s", run_id, exc_info=True)


Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc_aware(dt: datetime) -> datetime:
    """Return *dt* with UTC tzinfo, adding it when the datetime is naive (SQLite stores naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def default_host_id() -> str:
    """Identify this host process in ``generation_logs.claimed_by``."""
    return f"{socket.gethostname()}:{os.getpid()}"


# ---------------------------------------------------------------------------
# 受理
# ---------------------------------------------------------------------------

QUEUE_LIMIT = 5
"""Maximum number of queued (not yet executing) runs allowed per teacher."""


class QueueLimitError(Exception):
    """Raised by ``accept_run`` when a teacher already has ``QUEUE_LIMIT`` queued runs.

    The ``run_id`` attribute is always ``None``; callers must turn this into an
    HTTP 429 response with a stable ``code`` and a localizable ``detail``.
    """


@dataclasses.dataclass(frozen=True)
class AcceptedRun:
    run_id: str
    total: int
    questions: list[dict[str, Any]]

    def to_response(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "protocol_version": RUN_PROTOCOL_VERSION,
            "total": self.total,
            "questions": self.questions,
        }


async def _build_accepted_run_from_log(
    log: GenerationLog,
    session: AsyncSession,
) -> AcceptedRun:
    """Reconstruct an ``AcceptedRun`` from an existing ``GenerationLog``."""
    states = (
        await session.execute(
            select(GenerationQuestionState)
            .where(GenerationQuestionState.generation_log_id == log.id)
            .order_by(GenerationQuestionState.index)
        )
    ).scalars().all()
    return AcceptedRun(
        run_id=str(log.id),
        total=len(states),
        questions=[
            {"index": s.index, "question_id": s.question_id}
            for s in states
        ],
    )


async def accept_run(
    params: GenerateParams,
    user_id: uuid.UUID,
    *,
    session: AsyncSession,
    submission_key: str | None = None,
    queue_limit: int = QUEUE_LIMIT,
) -> AcceptedRun:
    """Record a queued run and its waiting questions in one transaction.

    Deduplication: when *submission_key* is provided and a run already exists
    for ``(user_id, submission_key)``, the original ``AcceptedRun`` is returned
    without creating anything new (idempotent retry after a network error).
    The duplicate-key retry bypasses the queue-limit check so the teacher
    always gets their run back.

    Queue limit: if the teacher already has ``queue_limit`` queued runs *and*
    this is not a dedup retry, ``QueueLimitError`` is raised and nothing is
    created.  A race where two concurrent requests both pass the limit check is
    resolved by whichever ``INSERT`` wins; the loser catches ``IntegrityError``
    (from the ``(user_id, submission_key)`` unique constraint) and returns the
    winner's run.

    Missing submission_key: accepted without dedup (conservative).
    """
    # If not supplied as an explicit kwarg, fall back to params.submission_key
    # so callers that embed the key in the params object still work.
    if submission_key is None:
        submission_key = getattr(params, "submission_key", None)

    # --- Dedup check (key present) -------------------------------------------
    if submission_key is not None:
        existing_log = (
            await session.execute(
                select(GenerationLog).where(
                    GenerationLog.user_id == user_id,
                    GenerationLog.submission_key == submission_key,
                )
            )
        ).scalar_one_or_none()
        if existing_log is not None:
            return await _build_accepted_run_from_log(existing_log, session)

    # --- Per-teacher serialization lock (Postgres) ---------------------------
    # Acquire an exclusive row lock on the teacher's User record.  On Postgres
    # this serialises concurrent accept_run calls from the same user so the
    # queue-count check and the INSERT are atomic per teacher.  SQLAlchemy
    # no-ops with_for_update() on SQLite, so this branch is safe on both.
    await session.execute(
        select(User).where(User.id == user_id).with_for_update()
    )

    # --- Queue limit check ---------------------------------------------------
    queued_count: int = (
        await session.execute(
            select(func.count()).select_from(GenerationLog).where(
                GenerationLog.user_id == user_id,
                GenerationLog.status == "queued",
            )
        )
    ).scalar_one()
    if queued_count >= queue_limit:
        raise QueueLimitError(
            f"teacher already has {queued_count} queued runs (limit {queue_limit})"
        )

    # --- Create the run ------------------------------------------------------
    log_id = uuid.uuid4()
    manifest = allocate_manifest(
        SUBJECTS[params.subject].question_id_prefix, str(log_id), max(1, params.count)
    )
    new_log = GenerationLog(
        id=log_id,
        user_id=user_id,
        params_json=params.model_dump(mode="json", exclude=set(SERVER_ONLY_GENERATE_FIELDS)),
        status="queued",
        # Queue order while queued; the first claim restamps it as the
        # execution start that the time limit is measured from.
        started_at=_utcnow(),
        submission_key=submission_key,
    )
    session.add(new_log)
    session.add_all(
        GenerationQuestionState(
            generation_log_id=log_id,
            question_id=question.question_id,
            index=question.index,
            processing="waiting",
        )
        for question in manifest
    )
    try:
        await session.commit()
    except IntegrityError:
        # Race: another concurrent request with the same submission_key committed
        # first.  Roll back, look up the winner and return it.
        await session.rollback()
        if submission_key is not None:
            winner = (
                await session.execute(
                    select(GenerationLog).where(
                        GenerationLog.user_id == user_id,
                        GenerationLog.submission_key == submission_key,
                    )
                )
            ).scalar_one_or_none()
            if winner is not None:
                return await _build_accepted_run_from_log(winner, session)
        # No submission_key or race resolved in an unexpected way: re-raise.
        raise

    return AcceptedRun(
        run_id=str(log_id),
        total=len(manifest),
        questions=[
            {"index": question.index, "question_id": question.question_id}
            for question in manifest
        ],
    )


# ---------------------------------------------------------------------------
# Owner read
# ---------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def read_run(
    run_id: str | uuid.UUID,
    user_id: uuid.UUID,
    *,
    session: AsyncSession,
    config: ServerConfig,
) -> dict[str, Any] | None:
    """Return the owner's persisted run state, or None when absent or not theirs."""
    try:
        log_id = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
    except ValueError:
        return None
    log = (
        await session.execute(
            select(GenerationLog).where(
                GenerationLog.id == log_id, GenerationLog.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if log is None:
        return None
    states = (
        await session.execute(
            select(GenerationQuestionState)
            .where(GenerationQuestionState.generation_log_id == log_id)
            .order_by(GenerationQuestionState.index)
        )
    ).scalars().all()
    if not states:
        # Not a 生成執行 (a pre-detached log or a 人工審題修正 log).
        return None
    record_ids = [s.generation_record_id for s in states if s.generation_record_id]
    records = {
        record.id: record
        for record in (
            await session.execute(
                select(GenerationRecord).where(GenerationRecord.id.in_(record_ids))
            )
        ).scalars().all()
    } if record_ids else {}

    questions = []
    for state in states:
        record = records.get(state.generation_record_id)
        result = None
        if record is not None and record.question_json is not None:
            result = {
                "record_id": str(record.id),
                "question": await asyncio.to_thread(
                    embed_image_base64, record.question_json, config
                ),
                "verification_trail": record.verification_trail_json,
                "figure_policy_trail": record.figure_policy_trail_json,
                "reference_example_record": record.reference_example_record_json,
            }
        questions.append({
            "index": state.index,
            "question_id": state.question_id,
            "processing": state.processing,
            "current_step": state.current_step,
            "termination_reason": state.termination_reason,
            "terminal": state.terminal_json,
            "error": state.error,
            "result": result,
        })
    # --- Queue position (per-teacher; only meaningful when queued) -----------
    # Count the teacher's own runs that are ahead of this one:
    # running runs (exactly one possible) plus queued runs that were queued
    # earlier (smaller started_at, or same started_at but smaller id).
    queue_position: int | None = None
    if log.status == "queued":
        running_log = aliased(GenerationLog)
        ahead_count: int = (
            await session.execute(
                select(func.count()).select_from(running_log).where(
                    running_log.user_id == user_id,
                    running_log.status.in_(["running", "queued"]),
                    running_log.id != log_id,
                    (running_log.status == "running")
                    | (running_log.started_at < log.started_at)
                    | (
                        (running_log.started_at == log.started_at)
                        & (running_log.id < log_id)
                    ),
                )
            )
        ).scalar_one()
        queue_position = ahead_count

    return {
        "run_id": str(log.id),
        "status": log.status,
        "subject": log.params_json.get("subject"),
        "total": len(states),
        "started_at": _iso(log.started_at),
        "completed_at": _iso(log.completed_at),
        "error": log.error,
        "cancel_requested": log.cancel_requested,
        "queue_position": queue_position,
        "questions": questions,
        "live_events_available": is_live_available(str(log.id)),
    }


_LIST_RUNS_ENDED_LIMIT = 20
"""Maximum number of ended (completed/failed/cancelled) runs returned by list_runs."""


async def list_runs(
    user_id: uuid.UUID,
    *,
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Return summary rows for the owner's runs, newest first.

    All unfinished (queued/running) runs are always included.  Ended
    (completed/failed/cancelled) runs are capped at
    ``_LIST_RUNS_ENDED_LIMIT`` (currently 20) to keep the response size
    bounded as history grows.

    Each row includes ``queue_position`` (non-null only when the run is
    ``queued``).  The result is ordered by ``started_at DESC, id DESC`` so
    newly accepted runs appear at the top.
    """
    _UNFINISHED = ("queued", "running")
    _ENDED_STATUSES = ("completed", "failed", "cancelled")

    # All unfinished runs
    unfinished_logs = (
        await session.execute(
            select(GenerationLog)
            .where(
                GenerationLog.user_id == user_id,
                GenerationLog.status.in_(_UNFINISHED),
            )
            .order_by(GenerationLog.started_at.desc(), GenerationLog.id.desc())
        )
    ).scalars().all()

    # Most recent N ended runs
    ended_logs = (
        await session.execute(
            select(GenerationLog)
            .where(
                GenerationLog.user_id == user_id,
                GenerationLog.status.in_(_ENDED_STATUSES),
            )
            .order_by(GenerationLog.started_at.desc(), GenerationLog.id.desc())
            .limit(_LIST_RUNS_ENDED_LIMIT)
        )
    ).scalars().all()

    logs = list(unfinished_logs) + list(ended_logs)
    # Re-sort combined list newest first
    logs.sort(key=lambda lg: (lg.started_at, lg.id), reverse=True)

    if not logs:
        return []

    # Compute queue_position for each queued run in a single pass.
    # Order the full set by (started_at, id) ascending; a run's position is the
    # count of running/queued runs that come before it in that ordering.
    running_or_queued = [
        (log.started_at, log.id, log.status)
        for log in logs
        if log.status in ("running", "queued")
    ]
    # Sort by (started_at, id) ascending — same order as the claim loop.
    running_or_queued.sort(key=lambda t: (t[0], t[1]))
    # Build a map: run_id → queue_position (0-based count of runs ahead).
    ahead_count_map: dict[uuid.UUID, int] = {}
    running_seen = 0
    queued_seen = 0
    for started_at, rid, st in running_or_queued:
        if st == "running":
            ahead_count_map[rid] = running_seen + queued_seen
            running_seen += 1
        else:  # "queued"
            ahead_count_map[rid] = running_seen + queued_seen
            queued_seen += 1

    rows = []
    for log in logs:
        queue_position: int | None = (
            ahead_count_map.get(log.id) if log.status == "queued" else None
        )
        rows.append({
            "run_id": str(log.id),
            "status": log.status,
            "subject": log.params_json.get("subject"),
            "started_at": _iso(log.started_at),
            "completed_at": _iso(log.completed_at),
            "queue_position": queue_position,
            "cancel_requested": bool(log.cancel_requested),
        })
    return rows


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ClaimedRun:
    run_id: uuid.UUID
    user_id: uuid.UUID
    params_json: dict[str, Any]
    attempt: int


async def claim_next_run(
    session_factory: Any,
    *,
    host_id: str,
    now: datetime | None = None,
    stale_threshold_s: float = STALE_THRESHOLD_S,
) -> ClaimedRun | None:
    """Claim the oldest eligible run: queued runs whose owner has no live run,
    or stale ``running`` runs whose heartbeat has not been updated in at least
    ``stale_threshold_s`` seconds (i.e. the original host crashed).

    ``FOR UPDATE SKIP LOCKED`` lets concurrent hosts claim different runs
    without blocking each other; SQLite ignores the clause.
    """
    from datetime import timedelta  # noqa: PLC0415 – local import to keep top-level clean
    claimed_at = now if now is not None else _utcnow()
    stale_cutoff = claimed_at - timedelta(seconds=stale_threshold_s)

    running = aliased(GenerationLog)
    owner_is_running = (
        select(running.id)
        .where(running.user_id == GenerationLog.user_id, running.status == "running")
        .exists()
    )
    # A stale run is "running" but its heartbeat_at is too old.  Its *own*
    # teacher record still has a "running" entry (this run itself), so we must
    # not apply the owner_is_running filter to stale runs — they are their own
    # "running" entry.  We limit stale reclaims to runs with attempts < MAX_ATTEMPTS.
    async with session_factory() as session:
        # 1. Try a stale running run first (higher priority — issue #911 fix).
        # No attempt-limit filter here: a run that has exhausted its attempts
        # must be *finalised* below, not silently skipped (that was the
        # stuck-forever bug — issue #911).
        stale_log = (
            await session.execute(
                select(GenerationLog)
                .where(
                    GenerationLog.status == "running",
                    GenerationLog.heartbeat_at <= stale_cutoff,
                )
                .order_by(GenerationLog.started_at, GenerationLog.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

        log = None
        _stale_to_persist: tuple | None = None  # (user_id, id, params_json, reason)
        if stale_log is not None:
            # Issue #911: check if this stale run must be finalised instead of
            # reclaimed.  Two conditions require finalization:
            # 1. attempts >= MAX_ATTEMPTS  → recovery_exhausted
            # 2. wall-clock past TIME_LIMIT_S → time_limit
            # Both checks run inside the same FOR UPDATE SKIP LOCKED transaction
            # so two racing hosts cannot both finalize the same run.
            exhausted = stale_log.attempts >= MAX_ATTEMPTS
            time_exceeded = (
                stale_log.started_at is not None
                and (
                    claimed_at - _utc_aware(stale_log.started_at)
                ).total_seconds() >= TIME_LIMIT_S
            )
            if exhausted or time_exceeded:
                reason = "time_limit" if time_exceeded else "recovery_exhausted"
                await session.execute(
                    update(GenerationQuestionState)
                    .where(
                        GenerationQuestionState.generation_log_id == stale_log.id,
                        GenerationQuestionState.termination_reason.is_(None),
                    )
                    .values(
                        processing="ended",
                        current_step=None,
                        termination_reason="failed",
                        terminal_json=_unfinished_terminal(reason),
                        updated_at=claimed_at,
                    )
                )
                await session.execute(
                    update(GenerationLog)
                    .where(GenerationLog.id == stale_log.id)
                    .values(status="failed", error=reason, completed_at=claimed_at)
                )
                await session.commit()
                logger.info(
                    "run %s finalized during claim (%s); attempts=%d",
                    stale_log.id, reason, stale_log.attempts,
                )
                # Persist a failed-run tombstone (best-effort, outside the
                # FOR UPDATE SKIP LOCKED transaction that just committed).
                _stale_to_persist = (
                    stale_log.user_id,
                    stale_log.id,
                    dict(stale_log.params_json),
                    reason,
                )
            else:
                log = stale_log

        if log is None and _stale_to_persist is None:
            # 2. Fall back to a fresh queued run.
            log = (
                await session.execute(
                    select(GenerationLog)
                    .where(GenerationLog.status == "queued", ~owner_is_running)
                    .order_by(GenerationLog.started_at, GenerationLog.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()

        if _stale_to_persist is not None:
            # A stale run was finalised above (already committed).  Return None
            # so the host loop can move on, but first persist the tombstone.
            pass  # will fall through to the persistence + return None below

        elif log is None:
            await session.rollback()

        if log is not None and _stale_to_persist is None:
            if log.attempts == 0:
                log.started_at = claimed_at
            log.attempts += 1
            log.status = "running"
            log.claimed_by = host_id
            log.heartbeat_at = claimed_at
            claimed = ClaimedRun(
                run_id=log.id,
                user_id=log.user_id,
                params_json=dict(log.params_json),
                attempt=log.attempts,
            )
            await session.commit()
            return claimed

    # Either log is None (nothing to claim) or a stale was finalised.
    if _stale_to_persist is not None:
        uid, gid, params_json, reason = _stale_to_persist
        try:
            stale_params = GenerateParams.model_validate(params_json)
            await persist_failed_generation_record(
                user_id=uid,
                generation_log_id=gid,
                subject=params_json.get("subject", ""),
                params=stale_params,
                error=reason,
                session_factory=session_factory,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "claim-time finalize: failed to persist failed record for %s", gid
            )
    return None


# ---------------------------------------------------------------------------
# Cancel (issue #910)
# ---------------------------------------------------------------------------


def _cancelled_terminal(reason: str = "cancelled before completion") -> dict[str, Any]:
    """A cancelled terminal for a question that ended without completion."""
    payload = {
        "termination_reason": "cancelled",
        "has_final": False,
        "final_revision": None,
        "delivery_status": "unknown",
        "expected": [],
        "delivered": [],
        "missing": [],
        "review": {"status": "unknown", "reason": "no final content"},
        "unknown_reason": reason,
    }
    QuestionTerminalPayload.model_validate(payload)
    return payload


async def cancel_run(
    run_id: str | uuid.UUID,
    user_id: uuid.UUID,
    *,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """Cancel a 生成執行 (owner-only, idempotent).

    Returns ``None`` when the run is not found or not owned (existence-hiding).
    Returns a dict with ``{"cancelled": bool, "reason": str}`` describing what
    happened:

    - ``cancelled=False, reason="already_ended"`` — all questions had a
      終止原因 already; nothing changed.
    - ``cancelled=True, reason="queued_run_cancelled"`` — the run was still
      queued; questions are marked cancelled immediately.
    - ``cancelled=True`` — cancel_requested flag set; the executing host will
      pick it up on the next heartbeat and confirm cancellation.
    """
    try:
        log_id = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
    except ValueError:
        return None

    log = (
        await session.execute(
            select(GenerationLog).where(
                GenerationLog.id == log_id, GenerationLog.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if log is None:
        return None

    states = (
        await session.execute(
            select(GenerationQuestionState).where(
                GenerationQuestionState.generation_log_id == log_id
            )
        )
    ).scalars().all()

    # Not a detached run (e.g. a pre-detached 人工審題修正 log).
    if not states:
        return None

    # AC3: if all questions already have a termination_reason, the run is done.
    if all(s.termination_reason is not None for s in states):
        return {"cancelled": False, "reason": "already_ended"}

    # Queued run: cancel immediately without waiting for a host to claim it.
    if log.status == "queued":
        now = _utcnow()
        terminal = _cancelled_terminal("cancelled before execution")
        # Guard: only update GenerationLog when status is still "queued" (race protection).
        log_res = await session.execute(
            update(GenerationLog)
            .where(GenerationLog.id == log_id, GenerationLog.status == "queued")
            .values(status="cancelled", completed_at=now, cancel_requested=True)
        )
        if log_res.rowcount > 0:
            # Log update succeeded: mark all pending questions as cancelled.
            await session.execute(
                update(GenerationQuestionState)
                .where(
                    GenerationQuestionState.generation_log_id == log_id,
                    GenerationQuestionState.termination_reason.is_(None),
                )
                .values(
                    processing="ended",
                    current_step=None,
                    termination_reason="cancelled",
                    terminal_json=terminal,
                    updated_at=now,
                )
            )
            await session.commit()
            return {"cancelled": True, "reason": "queued_run_cancelled"}
        # Race: run was claimed between SELECT and UPDATE; fall through to flag-only path.

    # Running run (or race-claimed run): set the flag only.
    if not log.cancel_requested:
        await session.execute(
            update(GenerationLog)
            .where(GenerationLog.id == log_id)
            .values(cancel_requested=True)
        )
        await session.commit()
    return {"cancelled": True}


# ---------------------------------------------------------------------------
# Persisted per-question state
# ---------------------------------------------------------------------------


def _step_for_stage(payload: Mapping[str, Any]) -> str | None:
    """Map an agent stage event to its 生成步驟 (text/subquestions/image/verify/correct)."""
    stage = str(payload.get("stage") or "")
    agent = str(payload.get("agent") or "")
    if agent.startswith("sub_generator#") or stage == "subquestion":
        return "subquestions"
    if agent == "image_agent" or "image" in stage:
        return "image"
    if agent == "verifier" or stage == "verify":
        return "verify"
    if agent == "corrector" or stage == "correct":
        return "correct"
    if agent in ("generator", "execute") or stage in ("llm_generate", "generate"):
        return "text"
    return None


def _unfinished_terminal(reason: str) -> dict[str, Any]:
    """A failed terminal for a question that ended without its own terminal."""
    payload = {
        "termination_reason": "failed",
        "has_final": False,
        "final_revision": None,
        "delivery_status": "unknown",
        "expected": [],
        "delivered": [],
        "missing": [],
        "review": {"status": "unknown", "reason": "no final content"},
        "unknown_reason": reason,
    }
    QuestionTerminalPayload.model_validate(payload)
    return payload


class _QuestionStateRecorder:
    """Translate bus events into persisted 處理狀態, 生成步驟 and 終止原因."""

    def __init__(
        self,
        run_id: uuid.UUID,
        session_factory: Any,
        *,
        confirmed_cancel_event: threading.Event | None = None,
    ) -> None:
        self._run_id = run_id
        self._sessions = session_factory
        self._steps: dict[str, str] = {}
        self._confirmed_cancel_event = confirmed_cancel_event

    async def observe(self, event: Mapping[str, Any]) -> None:
        name = event.get("event")
        context = event.get("context") or {}
        payload = event.get("payload") or {}
        question_id = context.get("question_id")
        if not isinstance(question_id, str):
            return
        if name == SSEEventName.QUESTION_TERMINAL:
            await self._record_terminal(question_id, payload)
        elif name == SSEEventName.ERROR:
            message = payload.get("message") if isinstance(payload, dict) else None
            await self._update_unfinished(question_id, error=str(message or payload))
        elif name == SSEEventName.PIPELINE and payload.get("event_name") == "question_start":
            await self._update_unfinished(question_id, processing="running")
        elif name == SSEEventName.STAGE and payload.get("status") == "start":
            step = _step_for_stage(payload)
            if step is not None and self._steps.get(question_id) != step:
                self._steps[question_id] = step
                await self._update_unfinished(
                    question_id, processing="running", current_step=step
                )

    async def _update_unfinished(self, question_id: str, **values: Any) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(GenerationQuestionState)
                .where(
                    GenerationQuestionState.generation_log_id == self._run_id,
                    GenerationQuestionState.question_id == question_id,
                    GenerationQuestionState.termination_reason.is_(None),
                )
                .values(**values, updated_at=_utcnow())
            )
            await session.commit()
            # Step-boundary cancel check (issue #910): poll DB for cancel_requested.
            if (
                self._confirmed_cancel_event is not None
                and not self._confirmed_cancel_event.is_set()
            ):
                flag = (
                    await session.execute(
                        select(GenerationLog.cancel_requested).where(
                            GenerationLog.id == self._run_id
                        )
                    )
                ).scalar_one_or_none()
                if flag:
                    self._confirmed_cancel_event.set()

    async def _record_terminal(self, question_id: str, terminal: Mapping[str, Any]) -> None:
        """Write the 終止原因 once: the first recorded outcome stands."""
        async with self._sessions() as session:
            record_id = None
            if terminal.get("has_final"):
                record_id = (
                    await session.execute(
                        select(GenerationRecord.id)
                        .where(
                            GenerationRecord.generation_log_id == self._run_id,
                            GenerationRecord.question_id == question_id,
                            GenerationRecord.status == "completed",
                        )
                        .order_by(GenerationRecord.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            await session.execute(
                update(GenerationQuestionState)
                .where(
                    GenerationQuestionState.generation_log_id == self._run_id,
                    GenerationQuestionState.question_id == question_id,
                    GenerationQuestionState.termination_reason.is_(None),
                )
                .values(
                    processing="ended",
                    current_step=None,
                    termination_reason=terminal.get("termination_reason"),
                    terminal_json=dict(terminal),
                    generation_record_id=record_id,
                    updated_at=_utcnow(),
                )
            )
            await session.commit()

    async def fail_unfinished(self, reason: str) -> None:
        """End every question still without a 終止原因 as failed with *reason*."""
        async with self._sessions() as session:
            await session.execute(
                update(GenerationQuestionState)
                .where(
                    GenerationQuestionState.generation_log_id == self._run_id,
                    GenerationQuestionState.termination_reason.is_(None),
                )
                .values(
                    processing="ended",
                    current_step=None,
                    termination_reason="failed",
                    terminal_json=_unfinished_terminal(reason),
                    updated_at=_utcnow(),
                )
            )
            await session.commit()


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class _TimeLimitExceededError(Exception):
    """Internal sentinel: 2-hour wall-clock limit reached for a generation run."""


async def _heartbeat(
    run_id: uuid.UUID,
    host_id: str,
    session_factory: Any,
    *,
    interval: float,
    clock: Clock,
    confirmed_cancel_event: threading.Event | None = None,
    time_limit_exceeded_event: threading.Event | None = None,
    time_limit_s: float = TIME_LIMIT_S,
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            async with session_factory() as session:
                now = clock()
                await session.execute(
                    update(GenerationLog)
                    .where(GenerationLog.id == run_id, GenerationLog.claimed_by == host_id)
                    .values(heartbeat_at=now)
                )
                await session.commit()
                # Check cancel_requested on every heartbeat (issue #910).
                if confirmed_cancel_event is not None and not confirmed_cancel_event.is_set():
                    row = (
                        await session.execute(
                            select(GenerationLog.cancel_requested, GenerationLog.started_at)
                            .where(GenerationLog.id == run_id)
                        )
                    ).one_or_none()
                    if row is not None:
                        flag, started_at = row
                        if flag:
                            confirmed_cancel_event.set()
                        # Issue #911: check per-heartbeat time limit.
                        if (
                            time_limit_exceeded_event is not None
                            and not time_limit_exceeded_event.is_set()
                            and started_at is not None
                        ):
                            elapsed = (now - _utc_aware(started_at)).total_seconds()
                            if elapsed >= time_limit_s:
                                time_limit_exceeded_event.set()
        except Exception as exc:  # noqa: BLE001 — a missed beat must not stop the run
            logger.warning("run heartbeat failed for %s: %s", run_id, type(exc).__name__)


async def execute_run(
    claimed: ClaimedRun,
    *,
    app_state: Any,
    config: ServerConfig,
    session_factory: Any,
    host_id: str,
    client_factory: Callable[..., Any] | None = None,
    subjects: Mapping[str, SubjectSpec] | None = None,
    heartbeat_interval: float = HEARTBEAT_INTERVAL_S,
    clock: Clock = _utcnow,
    time_limit_s: float = TIME_LIMIT_S,
) -> None:
    """Execute one claimed run to the end and persist its outcome."""
    run_str_id = str(claimed.run_id)

    # Issue #911: enforce attempt limit before spending any resources.
    if claimed.attempt > MAX_ATTEMPTS:
        recorder_pre = _QuestionStateRecorder(claimed.run_id, session_factory)
        await recorder_pre.fail_unfinished("recovery_exhausted")
        async with session_factory() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == claimed.run_id)
                .values(status="failed", error="recovery_exhausted", completed_at=clock())
            )
            await session.commit()
        logger.warning(
            "run %s exceeded MAX_ATTEMPTS (%d); marked failed", claimed.run_id, MAX_ATTEMPTS
        )
        return

    # issue #910: a shared event signals the generation pipeline to cancel.
    confirmed_cancel_event = threading.Event()
    # Issue #911: time-limit exceeded event (set by heartbeat or pre-check).
    time_limit_exceeded_event = threading.Event()
    recorder = _QuestionStateRecorder(
        claimed.run_id, session_factory, confirmed_cancel_event=confirmed_cancel_event
    )
    heartbeat = asyncio.create_task(
        _heartbeat(
            claimed.run_id, host_id, session_factory,
            interval=heartbeat_interval,
            clock=clock,
            confirmed_cancel_event=confirmed_cancel_event,
            time_limit_exceeded_event=time_limit_exceeded_event,
            time_limit_s=time_limit_s,
        )
    )
    # Initialise the live observer slot so is_live_available() returns True
    # for this run as soon as execution begins.
    async with _get_lock():
        _live_observers.setdefault(run_str_id, [])
    status = "completed"
    error: str | None = None
    params: GenerateParams | None = None
    try:
        params = GenerateParams.model_validate(claimed.params_json)
        # Check cancel_requested and time limit at the start of execution.
        async with session_factory() as _check_session:
            _row = (
                await _check_session.execute(
                    select(GenerationLog.cancel_requested, GenerationLog.started_at)
                    .where(GenerationLog.id == claimed.run_id)
                )
            ).one_or_none()
            if _row is not None:
                _flag, _started_at = _row
                if _flag:
                    confirmed_cancel_event.set()
                # Issue #911: check 2h limit at execution start too.
                if _started_at is not None:
                    if (clock() - _utc_aware(_started_at)).total_seconds() >= time_limit_s:
                        time_limit_exceeded_event.set()

        # Issue #911: if time limit already exceeded, skip generation.
        if time_limit_exceeded_event.is_set():
            raise _TimeLimitExceededError("time_limit exceeded before generation started")

        # Issue #911: load already-ended question IDs for resume support.
        skip_question_ids: frozenset[str] = frozenset()
        async with session_factory() as _resume_session:
            _ended_rows = (
                await _resume_session.execute(
                    select(GenerationQuestionState.question_id)
                    .where(
                        GenerationQuestionState.generation_log_id == claimed.run_id,
                        GenerationQuestionState.termination_reason.is_not(None),
                    )
                )
            ).scalars().all()
            skip_question_ids = frozenset(_ended_rows)

        async for event in generate_question_stream(
            params,
            config,
            app_state,
            user_id=claimed.user_id,
            generation_log_id=claimed.run_id,
            subjects=subjects,
            session_factory=session_factory,
            client_factory=client_factory,
            confirmed_cancel_event=confirmed_cancel_event,
            skip_question_ids=skip_question_ids,
            attempt=claimed.attempt,
        ):
            # Issue #911: abort stream on time limit.
            if time_limit_exceeded_event.is_set():
                raise _TimeLimitExceededError("time_limit exceeded during generation")
            if event.get("event") == SSEEventName.ERROR:
                status = "failed"
                payload = event.get("payload")
                error = (
                    payload.get("message", str(payload))
                    if isinstance(payload, dict)
                    else str(payload)
                )
            await recorder.observe(event)
            await _publish_live(run_str_id, event)
    except _TimeLimitExceededError:
        status = "failed"
        error = "time_limit"
        logger.info("run %s reached 2h time limit; terminating", claimed.run_id)
    except Exception as exc:  # noqa: BLE001 — the run must still reach an end state
        status = "failed"
        error = f"Run execution failed ({type(exc).__name__})"
        logger.exception("generation run %s failed", claimed.run_id)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        # Publish a sentinel so observers know the stream ended.
        await _publish_live(run_str_id, {"event": "done", "payload": None})
        # Remove the run's observer slot from the registry.
        async with _get_lock():
            _live_observers.pop(run_str_id, None)

    # Cancellation overrides any intermediate "completed"/"failed" status (issue #910).
    if confirmed_cancel_event.is_set() and status != "failed":
        status = "cancelled"
    # Issue #911: time-limit and recovery_exhausted use a specific terminal reason.
    unfinished_reason = error or "question ended without a terminal"
    await recorder.fail_unfinished(unfinished_reason)
    if status == "failed" and params is not None:
        await persist_failed_generation_record(
            user_id=claimed.user_id,
            generation_log_id=claimed.run_id,
            subject=params.subject,
            params=params,
            error=error or "Generation failed",
            session_factory=session_factory,
        )
    async with session_factory() as session:
        await session.execute(
            update(GenerationLog)
            .where(GenerationLog.id == claimed.run_id)
            .values(status=status, error=error, completed_at=clock())
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Host loop
# ---------------------------------------------------------------------------


async def run_host_loop(
    stop_event: asyncio.Event,
    *,
    app_state: Any,
    config: ServerConfig,
    session_factory: Any = None,
    client_factory: Callable[..., Any] | None = None,
    subjects: Mapping[str, SubjectSpec] | None = None,
    host_id: str | None = None,
    max_concurrent_runs: int | None = None,
    idle_interval: float = IDLE_INTERVAL_S,
    heartbeat_interval: float = HEARTBEAT_INTERVAL_S,
    clock: Clock = _utcnow,
) -> None:
    """Claim and execute runs until *stop_event* is set.

    Claims only while fewer than ``max_concurrent_runs`` runs execute here.  On
    stop, runs already executing are awaited so an orderly shutdown lets them
    finish within the platform's drain window.
    """
    sessions = session_factory if session_factory is not None else AsyncSessionLocal
    host = host_id or default_host_id()
    limit = max(
        1,
        max_concurrent_runs
        if max_concurrent_runs is not None
        else config.generation_host_concurrency,
    )
    active: set[asyncio.Task[None]] = set()
    try:
        while not stop_event.is_set():
            claimed = None
            if len(active) < limit:
                try:
                    claimed = await claim_next_run(sessions, host_id=host, now=clock())
                except Exception as exc:  # noqa: BLE001 — keep the host alive
                    logger.warning("run claim failed: %s", type(exc).__name__)
            if claimed is not None:
                task = asyncio.create_task(
                    execute_run(
                        claimed,
                        app_state=app_state,
                        config=config,
                        session_factory=sessions,
                        host_id=host,
                        client_factory=client_factory,
                        subjects=subjects,
                        heartbeat_interval=heartbeat_interval,
                        clock=clock,
                    )
                )
                active.add(task)
                task.add_done_callback(active.discard)
                continue
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=idle_interval)
    finally:
        if active:
            await asyncio.gather(*active, return_exceptions=True)
