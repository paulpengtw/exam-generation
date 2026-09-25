"""GenerationPublisher – run-wide monotonic event_seq and v2 envelope emission.

A single GenerationPublisher is created per HTTP request and shared across all
worker threads.  Workers call ``next_seq()`` to obtain the next monotonic integer
and ``publish()`` to enqueue a ``{context, payload}`` envelope via
``loop.call_soon_threadsafe``, which is safe to call from threads that don't own
the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import threading
from typing import Any

from src.common.generation_events import CallScope, OperationScope


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
        subquestion_index: int | None = None,
        operation_id: str | None = None,
        call_id: str | None = None,
        scope: OperationScope | None = None,
        call_scope: CallScope | None = None,
        retry_of_call_id: str | None = None,
        payload: dict[str, Any] | None = None,
        sidecars: dict | None = None,
    ) -> None:
        """Enqueue a v2 ``{context, payload}`` envelope from any thread.

        ``context`` is populated from the publisher's ``run_id`` and the next
        monotonic ``event_seq``; optional per-question fields are included when
        provided.  ``payload`` defaults to an empty dict if omitted.
        """
        if scope is not None:
            if operation_id is not None and operation_id != scope.operation_id:
                raise ValueError("operation_id conflicts with scope")
            operation_id = scope.operation_id
            question_id = question_id if question_id is not None else scope.question_id
            index = index if index is not None else scope.index
            subquestion_index = (
                subquestion_index
                if subquestion_index is not None
                else scope.subquestion_index
            )
        if call_scope is not None:
            if call_id is not None and call_id != call_scope.call_id:
                raise ValueError("call_id conflicts with call_scope")
            call_id = call_scope.call_id
            operation_id = operation_id or call_scope.operation_id
            retry_of_call_id = retry_of_call_id or call_scope.retry_of_call_id

        seq = self.next_seq()
        context: dict[str, Any] = {
            "run_id": self._run_id,
            "event_seq": seq,
        }
        if question_id is not None:
            context["question_id"] = question_id
        if index is not None:
            context["index"] = index
        if content_revision is not None:
            context["content_revision"] = content_revision
        if subquestion_index is not None:
            context["subquestion_index"] = subquestion_index
        if operation_id is not None:
            context["operation_id"] = operation_id
        if call_id is not None:
            context["call_id"] = call_id

        copied_payload = copy.deepcopy(payload) if payload is not None else {}
        if not isinstance(copied_payload, dict):
            raise TypeError("generation event payload must be a dictionary")
        canonical_payload_identity = {
            "run_id": self._run_id,
            "operation_id": operation_id,
            "call_id": call_id,
        }
        for key, value in canonical_payload_identity.items():
            if value is None:
                continue
            if key in copied_payload and copied_payload[key] != value:
                raise ValueError(f"payload {key} conflicts with event context")
        if scope is not None and scope.supersedes_operation_id is not None:
            if event_name == "stage" and copied_payload.get("status") == "start":
                if (
                    "supersedes_operation_id" in copied_payload
                    and copied_payload["supersedes_operation_id"]
                    != scope.supersedes_operation_id
                ):
                    raise ValueError("payload supersedes_operation_id conflicts with scope")
                copied_payload.setdefault(
                    "supersedes_operation_id", scope.supersedes_operation_id
                )
        if retry_of_call_id is not None:
            if (
                "retry_of_call_id" in copied_payload
                and copied_payload["retry_of_call_id"] != retry_of_call_id
            ):
                raise ValueError("payload retry_of_call_id conflicts with call scope")
            copied_payload.setdefault("retry_of_call_id", retry_of_call_id)

        envelope: dict[str, Any] = {
            "event": event_name,      # v1-compatible top-level key
            "context": context,        # v2 metadata
            "payload": copied_payload,
        }
        if sidecars:
            envelope.update(sidecars)

        self._loop.call_soon_threadsafe(self._queue.put_nowait, envelope)
