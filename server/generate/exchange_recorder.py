"""Persistence observer that pairs llm_request/llm_response events into DB rows."""

from __future__ import annotations

import asyncio
import itertools
import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

logger = logging.getLogger(__name__)

WriteRow = Callable[[dict[str, Any]], Any]


class ExchangeRecorder:
    """Pair request/response events without guessing ownership.

    Thread-safe: parallel sub-generators emit interleaved events through
    the same observer. Write failures are logged as warnings and never
    raised — generation must continue even when the DB is unreachable.

    A row with `request_body=NULL` is written if a response arrives with
    no matching request (defensive). If a request never gets a response
    (worker crashed), that row is intentionally not written — the
    generation_log row's `status='failed'` already signals the crash.

    Callers that own the event-loop-backed write sink should await ``flush()``
    after worker activity so writes get a bounded chance to finish before the
    run ends. Writes that outlive that chance continue in the background.
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
        self._pending_writes: set[Future[Any]] = set()

    def track_write(self, future: Future[Any]) -> None:
        """Retain a cross-thread write until its eventual completion."""
        with self._lock:
            self._pending_writes.add(future)
        future.add_done_callback(self._forget_write)

    def _forget_write(self, future: Future[Any]) -> None:
        with self._lock:
            self._pending_writes.discard(future)

    async def flush(self) -> None:
        """Await all writes that were still in flight when this is called.

        The write callback is intentionally best effort.  Its completion callback
        logs failures, while one failed write does not prevent sibling writes
        from being drained. The deadline applies to the complete set of writes,
        rather than once per write.
        """
        with self._lock:
            pending = tuple(self._pending_writes)
        if not pending:
            return

        # Import at call time so tests and deployments can change the existing
        # persistence timeout without creating a module import cycle.
        from server.generate import persistence

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, float(persistence.EXCHANGE_WRITE_TIMEOUT_SECONDS))
        wrapped = tuple(asyncio.wrap_future(future, loop=loop) for future in pending)
        done, not_done = await asyncio.wait(
            wrapped,
            timeout=max(0.0, deadline - loop.time()),
        )

        def _consume_late_result(future: asyncio.Future[Any]) -> None:
            try:
                future.result()
            except BaseException:
                # The persistence sink's completion callback owns the
                # eventual diagnostic; never surface content-bearing future
                # exceptions through asyncio's unhandled-future handler.
                pass

        for future in done:
            try:
                future.result()
            except BaseException as outcome:
                logger.warning(
                    "ExchangeRecorder write drain failed: %s",
                    type(outcome).__name__,
                )
        for future in not_done:
            future.add_done_callback(_consume_late_result)
        if not_done:
            with self._lock:
                still_pending = sum(not future.done() for future in pending)
            if still_pending:
                logger.warning(
                    "ExchangeRecorder flush timed out (pending_writes=%d)",
                    still_pending,
                )

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
                return
            if event_type == "llm_failure":
                agent = str(event.get("agent", ""))
                with self._lock:
                    if identity is not None:
                        req = self._pending_by_call.pop(identity, None)
                    else:
                        req = self._pending_legacy.pop(agent, None)
                self._flush_failure(agent, req, event)
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
                    **(
                        {"requested_model": req["requested_model"]}
                        if req.get("requested_model") is not None
                        else {}
                    ),
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
            write_result = self._write_row(row)
            if isinstance(write_result, Future):
                self.track_write(write_result)
        except Exception as exc:
            logger.warning(
                "ExchangeRecorder write failed (agent=%s, order=%d): %s",
                agent,
                order,
                exc,
            )

    def _flush_failure(
        self,
        agent: str,
        req: dict[str, Any] | None,
        failure_event: dict[str, Any],
    ) -> None:
        """Persist a failed provider call as an LLMExchange row.

        The row uses request_body from the matching pending request (if any)
        and encodes the ProviderErrorDetail fields in response_body["error"].
        prompt_tokens and completion_tokens are always None — no completion
        occurred.
        """
        _DETAIL_KEYS = (
            "provider",
            "model",
            "http_status",
            "provider_error_type",
            "provider_error_code",
            "provider_error_status",
            "provider_message",
            "request_id",
            "retry_after_seconds",
            "raw_body_truncated",
            "error_type",
        )

        if self._next_order is not None:
            order = self._next_order()
        else:
            with self._lock:
                order = next(self._counter)

        source = req or failure_event
        error_body: dict[str, Any] = {
            k: failure_event.get(k) for k in _DETAIL_KEYS if k in failure_event
        }

        response_body: dict[str, Any] = {"error": error_body}
        failure_identity = self._identity_fields(failure_event)
        if failure_identity:
            response_body["identity"] = failure_identity

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
                    **(
                        {"requested_model": req["requested_model"]}
                        if req.get("requested_model") is not None
                        else {}
                    ),
                }
                if req is not None
                else None
            ),
            "response_body": response_body,
            "model_used": str(source.get("model", "")),
            "prompt_tokens": None,
            "completion_tokens": None,
        }
        identity = self._identity_fields(req or failure_event)
        if identity:
            row.update(identity)
        if req is not None:
            request_identity = self._identity_fields(req)
            if request_identity:
                if row["request_body"] is not None:
                    row["request_body"]["identity"] = request_identity

        try:
            write_result = self._write_row(row)
            if isinstance(write_result, Future):
                self.track_write(write_result)
        except Exception as exc:
            logger.warning(
                "ExchangeRecorder write failed for llm_failure (agent=%s, order=%d): %s",
                agent,
                order,
                exc,
            )
