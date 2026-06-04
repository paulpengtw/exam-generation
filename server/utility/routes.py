"""Utility routes: /health and /api/schemas."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status

from server.auth.dependencies import get_config
from server.config import ServerConfig
from src.social_studies.curriculum_loader import load_learning_performance
from src.social_studies.schema_loader import load_schemas as load_ss_schemas

router = APIRouter(tags=["utility"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/schemas")
async def get_schemas(
    subject: str = Query(default="math"),
    config: ServerConfig = Depends(get_config),
) -> dict:
    if subject == "social_studies":
        try:
            schemas = load_ss_schemas(config.social_studies_curriculum_dir)
            performance = load_learning_performance(
                config.social_studies_curriculum_dir / "learning_performance.json"
            )
            learning_stage = schemas.get("學習階段", "")
            schemas["學習表現"] = [
                {
                    "value": entry["value"],
                    "instruction": entry.get("說明", ""),
                    "科目": entry.get("科目", ""),
                }
                for entry in performance.get("學習表現", [])
                if entry.get("學習階段") == learning_stage
            ]
            return schemas
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to load social_studies schemas: {exc}",
            ) from exc

    path: Path = config.question_schemas_path
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"schemas file not found for subject '{subject}'",
        ) from exc
