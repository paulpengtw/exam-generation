"""GenerationPublisher – run-wide monotonic event_seq and v2 envelope emission.

A single GenerationPublisher is created per HTTP request and shared across all
worker threads.  Workers call ``next_seq()`` to obtain the next monotonic integer
and ``publish()`` to enqueue a ``{context, payload}`` envelope via
``loop.call_soon_threadsafe``, which is safe to call from threads that don't own
the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
from typing import Any


class GenerationPublisher:
    """Thread-safe monotonic publisher for SSE stream v2 envelopes."""

    def __init__(
        self,
        run_id: str,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
    ) -> None:
        self._run_id = run_id
        self._loop = loop
        self._queue = queue
        self._counter = itertools.count(1)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def next_seq(self) -> int:
        """Return the next monotonic event_seq (thread-safe, starts at 1)."""
        with self._lock:
            return next(self._counter)

    def publish(
        self,
        event_name: str,
        *,
        question_id: str | None = None,
        index: int | None = None,
        content_revision: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Enqueue a v2 ``{context, payload}`` envelope from any thread.

        ``context`` is populated from the publisher's ``run_id`` and the next
        monotonic ``event_seq``; optional per-question fields are included when
        provided.  ``payload`` defaults to an empty dict if omitted.
        """
        seq = self.next_seq()
        context: dict[str, Any] = {
            "run_id": self._run_id,
            "event_seq": seq,
            "event": event_name,
        }
        if question_id is not None:
            context["question_id"] = question_id
        if index is not None:
            context["index"] = index
        if content_revision is not None:
            context["content_revision"] = content_revision

        envelope: dict[str, Any] = {
            "event": event_name,      # v1-compatible top-level key
            "context": context,        # v2 metadata
            "payload": dict(payload) if payload is not None else {},
        }

        self._loop.call_soon_threadsafe(self._queue.put_nowait, envelope)
