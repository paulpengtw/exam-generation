"""Persistence observer that pairs llm_request/llm_response events into DB rows."""

from __future__ import annotations

import itertools
import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

WriteRow = Callable[[dict[str, Any]], None]


class ExchangeRecorder:
    """Pair request/response events without guessing ownership.

    Thread-safe: parallel sub-generators emit interleaved events through
    the same observer. Write failures are logged as warnings and never
    raised — generation must continue even when the DB is unreachable.

    A row with `request_body=NULL` is written if a response arrives with
    no matching request (defensive). If a request never gets a response
    (worker crashed), that row is intentionally not written — the
    generation_log row's `status='failed'` already signals the crash.
    """

    def __init__(
        self,
        generation_log_id: uuid.UUID,
        write_row: WriteRow,
        next_order: Callable[[], int] | None = None,
    ) -> None:
        self._log_id = generation_log_id
        self._write_row = write_row
        # V2 generation events carry explicit run/call identity.  Legacy and
        # modification events do not, so they retain the historical agent key.
        self._pending_by_call: dict[tuple[str, str], dict[str, Any]] = {}
        self._pending_legacy: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        self._next_order = next_order

    def __call__(self, event: dict[str, Any]) -> None:
        try:
            event_type = event.get("type")
            identity = self._identity(event)
            if event_type == "llm_request":
                agent = str(event.get("agent", ""))
                with self._lock:
                    if identity is not None:
                        self._pending_by_call[identity] = event
                    else:
                        self._pending_legacy[agent] = event
                return
            if event_type == "llm_response":
                agent = str(event.get("agent", ""))
                with self._lock:
                    if identity is not None:
                        req = self._pending_by_call.pop(identity, None)
                    else:
                        req = self._pending_legacy.pop(agent, None)
                self._flush(agent, req, event)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("ExchangeRecorder failed to handle event: %s", exc)

    @staticmethod
    def _identity(event: dict[str, Any]) -> tuple[str, str] | None:
        """Return the explicit V2 pairing key, never an inferred fallback."""
        context = event.get("context")
        if not isinstance(context, dict):
            context = event
        run_id = context.get("run_id")
        call_id = context.get("call_id")
        if isinstance(run_id, str) and run_id and isinstance(call_id, str) and call_id:
            return run_id, call_id
        return None

    @classmethod
    def _identity_fields(cls, event: dict[str, Any] | None) -> dict[str, Any]:
        if event is None:
            return {}
        context = event.get("context")
        if not isinstance(context, dict):
            context = event
        return {
            key: context[key]
            for key in (
                "run_id",
                "call_id",
                "operation_id",
                "retry_of_call_id",
            )
            if context.get(key) is not None
        }

    def _flush(
        self,
        agent: str,
        req: dict[str, Any] | None,
        resp: dict[str, Any] | None,
    ) -> None:
        source = req or resp or {}
        usage = (resp or {}).get("usage") if resp else None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        if isinstance(usage, dict):
            prompt_tokens = usage.get("input")
            completion_tokens = usage.get("output")

        if self._next_order is not None:
            order = self._next_order()
        else:
            with self._lock:
                order = next(self._counter)

        row: dict[str, Any] = {
            "generation_log_id": self._log_id,
            "exchange_order": order,
            "agent": agent,
            "purpose": str(source.get("purpose", "")),
            "request_body": (
                {
                    "messages": req.get("messages"),
                    "params": req.get("params"),
                    "model": req.get("model"),
                }
                if req is not None
                else None
            ),
            "response_body": (
                {
                    "content": resp.get("content"),
                    "reasoning": resp.get("reasoning"),
                    "usage": resp.get("usage"),
                }
                if resp is not None
                else None
            ),
            "model_used": str(source.get("model", "")),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
        identity = self._identity_fields(req or resp)
        if identity:
            row.update(identity)
        if req is not None:
            request_identity = self._identity_fields(req)
            if request_identity:
                row["request_body"]["identity"] = request_identity
        if resp is not None:
            response_identity = self._identity_fields(resp)
            if response_identity:
                row["response_body"]["identity"] = response_identity
        try:
            self._write_row(row)
        except Exception as exc:
            logger.warning(
                "ExchangeRecorder write failed (agent=%s, order=%d): %s",
                agent,
                order,
                exc,
            )
