"""Small CLI seam for resolving and reporting generation payloads."""

from __future__ import annotations

import json
import sys
from typing import Any

from src.common.resolver import ResolveConflictError, ResolveResult, resolve


def resolve_and_print(
    payload: dict[str, Any],
    *,
    delimited: bool = False,
) -> ResolveResult:
    """Resolve one CLI payload, print it, or exit with a fielded error."""
    try:
        result = resolve(payload)
    except ResolveConflictError as exc:
        print(json.dumps({"errors": exc.errors}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    except (TypeError, ValueError) as exc:
        print(f"resolve error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    output = json.dumps(
        {"payload": result.payload, "drawn": result.drawn},
        ensure_ascii=False,
        sort_keys=True,
    )
    if delimited:
        print("--- BEGIN RESOLVED PAYLOAD ---")
    print(output)
    if delimited:
        print("--- END RESOLVED PAYLOAD ---")
    return result
