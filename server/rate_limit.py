"""Rate limiter setup using slowapi.

Defines a single shared `Limiter` plus a key function that resolves the JWT
user ID for authenticated endpoints (falling back to remote address).
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from server.auth.dependencies import get_config
from server.auth.tokens import decode_jwt


def jwt_user_key(request: Request) -> str:
    """Return the JWT subject (user id) as the rate-limit key.

    Falls back to the client IP when the Authorization header is missing or
    invalid, so unauthenticated callers still get rate-limited (and don't
    bypass the limiter by stripping the header).
    """
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if header:
        parts = header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            try:
                payload = decode_jwt(parts[1], config=get_config())
                sub = payload.get("sub")
                if sub:
                    return f"user:{sub}"
            except Exception:
                pass
    return get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)
