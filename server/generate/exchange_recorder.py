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
    """Buffer llm_request events per-agent, write one row on llm_response.

    Thread-safe: parallel sub-generators emit interleaved events through
    the same observer. Write failures are logged as warnings and never
    raised — generation must continue even when the DB is unreachable.

    A row with `request_body=NULL` is written if a response arrives with
    no matching request (defensive). If a request never gets a response
    (worker crashed), that row is intentionally not written — the
    generation_log row's `status='failed'` already signals the crash.
    """

    def __init__(self, generation_log_id: uuid.UUID, write_row: WriteRow) -> None:
        self._log_id = generation_log_id
        self._write_row = write_row
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    def __call__(self, event: dict[str, Any]) -> None:
        try:
            event_type = event.get("type")
            if event_type == "llm_request":
                agent = str(event.get("agent", ""))
                with self._lock:
                    self._pending[agent] = event
                return
            if event_type == "llm_response":
                agent = str(event.get("agent", ""))
                with self._lock:
                    req = self._pending.pop(agent, None)
                self._flush(agent, req, event)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("ExchangeRecorder failed to handle event: %s", exc)

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
        try:
            self._write_row(row)
        except Exception as exc:
            logger.warning(
                "ExchangeRecorder write failed (agent=%s, order=%d): %s",
                agent,
                order,
                exc,
            )
