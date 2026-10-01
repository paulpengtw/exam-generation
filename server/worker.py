"""Standalone 生成執行 host: ``python -m server.worker``.

Runs the same ``run_host_loop`` as the backend's lifespan (ADR 0034).  Splitting
generation onto a separate service is configuration only: run this entry point
with the backend's image and set ``GENERATION_HOST_ENABLED=false`` on the
backend.  Schema migrations stay with the backend's startup.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from types import SimpleNamespace

from server.config import ServerConfig
from server.generate.run import run_host_loop
from server.generation_state import load_generation_state, stop_generation_state
from server.observability import init_sentry

logger = logging.getLogger(__name__)


async def run_worker(stop_event: asyncio.Event, config: ServerConfig) -> None:
    """Load generation state and host runs until *stop_event* is set."""
    state = SimpleNamespace()
    load_generation_state(state, config)
    try:
        await run_host_loop(stop_event, app_state=state, config=config)
    finally:
        stop_generation_state(state)


async def _main() -> None:
    config = ServerConfig.from_env()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    logger.info("generation worker started")
    await run_worker(stop, config)
    logger.info("generation worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_sentry()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
