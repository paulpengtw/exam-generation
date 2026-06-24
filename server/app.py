"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import sys
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from server.auth.dependencies import get_config
from server.auth.routes import router as auth_router
from server.config import ServerConfig
from server.generate.routes import router as generate_router
from server.rate_limit import limiter
from server.utility.routes import router as utility_router
from src.data_loader import (
    get_grade_content,
    load_curriculum,
    load_intro_text,
    load_performance_standards,
)
from src.html_renderer import PlaywrightRenderer
from src.schema_loader import load_grades, load_schemas


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
    except Exception as exc:  # pragma: no cover - best effort on startup
        print(f"Warning: alembic upgrade failed: {exc}", file=sys.stderr)

    curriculum = load_curriculum(config.data_dir / "curriculum" / "學習內容.json")
    performance = load_performance_standards(config.data_dir / "curriculum" / "學習表現.json")
    intro_text = load_intro_text(Path('Introduction to "學習表現" and "學習階段".md'))
    grades = load_grades(load_schemas(config.question_schemas_path))
    grade_content = {g: get_grade_content(curriculum, g) for g in grades}

    app.state.curriculum = curriculum
    app.state.performance = performance
    app.state.intro_text = intro_text
    app.state.grade_content = grade_content
    print(f"Curriculum loaded: {len(curriculum)} grade entries, target grades {grades}")

    renderer_pool: asyncio.Queue[PlaywrightRenderer] = asyncio.Queue()
    started_renderers: list[PlaywrightRenderer] = []
    for _ in range(2):
        try:
            r = PlaywrightRenderer()
            r.start()
            renderer_pool.put_nowait(r)
            started_renderers.append(r)
        except Exception as exc:
            print(f"Warning: Playwright failed to start: {exc}", file=sys.stderr)
            break
    app.state.renderer_pool = renderer_pool if started_renderers else None
    app.state.html_renderer = None  # legacy; service.py uses renderer_pool
    if started_renderers:
        print(f"Playwright renderer pool started ({len(started_renderers)} instances)")

    try:
        yield
    finally:
        if app.state.renderer_pool is not None:
            while not app.state.renderer_pool.empty():
                r = app.state.renderer_pool.get_nowait()
                try:
                    r.stop()
                except Exception as exc:  # pragma: no cover
                    print(f"Warning: Playwright shutdown failed: {exc}", file=sys.stderr)


def create_app() -> FastAPI:
    app = FastAPI(title="Exam Generation API", lifespan=lifespan)

    app.state.limiter = limiter

    def _rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded: {exc.detail}"},
        )

    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    def _unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    app.add_exception_handler(Exception, _unhandled_exception_handler)
    app.add_middleware(SlowAPIMiddleware)

    config = get_config()
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
    app.include_router(utility_router)
    return app


app = create_app()
