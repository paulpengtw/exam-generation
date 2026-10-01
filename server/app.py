"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.dependencies import get_config
from server.auth.routes import router as auth_router
from server.config import ServerConfig
from server.db import AsyncSessionLocal, DatabaseUnavailableError
from server.generate.modification_routes import router as modification_router
from server.generate.release_authority import AuthoritySource, build_authority_source
from server.generate.routes import router as generate_router
from server.generate.run import run_host_loop
from server.generation_state import load_generation_state, stop_generation_state
from server.history.routes import router as history_router
from server.internal.routes import router as internal_router
from server.models import GenerationRecord, LLMExchange
from server.observability import init_sentry
from server.rate_limit import limiter
from server.utility.routes import router as utility_router

logger = logging.getLogger(__name__)


async def _prune_generation_records(session: AsyncSession, retention_days: int) -> None:
    """Delete generation_records older than retention_days.

    retention_days == 0 keeps every row (default). Failures are logged
    by the caller so startup never aborts on a prune error.
    """
    if retention_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    await session.execute(
        delete(GenerationRecord).where(GenerationRecord.created_at < cutoff)
    )
    await session.commit()


async def prune_expired_llm_exchanges(
    config: ServerConfig,
    *,
    session_maker=None,
) -> int:
    """Delete llm_exchanges rows older than `LLM_EXCHANGE_RETENTION_DAYS`.

    Returns the number of rows deleted. When retention == 0, persistence is
    disabled entirely — do not delete existing rows either (they remain
    inspectable via the read endpoint until the operator raises retention
    back above zero and old rows exit the window).
    """
    retention = config.llm_exchange_retention_days
    if retention <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
    sm = session_maker or AsyncSessionLocal
    async with sm() as sess:
        result = await sess.execute(
            delete(LLMExchange).where(LLMExchange.created_at < cutoff)
        )
        await sess.commit()
        return result.rowcount or 0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config: ServerConfig = get_config()

    try:
        from alembic.config import Config as AlembicConfig

        from alembic import command

        def _run_alembic() -> None:
            alembic_cfg = AlembicConfig(
                str(Path(__file__).resolve().parent.parent / "alembic.ini")
            )
            command.upgrade(alembic_cfg, "head")

        # alembic env.py uses asyncio.run; run in a worker thread so it gets its own loop.
        await asyncio.to_thread(_run_alembic)

        try:
            async with AsyncSessionLocal() as session:
                await _prune_generation_records(
                    session, config.generation_history_retention_days
                )
        except Exception as exc:  # pragma: no cover - best effort on startup
            print(
                f"Warning: generation_records prune failed: {exc}", file=sys.stderr
            )
    except Exception as exc:  # pragma: no cover - best effort on startup
        print(f"Warning: alembic upgrade failed: {exc}", file=sys.stderr)

    try:
        deleted = await prune_expired_llm_exchanges(config)
        if deleted:
            print(f"Pruned {deleted} expired llm_exchanges rows")
    except Exception as exc:  # pragma: no cover - best effort
        print(f"Warning: llm_exchanges pruning failed: {exc}", file=sys.stderr)

    load_generation_state(app.state, config)

    # The 生成執行 host (ADR 0034). GENERATION_HOST_ENABLED=false moves it to
    # `python -m server.worker` and doubles as the emergency stop.
    host_stop = asyncio.Event()
    host_task: asyncio.Task[None] | None = None
    if config.generation_host_enabled:
        host_task = asyncio.create_task(
            run_host_loop(host_stop, app_state=app.state, config=config)
        )

    try:
        yield
    finally:
        host_stop.set()
        if host_task is not None:
            await host_task
        stop_generation_state(app.state)


def create_app(*, release_authority_source: AuthoritySource | None = None) -> FastAPI:
    init_sentry()
    app = FastAPI(title="Exam Generation API", lifespan=lifespan)

    app.state.limiter = limiter

    def _rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded: {exc.detail}"},
        )

    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    def _database_unavailable_handler(
        _request: Request, _exc: DatabaseUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Database temporarily unavailable; please retry.",
                "code": "DATABASE_UNAVAILABLE",
            },
            headers={"Retry-After": "5"},
        )

    app.add_exception_handler(DatabaseUnavailableError, _database_unavailable_handler)

    def _unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        # Starlette re-raises after this response; Sentry's outer ASGI wrapper captures once.
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    app.add_exception_handler(Exception, _unhandled_exception_handler)
    app.add_middleware(SlowAPIMiddleware)

    config = get_config()
    app.state.release_authority_source = (
        release_authority_source
        if release_authority_source is not None
        else build_authority_source(
            config.release_authority_url,
            config.release_authority_path,
        )
    )
    allow_origins = [config.frontend_url] if config.frontend_url else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(generate_router)
    app.include_router(modification_router)
    app.include_router(history_router)
    app.include_router(internal_router)
    app.include_router(utility_router)
    return app


app = create_app()
