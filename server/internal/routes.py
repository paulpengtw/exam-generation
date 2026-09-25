"""Internal drain telemetry endpoint.

GET /internal/drain — requires X-Drain-Token header equal to
ServerConfig.drain_telemetry_token.  Returns DrainTelemetry.snapshot().

The gateway blocks all /internal/ paths so this endpoint is only
reachable from inside the deployment network.  Enabled only when
drain_telemetry_token is non-empty.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from server.auth.dependencies import get_config
from server.config import ServerConfig
from server.generate.drain import get_drain

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/drain")
async def drain_endpoint(
    request: Request,
    config: ServerConfig = Depends(get_config),
) -> dict:
    """Return the live drain telemetry snapshot for this backend instance.

    Requires DRAIN_TELEMETRY_TOKEN to be set (non-empty) and the header
    X-Drain-Token to match it.  No question text, prompts, or user
    identity is included in the response.
    """
    if not config.drain_telemetry_token:
        raise HTTPException(status_code=404, detail="Drain telemetry endpoint is not enabled.")
    token = request.headers.get("X-Drain-Token", "")
    if token != config.drain_telemetry_token:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Drain-Token header.")
    drain = get_drain(request.app.state)
    return drain.snapshot()
