"""Admission route for 人工審題修正 batches."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sse_starlette.sse import EventSourceResponse

from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import AsyncSessionLocal, get_async_session
from server.generate.marshalling import SSEEventName
from server.generate.models import build_sse_error
from server.generate.modification_service import modification_question_stream
from server.models import GenerationLog, GenerationRecord, User
from src.corrector import (
    FROZEN_SUBQUESTION_FIELDS as MATH_FROZEN_SUBQUESTION_FIELDS,
)
from src.corrector import (
    FROZEN_TOP_LEVEL_FIELDS as MATH_FROZEN_TOP_LEVEL_FIELDS,
)
from src.llm_client import LLMClient
from src.llm_client import classify_provider_error as _classify_provider_error
from src.natural_sciences.corrector import (
    FROZEN_SUBQUESTION_FIELDS as NS_FROZEN_SUBQUESTION_FIELDS,
)
from src.natural_sciences.corrector import (
    FROZEN_TOP_LEVEL_FIELDS as NS_FROZEN_TOP_LEVEL_FIELDS,
)
from src.social_studies.corrector import (
    FROZEN_SUBQUESTION_FIELDS as SS_FROZEN_SUBQUESTION_FIELDS,
)
from src.social_studies.corrector import (
    FROZEN_TOP_LEVEL_FIELDS as SS_FROZEN_TOP_LEVEL_FIELDS,
)

router = APIRouter(prefix="/api", tags=["generation-records"])


class ModificationSegment(BaseModel):
    field_path: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quoted_text: str


class ModificationAnnotation(BaseModel):
    segments: list[ModificationSegment] = Field(
        default_factory=list,
        alias="segments",
        validation_alias=AliasChoices("segments", "圈選"),
    )
    modification_instruction: str | None = Field(
        default=None,
        alias="修改指示",
        validation_alias=AliasChoices(
            "修改指示", "modification_instruction", "instruction"
        ),
    )

    model_config = {"populate_by_name": True}


class ModificationBatch(BaseModel):
    annotations: list[ModificationAnnotation] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_domain_shape(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        if "annotations" in value:
            raw_annotations = value["annotations"]
            if isinstance(raw_annotations, dict):
                return {**value, "annotations": [raw_annotations]}
            return value
        raw_selections = value.get("圈選")
        if not isinstance(raw_selections, list):
            return value
        if all(
            isinstance(selection, dict) and "field_path" in selection
            for selection in raw_selections
        ):
            return {
                "annotations": [
                    {"圈選": raw_selections, "修改指示": value.get("修改指示")}
                ]
            }
        return {**value, "annotations": raw_selections}


_PATH_TOKEN = re.compile(r"(?:^|\.)([^.\[\]]+)|\[(\d+)\]")

_FROZEN_FIELDS_BY_SUBJECT = {
    "math": (MATH_FROZEN_TOP_LEVEL_FIELDS, MATH_FROZEN_SUBQUESTION_FIELDS),
    "social_studies": (SS_FROZEN_TOP_LEVEL_FIELDS, SS_FROZEN_SUBQUESTION_FIELDS),
    "natural_sciences": (NS_FROZEN_TOP_LEVEL_FIELDS, NS_FROZEN_SUBQUESTION_FIELDS),
}


def _path_tokens(field_path: str) -> list[str | int]:
    tokens: list[str | int] = []
    consumed = 0
    for match in _PATH_TOKEN.finditer(field_path):
        consumed = match.end()
        key, index = match.groups()
        tokens.append(key if key is not None else int(index))
    if not tokens or consumed != len(field_path):
        raise KeyError(field_path)
    return tokens


def _resolve_field(question: dict[str, Any], field_path: str) -> object:
    current: object = question
    for token in _path_tokens(field_path):
        if isinstance(token, str):
            key = token
            index = None
        else:
            key = None
            index = token
        if key is not None:
            if not isinstance(current, dict) or key not in current:
                raise KeyError(field_path)
            current = current[key]
        else:
            if not isinstance(current, list):
                raise KeyError(field_path)
            current = current[index]
    return current


def _slice_by_frontend_offsets(value: str, start: int, end: int) -> str | None:
    """Slice using JavaScript/DOM UTF-16 offsets used by the web client."""
    encoded = value.encode("utf-16-le")
    unit_count = len(encoded) // 2
    if start > end or end > unit_count:
        return None
    try:
        return encoded[start * 2 : end * 2].decode("utf-16-le")
    except UnicodeDecodeError:
        return None


def _is_frozen_field(subject: str, field_path: str) -> bool:
    top_level, subquestion = _FROZEN_FIELDS_BY_SUBJECT.get(
        subject, (frozenset(), frozenset())
    )
    try:
        tokens = _path_tokens(field_path)
    except KeyError:
        return False
    # chart_spec is deliberately the one figure field that 人工審題修正 may
    # address, even though some subject correctors freeze it during automatic
    # 驗證/修正 passes.
    if (
        len(tokens) >= 3
        and tokens[0] == "subquestions"
        and isinstance(tokens[1], int)
        and tokens[2] == "chart_spec"
    ):
        return False
    if tokens and isinstance(tokens[0], str) and tokens[0] in top_level:
        return True
    return (
        len(tokens) >= 3
        and tokens[0] == "subquestions"
        and isinstance(tokens[1], int)
        and isinstance(tokens[2], str)
        and tokens[2] in subquestion
    )


async def _load_owned(
    record_id: str, user: User, session: AsyncSession
) -> GenerationRecord:
    try:
        parsed_id = uuid.UUID(record_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    row = (
        await session.execute(
            select(GenerationRecord).where(
                GenerationRecord.id == parsed_id,
                GenerationRecord.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


def _reject(code: str, message: str, *, status_code: int = 422) -> None:
    raise ModificationRejected(code, message, status_code)


class ModificationRejected(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code


_SUBQUESTION_QUESTION_PATH = re.compile(r"^subquestions\[(\d+)\]\.題目$")
_DEPENDENT_FIELDS = ("答案", "評分規準", "答案解析")


def _build_edit_scope(
    question: dict[str, Any], touched_paths: set[str]
) -> tuple[set[str], set[str]]:
    """Return direct + dependent editable paths and the dependent subset."""
    editable_paths = set(touched_paths)
    dependent_paths: set[str] = set()
    subquestions = question.get("subquestions")
    subquestion_count = len(subquestions) if isinstance(subquestions, list) else 0
    dependent_indexes: set[int] = set()
    for field_path in touched_paths:
        if field_path == "文本":
            dependent_indexes.update(range(subquestion_count))
            continue
        match = _SUBQUESTION_QUESTION_PATH.fullmatch(field_path)
        if match is not None:
            dependent_indexes.add(int(match.group(1)))
    for index in sorted(dependent_indexes):
        for field in _DEPENDENT_FIELDS:
            field_path = f"subquestions[{index}].{field}"
            editable_paths.add(field_path)
            dependent_paths.add(field_path)
    return editable_paths, dependent_paths


def _serialize_event(event: dict[str, Any]) -> dict[str, str]:
    data = event.get("data", "")
    if not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False)
    event_name = event["event"]
    if isinstance(event_name, SSEEventName):
        event_name = event_name.value
    return {"event": str(event_name), "data": data}


def _session_factory_for(session: AsyncSession) -> Any:
    """Build a factory on the request's bound engine for test and prod parity."""
    bind = session.bind
    if bind is None:
        return AsyncSessionLocal
    return async_sessionmaker(bind, expire_on_commit=False, class_=AsyncSession)


