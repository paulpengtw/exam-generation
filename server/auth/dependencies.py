"""FastAPI dependencies for auth (config, current user)."""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.tokens import decode_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import User


@lru_cache
def get_config() -> ServerConfig:
    """Cached ServerConfig instance loaded from environment."""
    return ServerConfig.from_env()


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1]


def get_current_token_payload(
    request: Request,
    config: ServerConfig = Depends(get_config),
) -> dict[str, Any]:
    """Decode and return the current Bearer JWT payload."""
    token = _bearer_token(request)
    return decode_jwt(token, config=config)


async def get_current_user(
    payload: dict[str, Any] = Depends(get_current_token_payload),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """Resolve the current user from the Bearer JWT, or raise HTTP 401."""
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    try:
        user_id = uuid.UUID(str(sub))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        ) from exc
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user
