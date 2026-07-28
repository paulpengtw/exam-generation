"""Utility routes: /health and /api/schemas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from server.auth.dependencies import get_config
from server.config import ServerConfig
from server.generate.models import ALLOWED_SUBJECTS
from server.generate.subjects import SUBJECTS

router = APIRouter(tags=["utility"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/models")
async def get_models(
    config: ServerConfig = Depends(get_config),
) -> dict:
    """Return the LLM model allowlist and the server-side defaults."""
    return {
        "allowed": list(config.llm_models_allowed),
        "defaults": {
            "plan": config.model_plan,
            "execute": config.model_execute,
        },
    }


@router.get("/api/schemas")
async def get_schemas(
    subject: str = Query(default="math"),
    grade: int | None = Query(default=None),
    config: ServerConfig = Depends(get_config),
) -> dict:
    if subject not in ALLOWED_SUBJECTS:
        allowed = ", ".join(sorted(ALLOWED_SUBJECTS))
        raise HTTPException(
            status_code=422,
            detail=f"subject: subject '{subject}' not in allowlist: [{allowed}]",
        )

    # Site 7: schemas dispatch via registry (replaces if/elif per-subject branches)
    spec = SUBJECTS[subject]
    try:
        return spec.build_schemas(config, grade)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"schemas file not found for subject '{subject}'",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to load {subject} schemas: {exc}",
        ) from exc