@router.post("/generation-records/{record_id}/modifications", response_model=None)
async def submit_modification_batch(
    record_id: str,
    batch: ModificationBatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str] | JSONResponse:
    """Validate a manual modification batch and admit a stub run."""
    try:
        row = await _load_owned(record_id, user, session)
    except HTTPException as exc:
        if exc.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={"error": "not_found", "message": "Not found"},
            )
        raise
    question = row.question_json if isinstance(row.question_json, dict) else {}

    try:
        child_id = (
            await session.execute(
                select(GenerationRecord.id)
                .where(GenerationRecord.parent_record_id == row.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if child_id is not None:
            _reject(
                "not_latest",
                "This record is not the latest version; submit the modification "
                "from the newest record.",
            )
        active_run_id = (
            await session.execute(
                select(GenerationLog.id)
                .where(
                    GenerationLog.user_id == user.id,
                    GenerationLog.question_id == str(row.id),
                    GenerationLog.status == "started",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active_run_id is not None:
            _reject(
                "run_in_progress",
                "An active modification run already exists for this record; wait for it to finish.",
                status_code=409,
            )
        if not batch.annotations or any(
            not annotation.segments
            or any(not segment.quoted_text.strip() for segment in annotation.segments)
            for annotation in batch.annotations
        ):
            _reject(
                "empty_annotation",
                "Each 圈選 must contain at least one non-empty, non-chrome segment.",
            )
        if any(
            not annotation.modification_instruction
            or not annotation.modification_instruction.strip()
            for annotation in batch.annotations
        ):
            _reject(
                "missing_instruction",
                "Every 圈選 must include a non-empty 修改指示.",
            )
        for annotation in batch.annotations:
            for segment in annotation.segments:
                try:
                    value = _resolve_field(question, segment.field_path)
                except (KeyError, IndexError, TypeError):
                    _reject(
                        "stale_base",
                        f"The selected field {segment.field_path!r} is no longer "
                        "present on this record.",
                    )
                if _is_frozen_field(row.subject, segment.field_path):
                    _reject(
                        "frozen_field",
                        f"The field {segment.field_path!r} is fixed by the corrector; "
                        "regenerate the record or change the request settings.",
                    )
                selected_text = (
                    _slice_by_frontend_offsets(value, segment.start, segment.end)
                    if isinstance(value, str)
                    else None
                )
                if selected_text != segment.quoted_text:
                    _reject(
                        "stale_base",
                        f"The selected text for {segment.field_path!r} no longer "
                        "matches this record.",
                    )
    except ModificationRejected as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message},
        )

    annotations = [
        annotation.model_dump(mode="json", by_alias=True, exclude_none=True)
        for annotation in batch.annotations
    ]
    touched_paths = {
        segment.field_path
        for annotation in batch.annotations
        for segment in annotation.segments
    }
    editable_paths, dependent_paths = _build_edit_scope(question, touched_paths)

    run = GenerationLog(
        user_id=user.id,
        params_json={
            "kind": "manual_modification",
            "record_id": str(row.id),
            "annotations": annotations,
            "editable_paths": sorted(editable_paths),
            "dependent_paths": sorted(dependent_paths),
        },
        status="started",
        question_id=str(row.id),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return {"run_id": str(run.id), "status": run.status}


@router.get(
    "/generation-records/{record_id}/modifications/{run_id}/stream",
    response_model=None,
)
@router.get(
    "/generation-records/{record_id}/modifications/{run_id}",
    response_model=None,
)
async def stream_modification_run(
    record_id: str,
    run_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    config: ServerConfig = Depends(get_config),
) -> EventSourceResponse:
    """Attach to an admitted 人工審題修正 run and stream its 修改 step."""
    row = await _load_owned(record_id, user, session)
    run = (
        await session.execute(
            select(GenerationLog).where(
                GenerationLog.id == run_id,
                GenerationLog.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if run is None or run.question_id != str(row.id):
        raise HTTPException(status_code=404, detail="Not found")
    if run.status != "started":
        raise HTTPException(status_code=409, detail="This modification run is no longer active")
    if not isinstance(row.question_json, dict):
        raise HTTPException(status_code=422, detail="The base record has no question payload")

    params = run.params_json if isinstance(run.params_json, dict) else {}
    annotations = params.get("annotations")
    if not isinstance(annotations, list):
        raise HTTPException(status_code=422, detail="The modification run has no annotations")
    editable_paths = {
        path for path in params.get("editable_paths", []) if isinstance(path, str)
    }
    dependent_paths = {
        path for path in params.get("dependent_paths", []) if isinstance(path, str)
    }
    run_session_factory = _session_factory_for(session)
    client_factory = (
        getattr(request.app.state, "modification_client_factory", None) or LLMClient
    )

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        status = "completed"
        error_message: str | None = None
        try:
            async for event in modification_question_stream(
                base_question=row.question_json,
                subject=row.subject,
                record_id=row.id,
                generation_log_id=run.id,
                annotations=annotations,
                editable_paths=editable_paths,
                dependent_paths=dependent_paths,
                config=config,
                user_id=user.id,
                session_factory=run_session_factory,
                figure_policy_trail_json=row.figure_policy_trail_json,
                client_factory=client_factory,
            ):
                yield _serialize_event(event)
        except Exception as exc:
            status = "failed"
            _mfc = _classify_provider_error(exc)
            error_payload = build_sse_error(
                "modification_failed",
                f"Modification stream failed ({type(exc).__name__})",
                failure_class=_mfc,
            )
            error_message = error_payload["message"]
            yield _serialize_event(
                {"event": SSEEventName.ERROR, "data": error_payload}
            )
            yield _serialize_event({"event": SSEEventName.DONE, "data": ""})
        finally:
            async with run_session_factory() as update_session:
                await update_session.execute(
                    update(GenerationLog)
                    .where(GenerationLog.id == run.id)
                    .values(
                        status=status,
                        error=error_message,
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await update_session.commit()

    return EventSourceResponse(
        event_generator(),
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
