"""GET /api/history — user-scoped generation history browse + detail + download."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.models import GenerationRecord, User
from server.rate_limit import jwt_user_key, limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["history"])


def _preview(question_json: dict | None, error: str | None = None) -> str:
    """One-line preview: 核心問題 if present, otherwise first 題目 line, capped to 120 chars."""
    if isinstance(error, str) and error.strip():
        return error.strip()[:120]
    if not isinstance(question_json, dict):
        return ""
    core = question_json.get("核心問題")
    if isinstance(core, str) and core.strip():
        return core.strip()[:120]
    subs = question_json.get("subquestions")
    if isinstance(subs, list) and subs:
        first_body = subs[0].get("題目")
        if isinstance(first_body, str) and first_body.strip():
            return first_body.strip().splitlines()[0][:120]
    body = question_json.get("題目")
    if isinstance(body, list) and body:
        first = body[0]
        if isinstance(first, str):
            return first.strip()[:120]
    return ""


def _verified(question_json: dict) -> bool:
    ver = question_json.get("verification")
    return bool(isinstance(ver, dict) and ver.get("passed"))


@router.get("/history")
@limiter.limit("60/minute", key_func=jwt_user_key)
async def list_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    subject: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Return the user's records newest-first with a short preview per row."""
    stmt = select(GenerationRecord).where(GenerationRecord.user_id == user.id)
    count_stmt = select(func.count()).select_from(GenerationRecord).where(
        GenerationRecord.user_id == user.id
    )
    if subject:
        stmt = stmt.where(GenerationRecord.subject == subject)
        count_stmt = count_stmt.where(GenerationRecord.subject == subject)
    stmt = stmt.order_by(GenerationRecord.created_at.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(count_stmt)).scalar_one()

    items = [
        {
            "id": str(r.id),
            "subject": r.subject,
            "question_id": r.question_id,
            "created_at": r.created_at.isoformat(),
            "status": r.status,
            "error": r.error,
            "preview": _preview(r.question_json, r.error if r.status != "completed" else None),
            "verified": _verified(r.question_json or {}) if r.status == "completed" else False,
        }
        for r in rows
    ]
    return {"total": int(total), "items": items}


async def _load_owned(
    record_id: str, user: User, session: AsyncSession
) -> GenerationRecord:
    try:
        rid = uuid.UUID(record_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    row = (
        await session.execute(
            select(GenerationRecord).where(
                GenerationRecord.id == rid,
                GenerationRecord.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


async def _load_latest_owned(
    row: GenerationRecord, user: User, session: AsyncSession
) -> GenerationRecord:
    """Follow this user's version chain to its newest terminal descendant."""
    visited = {row.id}
    descendants: dict[uuid.UUID, GenerationRecord] = {}
    parents_with_children: set[uuid.UUID] = set()
    frontier = [row.id]
    while frontier:
        children = (
            await session.execute(
                select(GenerationRecord)
                .where(
                    GenerationRecord.parent_record_id.in_(frontier),
                    GenerationRecord.user_id == user.id,
                )
            )
        ).scalars().all()
        parents_with_children.update(
            child.parent_record_id
            for child in children
            if child.parent_record_id is not None
        )
        frontier = []
        for child in children:
            if child.id in visited:
                continue
            visited.add(child.id)
            frontier.append(child.id)
            descendants[child.id] = child
    terminal_descendants = [
        child
        for child_id, child in descendants.items()
        if child_id not in parents_with_children
    ]
    candidates = terminal_descendants or list(descendants.values())
    return max(
        candidates,
        key=lambda child: (child.created_at, str(child.id)),
        default=row,
    )


def _embed_images_sync(question_json: dict, config: ServerConfig) -> dict:
    """Copy question_json and embed image_base64 for any PNG still on disk.

    Missing files are silently skipped — the record renders without them.
    Synchronous (blocking) file reads — call via `asyncio.to_thread` from
    async handlers.
    """
    out = dict(question_json)
    top = out.get("圖片")
    if isinstance(top, str) and top:
        path = config.output_dir / top
        if path.exists():
            out["image_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
    subs = out.get("subquestions")
    if isinstance(subs, list):
        new_subs = []
        for sub in subs:
            if not isinstance(sub, dict):
                new_subs.append(sub)
                continue
            sub_copy = dict(sub)
            sub_img = sub_copy.get("圖片")
            if isinstance(sub_img, str) and sub_img:
                path = config.output_dir / sub_img
                if path.exists():
                    sub_copy["image_base64"] = base64.b64encode(
                        path.read_bytes()
                    ).decode("ascii")
            new_subs.append(sub_copy)
        out["subquestions"] = new_subs
    return out


async def _embed_images(question_json: dict, config: ServerConfig) -> dict:
    """Async wrapper offloading the blocking file reads to a worker thread."""
    return await asyncio.to_thread(_embed_images_sync, question_json, config)


@router.get("/history/{record_id}")
@limiter.limit("60/minute", key_func=jwt_user_key)
async def get_history_detail(
    request: Request,
    record_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    config: ServerConfig = Depends(get_config),
) -> dict:
    row = await _load_owned(record_id, user, session)
    row = await _load_latest_owned(row, user, session)
    return {
        "id": str(row.id),
        "subject": row.subject,
        "question_id": row.question_id,
        "created_at": row.created_at.isoformat(),
        "status": row.status,
        "error": row.error,
        "params_json": row.params_json or {},
        "question_json": (
            await _embed_images(row.question_json or {}, config)
            if row.status == "completed"
            else None
        ),
    }


@router.get("/history/{record_id}/download")
@limiter.limit("30/minute", key_func=jwt_user_key)
async def download_history(
    request: Request,
    record_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    row = await _load_owned(record_id, user, session)
    if row.status != "completed":
        raise HTTPException(status_code=404, detail="Not found")
    download_payload = dict(row.question_json or {})
    download_payload["params_json"] = row.params_json or {}
    body = json.dumps(download_payload, ensure_ascii=False, indent=2)
    filename = f"{row.question_id or row.id}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
