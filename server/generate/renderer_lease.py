"""Per-render renderer pool lease (issue #700 option 2).

Exposes the same ``render(html, output_path, width=800)`` interface as
``PlaywrightRenderer``, but borrows from a pooled renderer for exactly the
duration of one HTML render and returns it immediately after.  The pool is
never held for the lifetime of the stream, so an aborted run releases within
one render, not when its worker thread exits.

Thread-safety model
-------------------
All ``asyncio.Queue`` operations are performed inside a single ``_acquire``
coroutine that runs entirely on the event loop.  The coroutine is submitted
once via ``run_coroutine_threadsafe`` and is **never cancelled** from the
worker thread: cancelling a ``concurrent.futures.Future`` after the loop-side
task completes causes ``_chain_future`` to drop the result, permanently losing
a renderer (Race 2).  The worker calls ``future.result(timeout=...)``
repeatedly only to decide when to emit warning events; it stops when the
future resolves, which is guaranteed to happen because ``_acquire`` keeps
looping until it either obtains a renderer or observes ``cancel_event``.

The ``cancel_event`` is a plain ``threading.Event``, safe to read from both
the event loop coroutine and any worker thread.  The ``queue`` used for SSE
stage events is the stream's own asyncio Queue; writes go through
``loop.call_soon_threadsafe`` so the event loop thread owns every mutation.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.generate.publisher import GenerationPublisher

logger = logging.getLogger(__name__)

# Short polling interval while waiting for a pooled renderer.
_POLL_SLICE_S: float = 0.05


async def _acquire(
    pool: asyncio.Queue,
    cancel_event: Any,
    slice_s: float,
) -> Any:  # noqa: ASYNC109
    """Acquire a renderer from *pool*, running entirely on the event loop.

    Returns a renderer when one becomes available, or ``None`` when
    *cancel_event* is set (stream cancelled -- the caller should skip render).

    This coroutine is submitted **once** via ``run_coroutine_threadsafe``.
    The caller must NEVER cancel the resulting future: if the future is
    cancelled after this coroutine has already completed ``get_nowait()``,
    ``_chain_future`` drops the obtained renderer and it is permanently lost.
    """
    while True:
        try:
            return pool.get_nowait()
        except asyncio.QueueEmpty:
            pass
        if cancel_event.is_set():
            return None
        await asyncio.sleep(slice_s)


class RendererLease:
    """Per-render borrow from a renderer pool.

    Call :meth:`render` from a worker thread; it borrows a renderer for exactly
    the duration of one render and returns it.  When the pool is empty on entry,
    it emits ``renderer/acquire/start`` to the stream queue, polls with
    ``_POLL_SLICE_S`` slices while checking ``cancel_event``, and emits
    ``renderer/acquire/end`` once it obtains a renderer.  Stage events are
    never emitted when a renderer is immediately available.

    Parameters
    ----------
    pool:
        ``asyncio.Queue`` of ``PlaywrightRenderer`` objects.
    loop:
        The event loop on which *pool* lives.
    cancel_event:
        ``threading.Event`` set when the stream is aborted.
    queue:
        ``asyncio.Queue`` used by the stream to emit SSE events.  Stage events
        are put here via ``loop.call_soon_threadsafe`` from the worker thread.
    publisher:
        Optional :class:`~server.generate.publisher.GenerationPublisher`.  When
        provided, stage events are emitted as v2 envelopes via the publisher
        (batch-scoped, no ``question_id``).  When ``None``, the legacy v1 dict
        is enqueued directly onto *queue* (backward-compat for callers that do
        not yet supply a publisher).
    """

    def __init__(
        self,
        pool: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        cancel_event: Any,  # threading.Event
        queue: asyncio.Queue,
        *,
        publisher: GenerationPublisher | None = None,
    ) -> None:
        self._pool = pool
        self._loop = loop
        self._cancel_event = cancel_event
        self._queue = queue
        self._publisher = publisher

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_stage(self, agent: str, stage: str, status: str) -> None:
        """Thread-safe: enqueue a stage event onto the stream's SSE queue.

        When a publisher is available the event is emitted as a v2 envelope
        (batch-scoped, monotonic ``event_seq``).  Otherwise falls back to the
        legacy v1 ``{'event': STAGE, 'data': {...}}`` dict.
        """
        from server.generate.marshalling import SSEEventName  # noqa: PLC0415

        payload = {
            "type": "stage",
            "agent": agent,
            "stage": stage,
            "status": status,
            "ts": time.time(),
        }

        if self._publisher is not None:
            # v2 path: route through publisher for monotonic event_seq.
            # publish() calls loop.call_soon_threadsafe internally.
            self._publisher.publish(SSEEventName.STAGE, payload=payload)
        else:
            # Legacy v1 path: enqueue directly (no publisher available).
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait,
                {
                    "event": SSEEventName.STAGE,
                    "data": payload,
                },
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def render(self, html: str, output_path: str | Path, width: int = 800) -> str | None:
        """Borrow a renderer, render, return it.  Called from a worker thread.

        Returns the rendered output path on success, or ``None`` when the run
        is cancelled while waiting for a renderer (the caller should treat
        ``None`` the same as when ``html_renderer`` is ``None`` on the context).

        A single ``_acquire`` coroutine runs on the event loop and is never
        cancelled: that avoids the ``_chain_future`` drop that would permanently
        lose a renderer (Race 2).  The worker polls ``future.result(timeout=...)``
        only to decide when to emit warning events; it NEVER cancels the future
        and NEVER stops waiting before it resolves.

        The warning threshold is read from
        ``server.generate.service.RENDERER_POOL_WAIT_WARN_THRESHOLD_S`` at
        call time so that tests can monkeypatch it on that module.
        """
        from server.generate.service import RENDERER_POOL_WAIT_WARN_THRESHOLD_S  # noqa: PLC0415

        loop = self._loop
        pool = self._pool
        cancel_event = self._cancel_event

        # Submit _acquire once; poll for timing signals without ever cancelling.
        future: concurrent.futures.Future[Any] = asyncio.run_coroutine_threadsafe(
            _acquire(pool, cancel_event, _POLL_SLICE_S),
            loop,
        )

        start_time = time.monotonic()
        warned = False
        emitted_start = False

        while True:
            try:
                renderer = future.result(timeout=_POLL_SLICE_S)
                break
            except concurrent.futures.TimeoutError:
                pass

            # First timeout: pool was not immediately available; emit acquire/start.
            if not emitted_start:
                emitted_start = True
                self._emit_stage("renderer", "acquire", "start")

            elapsed = time.monotonic() - start_time
            if not warned and elapsed >= RENDERER_POOL_WAIT_WARN_THRESHOLD_S:
                warned = True
                logger.warning(
                    "renderer pool wait exceeded %.1f s — pool may be exhausted "
                    "(issue #700); continuing to wait",
                    RENDERER_POOL_WAIT_WARN_THRESHOLD_S,
                )

        if renderer is None:
            # Cancelled: _acquire returned None because cancel_event was set.
            return None

        if emitted_start:
            self._emit_stage("renderer", "acquire", "end")

        try:
            return renderer.render(html, output_path, width)
        finally:
            loop.call_soon_threadsafe(pool.put_nowait, renderer)
