"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from server.auth.routes import router as auth_router
from server.utility.routes import router as utility_router


def create_app() -> FastAPI:
    app = FastAPI(title="Exam Generation API")
    app.include_router(auth_router)
    app.include_router(utility_router)
    return app


app = create_app()
