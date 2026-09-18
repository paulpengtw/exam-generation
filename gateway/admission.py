"""Pure classification of requests that start new generation."""

PAUSED_DETAIL = "目前暫停受理新的出題請求，請稍後再試。"
PAUSED_CODE = "GENERATION_ADMISSION_PAUSED"


def is_private_path(path: str) -> bool:
    """Return True for paths that must never be proxied to the public internet.

    The gateway returns 404 for these paths so the public entry cannot
    reach internal telemetry endpoints.
    """
    return path.startswith("/internal/") or path == "/internal"


def is_generation_entry(method: str, path: str) -> bool:
    """Accept an HTTP method and URL path, excluding the query string."""
    return method in {"GET", "POST"} and path in {"/api/generate", "/api/generate/"}
