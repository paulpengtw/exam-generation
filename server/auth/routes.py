"""Auth routes: magic-link request, verify, and me."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.dependencies import get_config, get_current_user
from server.auth.email import EmailSender, get_email_sender
from server.auth.tokens import create_jwt, generate_magic_token
from server.config import ServerConfig
from server.db import get_async_session
from server.models import MagicLinkToken, User
from server.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])

MAGIC_LINK_TTL_MINUTES = 15
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MagicLinkRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email")
        return v


class MagicLinkResponse(BaseModel):
    message: str = "Check your email"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime


def _email_sender_dep(config: ServerConfig = Depends(get_config)) -> EmailSender:
    return get_email_sender(config)


@router.post("/magic-link", response_model=MagicLinkResponse)
@limiter.limit("5/hour")
async def request_magic_link(
    request: Request,
    payload: MagicLinkRequest,
    session: AsyncSession = Depends(get_async_session),
    sender: EmailSender = Depends(_email_sender_dep),
) -> MagicLinkResponse:
    """Generate a magic link, store its hash, and email the raw token.

    Always returns the same response to prevent email enumeration.
    """
    email = payload.email.lower()
    raw_token, token_hash = generate_magic_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)

    token_row = MagicLinkToken(
        email=email,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(token_row)
    await session.commit()

    try:
        sender.send(email, raw_token)
    except Exception:
        # Swallow send failures so we never reveal whether an email exists.
        pass

    return MagicLinkResponse()


@router.get("/verify", response_model=TokenResponse)
async def verify_magic_link(
    token: str = Query(..., min_length=1),
    email: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_async_session),
    config: ServerConfig = Depends(get_config),
) -> TokenResponse:
    """Verify a magic link, mark the token used, upsert the user, and return a JWT."""
    email_norm = email.lower()
    if not _EMAIL_RE.match(email_norm):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(MagicLinkToken).where(
            MagicLinkToken.email == email_norm,
            MagicLinkToken.token_hash == token_hash,
            MagicLinkToken.used_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    row.used_at = now

    user_result = await session.execute(select(User).where(User.email == email_norm))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(email=email_norm, last_login_at=now)
        session.add(user)
        await session.flush()
    else:
        user.last_login_at = now

    await session.commit()

    access_token = create_jwt(user.id, user.email, config=config)
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, created_at=user.created_at)
