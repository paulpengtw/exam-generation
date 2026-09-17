"""Minimal FastAPI app that mounts server.internal router with real DrainTelemetry.

Invoked as:
    uv run python -m tests.release_control._instance_runner <port>

or via subprocess.Popen:
    [sys.executable, "-m", "tests.release_control._instance_runner", "<port>"]

Environment variables:
    DRAIN_TELEMETRY_TOKEN  — the token required for /internal/drain (required)

The server binds to 0.0.0.0:<port> and is ready when it prints 'READY' to stdout.
"""
from __future__ import annotations

import os
import sys

import uvicorn
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Build the app
# ---------------------------------------------------------------------------


def create_runner_app() -> FastAPI:
    """Create a minimal FastAPI app exposing /internal/drain."""
    from server.config import ServerConfig
    from server.generate.drain import DrainTelemetry
    from server.internal.routes import router as internal_router

    token = os.environ.get("DRAIN_TELEMETRY_TOKEN", "")
    if not token:
        raise RuntimeError("DRAIN_TELEMETRY_TOKEN must be set")

    app = FastAPI()

    # Attach the drain telemetry and config so the router dependency resolves
    drain = DrainTelemetry()
    app.state.drain_telemetry = drain

    # Minimal ServerConfig with just the drain token
    from pathlib import Path
    config = ServerConfig(
        api_key="not-used",
        drain_telemetry_token=token,
        output_dir=Path("/tmp"),
        data_dir=Path("data"),
    )
    app.state.config = config

    # Override the get_config dependency to return our config
    from server.auth.dependencies import get_config

    app.dependency_overrides[get_config] = lambda: config

    app.include_router(internal_router)
    return app


app = create_runner_app()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m tests.release_control._instance_runner <port>", file=sys.stderr)
        sys.exit(1)
    port = int(sys.argv[1])

    # Signal readiness BEFORE uvicorn starts (uvicorn will print its own logs)
    # We rely on uvicorn's startup; the test polls until the port is up.
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
