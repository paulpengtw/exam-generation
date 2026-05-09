"""Generate routes — GET /api/generate SSE endpoint."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import AsyncSessionLocal, get_async_session
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.models import GenerationLog, User

router = APIRouter(prefix="/api", tags=["generate"])


def _serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Convert internal event dict to sse_starlette ServerSentEvent fields."""
    data = event.get("data", "")
    if not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False)
    return {"event": event["event"], "data": data}


@router.get("/generate")
async def generate_endpoint(
    request: Request,
    grade: int | None = Query(default=None),
    style: list[str] | None = Query(default=None),
    context: list[str] | None = Query(default=None),
    set_type: str | None = Query(default=None),
    q_type: list[str] | None = Query(default=None),
    count: int = Query(default=1, ge=1),
    skip_verify: bool = Query(default=False),
    seed: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    config: ServerConfig = Depends(get_config),
) -> EventSourceResponse:
    """Stream question generation events as Server-Sent Events.

    Logs the request to `generation_log` at start and updates the row to
    `completed` or `failed` when the stream ends.
    """
    params = GenerateParams(
        grade=grade,
        style=style,
        context=context,
        set_type=set_type,
        q_type=q_type,
        count=count,
        skip_verify=skip_verify,
        seed=seed,
    )

    log = GenerationLog(
        user_id=user.id,
        params_json=params.model_dump(mode="json"),
        status="started",
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    log_id = log.id

    app_state = request.app.state

    async def event_generator() -> AsyncIterator[dict[str, Any]]:
        status = "completed"
        error_msg: str | None = None
        try:
            async for event in generate_question_stream(params, config, app_state):
                if event["event"] == "error":
                    status = "failed"
                    error_msg = str(event.get("data", ""))
                yield _serialize_event(event)
        except Exception as exc:
            status = "failed"
            error_msg = f"{type(exc).__name__}: {exc}"
            yield {"event": "error", "data": error_msg}
            yield {"event": "done", "data": ""}
        finally:
            async with AsyncSessionLocal() as s:
                await s.execute(
                    update(GenerationLog)
                    .where(GenerationLog.id == log_id)
                    .values(
                        status=status,
                        error=error_msg,
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await s.commit()

    return EventSourceResponse(event_generator())
