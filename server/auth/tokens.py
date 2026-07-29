"""Magic-link token and JWT helpers."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from jose import JWTError, jwt

from server.config import ServerConfig

JWT_ALGORITHM = "HS256"


def generate_magic_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hash)``. Store the hash, email the raw token."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def create_jwt(
    user_id: uuid.UUID | str,
    email: str,
    *,
    config: ServerConfig,
    origin: int | None = None,
) -> str:
    """Create an HS256 JWT for the given user."""
    now = datetime.now(timezone.utc)
    issued_at = int(now.timestamp())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": issued_at,
        "exp": int((now + timedelta(days=config.jwt_expire_days)).timestamp()),
        "origin": issued_at if origin is None else origin,
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=JWT_ALGORITHM)


def session_origin(payload: dict[str, Any]) -> int:
    """Return the timestamp when the presented login session began."""
    if "origin" in payload:
        return payload["origin"]
    # This fallback becomes dead code once pre-origin tokens age out and should then be removed.
    return payload["iat"]


def decode_jwt(token: str, *, config: ServerConfig) -> dict[str, Any]:
    """Decode + validate a JWT. Raises HTTP 401 on failure."""
    try:
        return jwt.decode(token, config.jwt_secret, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
