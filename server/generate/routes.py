"""Generate routes — GET /api/generate SSE endpoint."""

from __future__ import annotations

import json
import logging
import traceback
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
from server.generate.models import (
    GenerateParams,
    ImageGenerationMode,
    PlanCoreQuestionsRequest,
    PlanCoreQuestionsResponse,
)
from server.generate.service import generate_question_stream
from server.models import GenerationLog, User
from server.rate_limit import jwt_user_key, limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])


def _serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Convert internal event dict to sse_starlette ServerSentEvent fields."""
    data = event.get("data", "")
    if not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False)
    return {"event": event["event"], "data": data}


@router.get("/generate")
@limiter.limit("10/hour", key_func=jwt_user_key)
async def generate_endpoint(
    request: Request,
    subject: str = Query(default="math"),
    grade: int | None = Query(default=None),
    style: list[str] | None = Query(default=None),
    context: list[str] | None = Query(default=None),
    set_type: str | None = Query(default=None),
    q_type: list[str] | None = Query(default=None),
    count: int = Query(default=1, ge=1),
    skip_verify: bool = Query(default=False),
    seed: int | None = Query(default=None),
    image_generation_mode: ImageGenerationMode = Query(default="html"),
    subject_filter: list[str] | None = Query(default=None),
    content_type: str | None = Query(default=None),
    passage: str | None = Query(default=None),
    options: list[str] | None = Query(default=None),
    topic: str | None = Query(default=None),
    core_question: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    config: ServerConfig = Depends(get_config),
) -> EventSourceResponse:
    """Stream question generation events as Server-Sent Events.

    Logs the request to `generation_log` at start and updates the row to
    `completed` or `failed` when the stream ends.
    """
    params = GenerateParams(
        subject=subject,
        grade=grade,
        style=style,
        context=context,
        set_type=set_type,
        q_type=q_type,
        count=count,
        skip_verify=skip_verify,
        seed=seed,
        image_generation_mode=image_generation_mode,
        subject_filter=subject_filter,
        content_type=content_type,
        passage=passage,
        options=options,
        topic=topic,
        core_question=core_question,
    )
    logger.info("generate request user=%s params=%s", user.email, params.model_dump(mode="json"))

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
            tb = traceback.format_exc()
            error_msg = f"{type(exc).__name__}: {exc}\n\n{tb}"
            logger.exception("generate_endpoint stream error")
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

    return EventSourceResponse(
        event_generator(),
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.post("/plan-core-questions", response_model=PlanCoreQuestionsResponse)
@limiter.limit("30/hour", key_func=jwt_user_key)
async def plan_core_questions_endpoint(
    request: Request,
    body: PlanCoreQuestionsRequest,
    user: User = Depends(get_current_user),
    config: ServerConfig = Depends(get_config),
) -> PlanCoreQuestionsResponse:
    """Return three candidate 核心問題 for a given topic (Opus single call)."""
    from src.config import Config as SrcConfig
    from src.llm_client import LLMClient
    from src.social_studies.planner import plan_core_questions
    from src.social_studies.schema_loader import load_learning_stage, load_schemas

    src_config = SrcConfig.from_env()
    client = LLMClient(src_config)
    schemas = load_schemas()
    learning_stage = load_learning_stage(schemas)

    candidates = plan_core_questions(
        client,
        body.topic,
        subject_filter=body.subject_filter,
        grade=body.grade,
        learning_stage=learning_stage,
    )
    return PlanCoreQuestionsResponse(candidates=candidates)
