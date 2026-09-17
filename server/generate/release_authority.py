"""Build-admission authority reader — issue #771.

Reads the current release-policy document from either a configured HTTP(S)
endpoint or a local fixture. The source is injectable so issue #778 can swap
in a live controller without changing the admission logic.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

SCHEMA = "exam-generation.release-policy/1"
CLIENT_UPDATE_REQUIRED = "CLIENT_UPDATE_REQUIRED"
AUTHORITY_UNAVAILABLE = "AUTHORITY_UNAVAILABLE"
SERVICE_PAUSED = "SERVICE_PAUSED"
AUTHORITY_TIMEOUT_SECONDS = 2.0


@runtime_checkable
class AuthoritySource(Protocol):
    """Configurable source for the release policy document."""

    def read(self) -> Awaitable[dict | None]: ...


class FileAuthoritySource:
    """Read a build-emitted policy fixture from the local filesystem."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def read(self) -> dict | None:
        try:
            raw = json.loads(
                await asyncio.to_thread(self._path.read_text, encoding="utf-8")
            )
            if not isinstance(raw, dict):
                raise ValueError("release policy must be a JSON object")
            return raw
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("release_authority: cannot read %s: %s", self._path, exc)
            return None
        except ValueError as exc:
            logger.warning("release_authority: invalid policy %s: %s", self._path, exc)
            return None


class HttpAuthoritySource:
    """Read the current release policy from an HTTP(S) frontend endpoint.

    A new client is used for every read.  This deliberately avoids retaining a
    positive policy in process memory, so a deployment can observe a release
    change on the next admission request.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout: float = AUTHORITY_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._timeout = min(max(timeout, 0.001), AUTHORITY_TIMEOUT_SECONDS)
        self._transport = transport

    async def read(self) -> dict | None:
        parsed = urlparse(self._url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            logger.warning("release_authority: invalid URL %r", self._url)
            return None
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                async with asyncio.timeout(self._timeout):
                    response = await client.get(self._url)
            if not 200 <= response.status_code < 300:
                logger.warning(
                    "release_authority: URL returned HTTP %s", response.status_code
                )
                return None
            raw = response.json()
            if not isinstance(raw, dict):
                raise ValueError("release policy must be a JSON object")
            return raw
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            logger.warning("release_authority: cannot read %s: %s", self._url, exc)
            return None


def build_authority_source(
    url: str | None,
    path: Path | None,
) -> AuthoritySource | None:
    """Select one authority source, preferring the deployment URL."""
    if url and url.strip():
        return HttpAuthoritySource(url.strip())
    if path is not None:
        return FileAuthoritySource(path)
    return None


async def check_build_admission(
    build_id_header: str | None,
    source: AuthoritySource | None,
) -> JSONResponse | None:
    """Check the X-Frontend-Build-ID header against the authority.

    Returns None on pass (proceed), or a JSONResponse (426/503) to return
    immediately.  Caller pattern: ``if resp := await check_build_admission(...): return resp``.

    Check runs AFTER authentication and stream-version gate but BEFORE any
    generation work, planner dispatch, or provider call.  Zero side effects.
    """
    try:
        raw = await source.read() if source is not None else None
    except Exception as exc:  # pragma: no cover - defensive seam for future sources
        logger.warning("release_authority: source read failed: %s", exc)
        raw = None

    # Authority unavailable — retryable
    if raw is None:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "無法取得版本授權，請稍後再試。"
                    " / Release authority unavailable; please retry."
                ),
                "code": AUTHORITY_UNAVAILABLE,
            },
            headers={"Retry-After": "30"},
        )

    # Unknown schema — treat as unavailable
    schema = raw.get("schema")
    if schema != SCHEMA:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "版本授權格式未知，請稍後再試。"
                    " / Unknown release authority schema; please retry."
                ),
                "code": AUTHORITY_UNAVAILABLE,
            },
            headers={"Retry-After": "30"},
        )

    # Paused / preparing — maintenance mode
    admission = raw.get("admission", "open")
    if admission in ("paused", "preparing"):
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "出題服務暫停維護中，請稍候。"
                    " / Generation is paused for maintenance; please wait."
                ),
                "code": SERVICE_PAUSED,
            },
            headers={"Retry-After": "60"},
        )

    released_build_id: object = raw.get("released_build_id", "")
    if not isinstance(released_build_id, str) or not released_build_id:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "版本授權缺少 released_build_id，請稍後再試。"
                    " / Release authority missing released_build_id; please retry."
                ),
                "code": AUTHORITY_UNAVAILABLE,
            },
            headers={"Retry-After": "30"},
        )

    # Build ID comparison — missing, malformed, or outdated → 426
    header = (build_id_header or "").strip()
    if not header or header != released_build_id:
        return JSONResponse(
            status_code=426,
            content={
                "detail": (
                    "介面版本已更新，請重新整理頁面後再生成。"
                    " / Client build is outdated; please reload the page."
                ),
                "code": CLIENT_UPDATE_REQUIRED,
                "required_build_id": released_build_id,
            },
        )

    return None  # pass
