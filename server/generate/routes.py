"""Generate routes — JSON body and legacy GET transports for previews and SSE."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import AsyncSessionLocal, get_async_session
from server.generate.event_protocol import SUPPORTED_STREAM_VERSIONS, client_update_required_body
from server.generate.models import (
    ALLOWED_SUBJECTS,
    SERVER_ONLY_GENERATE_FIELDS,
    CoverageMode,
    GenerateParams,
    ImageGenerationMode,
    PlanCoreQuestionsRequest,
    PlanCoreQuestionsResponse,
    ResolveRequest,
    ResolveResponse,
    build_sse_error,
)
from server.generate.persistence import (
    persist_aborted_generation_record,
    persist_failed_generation_record,
)
from server.generate.service import build_prompt_previews, generate_question_stream
from server.generate.subjects import SUBJECTS
from server.models import GenerationLog, LLMExchange, User
from server.rate_limit import jwt_user_key, limiter
from src.common.resolver import ResolveConflictError, resolve

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])
NonEmptyQueryValue = Annotated[str, Field(min_length=1)]
GenerateQuery = Annotated[GenerateParams, Query()]


def _require_complete_generate_params(params: GenerateParams) -> GenerateParams:
    """Reject unresolved or incompatible payloads before any generation side effect."""
    try:
        # Exclude server-only fields (e.g. stream_version) from the resolver payload
        # so they are never forwarded into per_question_params rows.
        resolver_input = {
            k: v
            for k, v in params.model_dump(mode="json", exclude_none=True).items()
            if k not in SERVER_ONLY_GENERATE_FIELDS
        }
        result = resolve(resolver_input)
    except ResolveConflictError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result.drawn:
        raise HTTPException(
            status_code=422,
            detail=[
                {"field": field, "code": "unresolved"}
                for field in result.drawn
            ],
        )

    resolved_payload = dict(result.payload)
    rows = resolved_payload.get("per_question_params")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("subquestion_configs"), list):
                row["subquestion_configs"] = json.dumps(
                    row["subquestion_configs"], ensure_ascii=False
                )
        resolved_payload["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    configs = resolved_payload.get("subquestion_configs")
    if isinstance(configs, list):
        resolved_payload["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)
    try:
        return GenerateParams.model_validate(resolved_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/generate/preview")
@limiter.limit("30/hour", key_func=jwt_user_key)
async def preview_generate_endpoint(
    request: Request,
    params: GenerateQuery,
    _user: User = Depends(get_current_user),
    config: ServerConfig = Depends(get_config),
) -> dict[str, Any]:
    return _preview_generate(request, params, config)


@router.post("/generate/preview")
@limiter.limit("30/hour", key_func=jwt_user_key)
async def preview_generate_body_endpoint(
    request: Request,
    params: GenerateParams,
    _user: User = Depends(get_current_user),
    config: ServerConfig = Depends(get_config),
) -> dict[str, Any]:
    return _preview_generate(request, params, config)


def _preview_generate(
    request: Request, params: GenerateParams, config: ServerConfig,
) -> dict[str, Any]:
    """Return exact first-stage prompts without invoking an LLM."""
    params = _require_complete_generate_params(params)
    _check_model_allowed(params.model_plan, config, "model_plan")
    _check_model_allowed(params.model_execute, config, "model_execute")
    _check_model_allowed(params.model_verify, config, "model_verify")    # #375
    _check_model_allowed(params.model_correct, config, "model_correct")  # #375
    _check_subject_allowed(params.subject)
    effective_plan_model = params.model_plan or config.model_plan
    effective_execute_model = params.model_execute or config.model_execute
    # #375: tier model resolution — request param → env var → effective execute model
    effective_verify_model = params.model_verify or config.model_verify or effective_execute_model
    effective_correct_model = (
        params.model_correct or config.model_correct or effective_execute_model
    )
    _check_effort_for_model(params.effort_plan, effective_plan_model, "effort_plan")
    # #377: effective execute effort (with per-request override applied)
    effective_execute_effort = params.effort_execute or config.effort_execute
    _check_effort_for_model(params.effort_execute, effective_execute_model, "effort_execute")
    # #377: validate tier efforts against their effective model using the full inherited chain
    effective_verify_effort = (
        params.effort_verify or config.effort_verify or effective_execute_effort
    )
    _check_effort_for_model(effective_verify_effort, effective_verify_model, "effort_verify")
    effective_correct_effort = (
        params.effort_correct or config.effort_correct or effective_execute_effort
    )
    _check_effort_for_model(effective_correct_effort, effective_correct_model, "effort_correct")
    _check_image_api_key(params.image_generation_mode, params.subquestion_configs, config)
    _check_provider_key_for_model(effective_plan_model, config, "model_plan")
    _check_provider_key_for_model(effective_execute_model, config, "model_execute")
    _check_provider_key_for_model(effective_verify_model, config, "model_verify")    # #375
    _check_provider_key_for_model(effective_correct_model, config, "model_correct")  # #375
    return {"prompts": build_prompt_previews(params, config, request.app.state)}


@router.post("/generate/resolve", response_model=ResolveResponse)
@limiter.limit("30/hour", key_func=jwt_user_key)
async def resolve_generate_endpoint(
    request: Request,
    body: ResolveRequest,
    _user: User = Depends(get_current_user),
    _config: ServerConfig = Depends(get_config),
) -> ResolveResponse:
    """Resolve a whole generation payload before prompt assembly."""
    payload = (
        body.payload
        if body.payload is not None
        else body.model_dump(exclude={"payload", "redraws"})
    )
    try:
        result = resolve(payload, redraws=body.redraws)
    except ResolveConflictError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ResolveResponse(payload=result.payload, drawn=result.drawn, cleared=result.cleared)


def _serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Convert internal event dict to sse_starlette ServerSentEvent fields.

    Supports both v1 events ({event, data}) and v2 envelopes (dual-key: top-level
    "event" plus {context, payload}).  V2 envelopes serialize the full envelope as
    JSON in the data field so the client receives the context+payload structure.
    """
    if "context" in event:
        # v2 envelope: includes both top-level "event" and context/payload structure.
        event_name = event.get("event") or event["context"].get("event", "unknown")
        # Serialize full envelope (context + payload) so client gets v2 metadata.
        envelope_for_wire = {"context": event["context"], "payload": event.get("payload", {})}
        data = json.dumps(envelope_for_wire, ensure_ascii=False)
        return {"event": event_name, "data": data}
    data = event.get("data", "")
    if not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False)
    return {"event": event["event"], "data": data}


