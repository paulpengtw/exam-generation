"""Build-admission authority reader — issue #771.

Reads the shared release-policy fixture that buildIdentityPlugin emits at
build time. The source is injectable so issue #778 can swap in a live
controller without changing the admission logic.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Default path — buildIdentityPlugin writes this at `npm run build`.
_DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2] / "web" / "dist" / "release" / "policy.json"
)

SCHEMA = "exam-generation.release-policy/1"
CLIENT_UPDATE_REQUIRED = "CLIENT_UPDATE_REQUIRED"
AUTHORITY_UNAVAILABLE = "AUTHORITY_UNAVAILABLE"
SERVICE_PAUSED = "SERVICE_PAUSED"


@runtime_checkable
class AuthoritySource(Protocol):
    """Configurable source for the release policy document."""

    def read(self) -> dict | None: ...


class FileAuthoritySource:
    """Default source — reads the build-emitted fixture file."""

    def __init__(self, path: Path = _DEFAULT_FIXTURE) -> None:
        self._path = path

    def read(self) -> dict | None:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("release_authority: cannot read %s: %s", self._path, exc)
            return None


def check_build_admission(
    build_id_header: str | None,
    source: AuthoritySource,
) -> JSONResponse | None:
    """Check the X-Frontend-Build-ID header against the authority.

    Returns None on pass (proceed), or a JSONResponse (426/503) to return
    immediately.  Caller pattern: ``if resp := check_build_admission(...): return resp``.

    Check runs AFTER authentication and stream-version gate but BEFORE any
    generation work, planner dispatch, or provider call.  Zero side effects.
    """
    raw = source.read()

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
