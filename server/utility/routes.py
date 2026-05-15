"""Utility routes: /health and /api/schemas."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status

from server.auth.dependencies import get_config
from server.config import ServerConfig

router = APIRouter(tags=["utility"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/schemas")
async def get_schemas(
    subject: str = Query(default="math"),
    config: ServerConfig = Depends(get_config),
) -> dict:
    path: Path = (
        config.social_studies_schemas_path
        if subject == "social_studies"
        else config.question_schemas_path
    )
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"schemas file not found for subject '{subject}'",
        ) from exc