def _check_model_allowed(model: str | None, config: ServerConfig, field: str) -> None:
    """Raise HTTPException(422) when a submitted model is outside the allowlist."""
    if not model:
        return
    if model not in config.llm_models_allowed:
        allowed = ", ".join(config.llm_models_allowed)
        raise HTTPException(
            status_code=422,
            detail=f"{field}: model '{model}' not in allowlist: [{allowed}]",
        )


def _check_effort_for_model(effort: str | None, model: str, field: str) -> None:
    """Raise HTTPException(422) when effort level is not in the model's roster."""
    if effort is None:
        return
    from server.config import _EFFORT_LEVELS  # noqa: PLC0415

    roster = _EFFORT_LEVELS.get(model, ["low", "medium", "high", "max"])
    if effort not in roster:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{field}: effort '{effort}' not supported by model '{model}' "
                f"(supported: {roster})"
            ),
        )


def _check_subject_allowed(subject: str) -> None:
    """Raise HTTPException(422) when subject is not a recognised value."""
    if subject not in ALLOWED_SUBJECTS:
        allowed = ", ".join(sorted(ALLOWED_SUBJECTS))
        raise HTTPException(
            status_code=422,
            detail=f"subject: subject '{subject}' not in allowlist: [{allowed}]",
        )


def _check_image_api_key(
    image_generation_mode: str,
    subquestion_configs_raw: str | None,
    config: ServerConfig,
) -> None:
    """Raise HTTPException(422) when gpt_image is requested but IMAGE_API_KEY is empty."""
    if config.image_api_key:
        return
    needs_gpt = image_generation_mode == "gpt_image"
    if not needs_gpt and subquestion_configs_raw:
        try:
            items = json.loads(subquestion_configs_raw)
            if isinstance(items, list):
                needs_gpt = any(
                    isinstance(item, dict) and item.get("image_generation_mode") == "gpt_image"
                    for item in items
                )
        except Exception:
            pass
    if needs_gpt:
        raise HTTPException(
            status_code=422,
            detail=(
                "image_generation_mode: gpt_image requires IMAGE_API_KEY "
                "to be set on the server"
            ),
        )


_PROVIDER_KEY_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "anthropic": ("api_key", "LLM_API_KEY"),
    "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
}


def _check_provider_key_for_model(model: str, config: ServerConfig, field: str) -> None:
    """Raise HTTPException(422) when the model's provider API key is unset."""
    from src.llm_client import resolve_provider  # noqa: PLC0415

    attr, env_name = _PROVIDER_KEY_REQUIREMENTS[resolve_provider(model)]
    if not getattr(config, attr):
        raise HTTPException(
            status_code=422,
            detail=f"{field}: model '{model}' requires {env_name} to be set on the server",
        )


