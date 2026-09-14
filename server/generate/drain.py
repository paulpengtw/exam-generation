"""Drain telemetry — per-instance live-work counters for release control.

Used by operators to confirm that all in-flight generation work and delivery
have truly ended before reopening admission after a pause.  All counters are
thread-safe; snapshot() may be called from any thread or coroutine.
"""

from __future__ import annotations

import os
import socket
import threading
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any


def _app_version() -> str | None:
    for var in ("APP_VERSION", "RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA"):
        v = os.environ.get(var)
        if v:
            return v
    return None


class DrainTelemetry:
    """Thread-safe live-work counters attached to one backend instance.

    All ``ctx_*`` context managers are safe to call from worker threads and
    async tasks; they use a single lock for all counter mutations.

    Parameters
    ----------
    instance_id:
        Optional override for the instance UUID (used in tests).
    """

    def __init__(self, *, instance_id: str | None = None) -> None:
        self._lock = threading.Lock()
        self._active_runs = 0
        self._active_workers = 0
        self._open_streams = 0
        self._renderer_leases_held = 0
        self._pending_persistence = 0

        # Registered asyncio.Queue objects for pending_deliveries sampling
        self._queues: list[Any] = []

        # Stable identity — fixed at construction
        self.instance_id: str = instance_id or str(uuid.uuid4())
        self.hostname: str = socket.gethostname()
        self.pid: int = os.getpid()
        self.started_at: str = datetime.now(UTC).isoformat()
        self.app_version: str | None = _app_version()
        self.supported_stream_versions: list[int] = [1]

    # ------------------------------------------------------------------
    # Internal counter helpers
    # ------------------------------------------------------------------

    def _inc(self, attr: str) -> None:
        with self._lock:
            setattr(self, attr, getattr(self, attr) + 1)

    def _dec(self, attr: str) -> None:
        with self._lock:
            new = getattr(self, attr) - 1
            if new < 0:
                new = 0
            setattr(self, attr, new)

    # ------------------------------------------------------------------
    # Context managers (safe to use from threads or coroutines)
    # ------------------------------------------------------------------

    @contextmanager
    def ctx_active_run(self) -> Generator[None, None, None]:
        """Track one generate_question_stream invocation."""
        self._inc("_active_runs")
        try:
            yield
        finally:
            self._dec("_active_runs")

    @contextmanager
    def ctx_active_worker(self) -> Generator[None, None, None]:
        """Track one _worker_one invocation (including its finally)."""
        self._inc("_active_workers")
        try:
            yield
        finally:
            self._dec("_active_workers")

    @contextmanager
    def ctx_open_stream(self) -> Generator[None, None, None]:
        """Track one event_generator that is open to the client."""
        self._inc("_open_streams")
        try:
            yield
        finally:
            self._dec("_open_streams")

    @contextmanager
    def ctx_renderer_lease(self) -> Generator[None, None, None]:
        """Track one renderer borrow from the pool."""
        self._inc("_renderer_leases_held")
        try:
            yield
        finally:
            self._dec("_renderer_leases_held")

    # ------------------------------------------------------------------
    # Persistence counter (called from persistence helpers)
    # ------------------------------------------------------------------

    def inc_pending_persistence(self) -> None:
        with self._lock:
            self._pending_persistence += 1

    def dec_pending_persistence(self) -> None:
        with self._lock:
            new = self._pending_persistence - 1
            self._pending_persistence = max(0, new)

    # ------------------------------------------------------------------
    # Queue registry for pending_deliveries sampling
    # ------------------------------------------------------------------

    def register_queue(self, q: Any) -> None:
        """Register an asyncio.Queue so its qsize() contributes to pending_deliveries."""
        with self._lock:
            self._queues.append(q)

    def unregister_queue(self, q: Any) -> None:
        """Unregister a queue when its run exits."""
        with self._lock:
            try:
                self._queues.remove(q)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Return a point-in-time snapshot safe to serialise to JSON."""
        with self._lock:
            pending_deliveries = sum(q.qsize() for q in self._queues)
            active_runs = self._active_runs
            active_workers = self._active_workers
            open_streams = self._open_streams
            renderer_leases_held = self._renderer_leases_held
            pending_persistence = self._pending_persistence

        quiescent = (
            active_runs == 0
            and active_workers == 0
            and open_streams == 0
            and renderer_leases_held == 0
            and pending_persistence == 0
            and pending_deliveries == 0
        )

        return {
            "instance_id": self.instance_id,
            "hostname": self.hostname,
            "pid": self.pid,
            "started_at": self.started_at,
            "app_version": self.app_version,
            "supported_stream_versions": self.supported_stream_versions,
            "captured_at": datetime.now(UTC).isoformat(),
            "active_runs": active_runs,
            "active_workers": active_workers,
            "open_streams": open_streams,
            "pending_deliveries": pending_deliveries,
            "pending_persistence": pending_persistence,
            "renderer_leases_held": renderer_leases_held,
            "quiescent": quiescent,
        }


class _NoopDrainTelemetry:
    """Drop-in no-op that satisfies the DrainTelemetry interface without tracking."""

    def _inc(self, attr: str) -> None:
        pass

    def _dec(self, attr: str) -> None:
        pass

    def ctx_active_run(self):  # noqa: ANN201
        from contextlib import nullcontext
        return nullcontext()

    def ctx_active_worker(self):  # noqa: ANN201
        from contextlib import nullcontext
        return nullcontext()

    def ctx_open_stream(self):  # noqa: ANN201
        from contextlib import nullcontext
        return nullcontext()

    def ctx_renderer_lease(self):  # noqa: ANN201
        from contextlib import nullcontext
        return nullcontext()

    def inc_pending_persistence(self) -> None:
        pass

    def dec_pending_persistence(self) -> None:
        pass

    def register_queue(self, q: Any) -> None:
        pass

    def unregister_queue(self, q: Any) -> None:
        pass

    def snapshot(self) -> dict:
        return {}


NOOP_DRAIN: _NoopDrainTelemetry = _NoopDrainTelemetry()


def get_drain(app_state: Any) -> DrainTelemetry | _NoopDrainTelemetry:
    """Return the app's DrainTelemetry or the no-op singleton."""
    return getattr(app_state, "drain_telemetry", NOOP_DRAIN)