@router.get("/generate")
@limiter.limit("10/hour", key_func=jwt_user_key)
async def generate_endpoint(
    request: Request,
    subject: str = Query(default="math"),
    grade: int | None = Query(default=None),
    style: list[NonEmptyQueryValue] | None = Query(default=None),
    context: list[NonEmptyQueryValue] | None = Query(default=None),
    set_type: NonEmptyQueryValue | None = Query(default=None),
    q_type: list[NonEmptyQueryValue] | None = Query(default=None),
    count: int = Query(default=1, ge=1, le=10),
    skip_verify: bool = Query(default=False),
    disable_reference_fewshot: bool = Query(default=False),
    seed: int | None = Query(default=None),
    max_retries: int = Query(default=3),
    allow_duplicate_figure_kinds: bool = Query(default=False),
    image_generation_mode: ImageGenerationMode = Query(default="html"),
    difficulty: Literal["easy", "medium", "hard"] | None = Query(default=None),
    coverage_mode: CoverageMode = Query(default="balanced"),
    core_question_callback: bool = Query(default=True),
    subject_filter: list[NonEmptyQueryValue] | None = Query(default=None),
    content_type: str | None = Query(default=None),
    content_domain: str | None = Query(default=None),
    target_surface: Literal["紙本", "數位"] | None = Query(default=None),
    passage: str | None = Query(default=None),
    options: list[str] | None = Query(default=None),
    topic: str | None = Query(default=None),
    core_question: str | None = Query(default=None),
    text_instruction: str | None = Query(default=None),
    sub_context: NonEmptyQueryValue | None = Query(default=None),
    science_competency: list[NonEmptyQueryValue] | None = Query(default=None),
    learning_performance: list[str] | None = Query(default=None),
    core_competency: list[str] | None = Query(default=None),
    math_thinking: list[str] | None = Query(default=None),
    learning_content: list[str] | None = Query(default=None),
    sub_question_count: int | None = Query(default=None, ge=3, le=7),
    question_word_limit: int | None = Query(default=None, ge=1),
    option_word_limit: int | None = Query(default=None, ge=1),
    text_word_limit: int | None = Query(default=None, ge=1),
    subquestion_configs: str | None = Query(default=None),
    per_question_params: str | None = Query(default=None),
    drawn: list[str] | None = Query(default=None),
    model_plan: str | None = Query(default=None),
    model_execute: str | None = Query(default=None),
    model_verify: str | None = Query(default=None),    # #375: per-request tier model override
    model_correct: str | None = Query(default=None),   # #375: per-request tier model override
    effort_plan: str | None = Query(default=None),
    effort_execute: str | None = Query(default=None),
    effort_verify: str | None = Query(default=None),   # #377: per-request tier effort override
    effort_correct: str | None = Query(default=None),  # #377: per-request tier effort override
    reporting_scale: str | None = Query(default=None),
    stream_version: int | None = Query(default=None),  # #742: stream protocol version gate
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    config: ServerConfig = Depends(get_config),
) -> EventSourceResponse:
    """Stream question generation events as Server-Sent Events.

    Logs the request to `generation_log` at start and updates the row to
    `completed` or `failed` when the stream ends.
    """
    try:
        # FastAPI has already type-checked the query fields. Keep configuration
        # admission ahead of subject-specific validation, as on the legacy route.
        params = GenerateParams.model_construct(
            subject=subject,
            grade=grade,
            style=style,
            context=context,
            set_type=set_type,
            q_type=q_type,
            count=count,
            skip_verify=skip_verify,
            disable_reference_fewshot=disable_reference_fewshot,
            seed=seed,
            max_retries=max_retries,
            allow_duplicate_figure_kinds=allow_duplicate_figure_kinds,
            image_generation_mode=image_generation_mode,
            difficulty=difficulty,
            coverage_mode=coverage_mode,
            core_question_callback=core_question_callback,
            subject_filter=subject_filter,
            content_type=content_type,
            content_domain=content_domain,
            target_surface=target_surface,
            passage=passage,
            options=options,
            topic=topic,
            core_question=core_question,
            text_instruction=text_instruction,
            sub_context=sub_context,
            science_competency=science_competency,
            learning_performance=learning_performance,
            core_competency=core_competency,
            math_thinking=math_thinking,
            learning_content=learning_content,
            sub_question_count=sub_question_count,
            question_word_limit=question_word_limit,
            option_word_limit=option_word_limit,
            text_word_limit=text_word_limit,
            subquestion_configs=subquestion_configs,
            per_question_params=per_question_params,
            drawn=drawn,
            model_plan=model_plan,
            model_execute=model_execute,
            model_verify=model_verify,    # #375
            model_correct=model_correct,  # #375
            effort_plan=effort_plan,
            effort_execute=effort_execute,
            effort_verify=effort_verify,   # #377
            effort_correct=effort_correct,  # #377
            reporting_scale=reporting_scale,
        )
        if stream_version is None or stream_version not in SUPPORTED_STREAM_VERSIONS:
            return JSONResponse(status_code=426, content=client_update_required_body())
        _check_generation_admission(params, config)
        params = GenerateParams.model_validate(params.model_dump())
    except ValidationError as exc:
        # Emit a WARNING so Sentry (LoggingIntegration at WARNING level) captures
        # validation-rejection spikes without widening failed_request_status_codes.
        # Log only the error count and field names — never user-supplied values
        # (ADR 0004).
        logger.warning(
            "generate 422 validation_error: %d error(s) on field(s) %s",
            exc.error_count(),
            [str(e["loc"]) for e in exc.errors()],
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _generate(request, params, user, session, config)


@router.post("/generate")
@limiter.limit("10/hour", key_func=jwt_user_key)
async def generate_body_endpoint(
    request: Request,
    params: GenerateParams,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    config: ServerConfig = Depends(get_config),
) -> EventSourceResponse:
    if params.stream_version is None or params.stream_version not in SUPPORTED_STREAM_VERSIONS:
        return JSONResponse(status_code=426, content=client_update_required_body())
    _check_generation_admission(params, config)
    return await _generate(request, params, user, session, config)


def _check_generation_admission(params: GenerateParams, config: ServerConfig) -> None:
    """Apply the same model, effort, image and provider rules to both transports."""
    _check_model_allowed(params.model_plan, config, "model_plan")
    _check_model_allowed(params.model_execute, config, "model_execute")
    _check_model_allowed(params.model_verify, config, "model_verify")    # #375
    _check_model_allowed(params.model_correct, config, "model_correct")  # #375
    _check_subject_allowed(params.subject)
    # Validate effort levels against the effective model's roster (BEFORE any LLM call).
    effective_plan_model = params.model_plan or config.model_plan
    effective_execute_model = params.model_execute or config.model_execute
    # #375: tier model resolution — request param → env var → effective execute model.
    # Note: chains off effective_execute_model (honours per-request model_execute override).
    effective_verify_model = params.model_verify or config.model_verify or effective_execute_model
    effective_correct_model = (
        params.model_correct or config.model_correct or effective_execute_model
    )
    _check_effort_for_model(params.effort_plan, effective_plan_model, "effort_plan")
    _check_effort_for_model(params.effort_execute, effective_execute_model, "effort_execute")
    # #377: validate tier efforts against their effective model using the full inherited chain.
    # Note: effective_execute_effort chains off the per-request override so that an unset
    # tier effort inherits the per-request execute override (not the env-time default).
    effective_execute_effort = params.effort_execute or config.effort_execute
    effective_verify_effort = (
        params.effort_verify or config.effort_verify or effective_execute_effort
    )
    _check_effort_for_model(effective_verify_effort, effective_verify_model, "effort_verify")
    effective_correct_effort = (
        params.effort_correct or config.effort_correct or effective_execute_effort
    )
    _check_effort_for_model(effective_correct_effort, effective_correct_model, "effort_correct")
    _check_image_api_key(params.image_generation_mode, params.subquestion_configs, config)
    _check_provider_key_for_model(effective_plan_model, config, "model_plan")
    _check_provider_key_for_model(effective_execute_model, config, "model_execute")
    _check_provider_key_for_model(effective_verify_model, config, "model_verify")    # #375
    _check_provider_key_for_model(effective_correct_model, config, "model_correct")  # #375


async def _generate(
    request: Request,
    params: GenerateParams,
    user: User,
    session: AsyncSession,
    config: ServerConfig,
) -> EventSourceResponse:
    params = _require_complete_generate_params(params)
    logger.info("generate request params=%s", params.model_dump(mode="json"))

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
        failed_record_written = False
        aborted_record_written = False

        async def persist_failure_once(message: str) -> None:
            nonlocal failed_record_written
            if failed_record_written:
                return
            failed_record_written = True
            await persist_failed_generation_record(
                user_id=user.id,
                generation_log_id=log_id,
                subject=params.subject,
                params=params,
                error=message,
                session_factory=AsyncSessionLocal,
            )

        async def persist_aborted_once() -> None:
            nonlocal aborted_record_written
            if aborted_record_written or status == "failed":
                return
            aborted_record_written = True
            await persist_aborted_generation_record(
                user_id=user.id,
                generation_log_id=log_id,
                subject=params.subject,
                params=params,
                session_factory=AsyncSessionLocal,
            )

        stream = generate_question_stream(
            params,
            config,
            app_state,
            user_id=user.id,
            generation_log_id=log_id,
            session_factory=AsyncSessionLocal,
        )
        try:
            async for event in stream:
                if event.get("event") == "error":
                    status = "failed"
                    data = event.get("data", "")
                    error_msg = (
                        data.get("message", str(data)) if isinstance(data, dict) else str(data)
                    )
                yield _serialize_event(event)
            if status == "failed":
                await persist_failure_once(error_msg or "Generation failed")
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                try:
                    await stream.aclose()
                finally:
                    if status == "failed":
                        await persist_failure_once(error_msg or "Generation failed")
                    else:
                        await persist_aborted_once()
            raise
        except Exception as exc:
            status = "failed"
            error_payload = build_sse_error(
                "stream_failed",
                f"Stream error ({type(exc).__name__})",
            )
            error_msg = error_payload["message"]
            logger.exception("generate_endpoint stream error")
            await persist_failure_once(error_msg)
            yield _serialize_event({"event": "error", "data": error_payload})
            yield {"event": "done", "data": ""}
        finally:
            with anyio.CancelScope(shield=True):
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
    """Return three candidate 核心問題 with at most one correction call."""
    _check_model_allowed(body.model_plan, config, "model_plan")
    _check_model_allowed(body.model_execute, config, "model_execute")
    # Validate effort_plan against the effective plan model's roster.
    effective_plan_model = body.model_plan or config.model_plan
    effective_execute_model = body.model_execute or config.model_execute
    _check_effort_for_model(body.effort_plan, effective_plan_model, "effort_plan")
    _check_provider_key_for_model(effective_plan_model, config, "model_plan")
    _check_provider_key_for_model(effective_execute_model, config, "model_execute")
    from src.config import Config as SrcConfig
    from src.llm_client import LLMClient

    src_config = SrcConfig.from_env()
    src_config = dataclasses.replace(
        src_config,
        model_plan=body.model_plan or src_config.model_plan,
        model_execute=body.model_execute or src_config.model_execute,
        effort_plan=body.effort_plan or src_config.effort_plan,
    )
    client = LLMClient(src_config)

    # Site 6: planner dispatch via registry (replaces if/elif per-subject branches)
    spec = SUBJECTS[body.subject]
    learning_stage = spec.load_planner_stage(None, body.grade)
    try:
        candidates = spec.plan_core_questions(
            client,
            body.topic,
            subject_filter=body.subject_filter,
            grade=body.grade,
            learning_stage=learning_stage,
        )
    except ValueError as exc:
        from server.observability import PLANNER_DIAGNOSTIC_MARKER
        from src.common.planner import CandidateValidationError

        diagnostic = {PLANNER_DIAGNOSTIC_MARKER: True}
        if isinstance(exc, CandidateValidationError):
            diagnostic.update(
                stage=exc.stage,
                attempt=exc.attempt,
                expected_count=exc.expected_count,
                actual_count=exc.actual_count,
                received_count=exc.received_count,
            )
        logger.warning("Planner returned malformed candidates: %s", exc, extra=diagnostic)
        raise HTTPException(
            status_code=502,
            detail="Planner upstream returned malformed candidates",
        ) from exc
    return PlanCoreQuestionsResponse(candidates=candidates)


@router.get("/generation-logs/{log_id}/exchanges")
async def list_generation_log_exchanges(
    log_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[dict[str, Any]]:
    """Return LLM exchanges for a generation the caller owns, ordered by exchange_order.

    404 on missing/other-user logs (existence-hiding — never 403).
    """
    log_row = (
        await session.execute(
            select(GenerationLog).where(
                GenerationLog.id == log_id, GenerationLog.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if log_row is None:
        raise HTTPException(status_code=404, detail="generation log not found")

    rows = (
        (
            await session.execute(
                select(LLMExchange)
                .where(LLMExchange.generation_log_id == log_id)
                .order_by(LLMExchange.exchange_order.asc())
            )
        )
        .scalars()
        .all()
    )

    return [
        {
            "id": str(row.id),
            "exchange_order": row.exchange_order,
            "agent": row.agent,
            "purpose": row.purpose,
            "request_body": row.request_body,
            "response_body": row.response_body,
            "model_used": row.model_used,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
