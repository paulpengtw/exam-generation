"""Generate web/src/api/generated/contract.ts from Pydantic server models.

Run from repo root:

    python scripts/generate_ts_contract.py

Output is deterministic: fields are emitted in model_fields definition order;
SSE event names are emitted in SSEEventName declaration order. No timestamps.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import types
from pathlib import Path
from typing import Literal, Union, get_args, get_origin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.generate.event_protocol import StartedPayload  # noqa: E402
from server.generate.marshalling import EMITTED_EVENT_NAMES, SSEEventName  # noqa: E402
from server.generate.models import (  # noqa: E402
    SERVER_ONLY_GENERATE_FIELDS,
    GenerateParams,
    ResolveFieldError,
    ResolveRequest,
    ResolveResponse,
)

_REGEN_CMD = "python scripts/generate_ts_contract.py"
_OUTPUT_PATH = ROOT / "web" / "src" / "api" / "generated" / "contract.ts"


def _ts_type(annotation: object) -> tuple[str, bool]:
    """Return (ts_type_string, is_optional).

    is_optional=True means the field should carry '?' in the interface.
    Handles: str, int, bool, list[X], Literal[...], Union[X, None], X | None.
    """
    if annotation is str:
        return "string", False
    if annotation is int:
        return "number", False
    if annotation is bool:
        return "boolean", False

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Literal["a", "b"] -> '"a" | "b"'; Literal[2] -> '2'
    if origin is Literal:
        parts = []
        for a in args:
            parts.append(f'"{a}"' if isinstance(a, str) else str(a))
        return " | ".join(parts), False

    if annotation is dict:
        return "Record<string, unknown>", False

    # list[X] -> X[]
    if origin is list:
        inner, _ = _ts_type(args[0])
        return f"{inner}[]", False

    # Union[X, Y, None] or X | None (Python 3.10+)
    if origin is Union or (hasattr(types, "UnionType") and isinstance(annotation, types.UnionType)):  # type: ignore[attr-defined]
        non_none = [a for a in args if a is not type(None)]
        has_none = any(a is type(None) for a in args)
        if len(non_none) == 1:
            inner, _ = _ts_type(non_none[0])
            return inner, has_none
        parts = [_ts_type(a)[0] for a in non_none]
        return " | ".join(parts), has_none

    return "unknown", False


def _field_is_optional(field_info: object) -> bool:
    """Return True if the field has a default value or default_factory."""
    import pydantic_core
    return (
        field_info.default is not pydantic_core.PydanticUndefined  # type: ignore[union-attr]
        or field_info.default_factory is not None  # type: ignore[union-attr]
    )


def _generate_params_block() -> str:
    """Emit the GenerateParams TypeScript interface."""
    import typing

    lines: list[str] = []
    lines.append("/**")
    lines.append(" * Wire params for GET /api/generate.")
    lines.append(" * Source of truth: server/generate/models.py:GenerateParams")
    lines.append(" */")
    lines.append("export interface GenerateParams {")

    hints = typing.get_type_hints(GenerateParams)
    # model_fields preserves declaration order (Pydantic v2)
    for field_name, field_info in GenerateParams.model_fields.items():
        if field_name in SERVER_ONLY_GENERATE_FIELDS:
            continue
        annotation = hints.get(field_name, field_info.annotation)
        ts_type, optional = _ts_type(annotation)
        # Fields with defaults are optional on the wire (caller can omit them)
        has_default = _field_is_optional(field_info)
        optional = optional or has_default
        suffix = "?" if optional else ""
        lines.append(f"  {field_name}{suffix}: {ts_type};")

    lines.append("}")
    return "\n".join(lines)


def _generate_sse_block() -> str:
    """Emit the SSEEventName union type and the emitted-names runtime constant."""
    members = list(SSEEventName)
    emitted = [m for m in members if m.value in EMITTED_EVENT_NAMES]
    declared_only = [m for m in members if m.value not in EMITTED_EVENT_NAMES]

    lines: list[str] = []

    lines.append("/**")
    lines.append(" * All SSE event names declared by the server (full wire vocabulary).")
    lines.append(" * Source of truth: server/generate/marshalling.py:SSEEventName")
    lines.append(" *")
    for d in declared_only:
        lines.append(
            f' * NOTE: "{d.value}" is declared for wire-contract completeness but the'
        )
        lines.append(
            " *       server never emits it. The frontend may still handle it."
        )
    lines.append(" */")
    lines.append("export type SSEEventName =")
    for i, m in enumerate(members):
        sep = "  |" if i > 0 else "  "
        lines.append(f'{sep} "{m.value}"')
    lines.append("  ;")
    lines.append("")

    lines.append("/**")
    lines.append(" * SSE event names the server actually emits at runtime.")
    lines.append(' * Excludes declared-only names (e.g. "progress").')
    lines.append(" * Source of truth: server/generate/marshalling.py:EMITTED_EVENT_NAMES")
    lines.append(" */")
    lines.append("export const SSE_EMITTED_EVENT_NAMES = [")
    for m in emitted:
        lines.append(f'  "{m.value}",')
    lines.append("] as const;")
    lines.append("")
    lines.append("export type SSEEmittedEventName = (typeof SSE_EMITTED_EVENT_NAMES)[number];")

    return "\n".join(lines)


def _generate_resolve_block() -> str:
    """Emit the JSON-body resolve request and response wire types."""
    # ResolveRequest permits the direct partial-payload form as well as the
    # optional {payload, redraws} wrapper; the Pydantic model preserves the
    # direct form's subject-specific fields as extras.
    _ = ResolveRequest, ResolveResponse, ResolveFieldError
    return "\n".join(
        [
            "/**",
            " * Wire body for POST /api/generate/resolve.",
            " * Source of truth: server/generate/models.py:ResolveRequest",
            " * The direct form carries the partial generation fields at the top level;",
            " * callers may instead put them in `payload` beside `redraws`.",
            " */",
            "export interface ResolveRequest {",
            "  payload?: Record<string, unknown>;",
            "  redraws?: Record<string, number>;",
            "  [key: string]: unknown;",
            "}",
            "",
            "/** Completed payload and canonical sampler paths changed by the resolver. */",
            "export interface ResolveResponse {",
            "  payload: Record<string, unknown>;",
            "  drawn: string[];",
            "  cleared: string[];",
            "}",
            "",
            "/** Field-addressed 422 detail emitted for resolver conflicts. */",
            "export interface ResolveFieldError {",
            '  field: string;',
            '  code: "incompatible_parent" | "no_admitting_parent" | "unresolved";',
            "  parent?: string;",
            "}",
        ]
    )


def _generate_started_payload_block() -> str:
    """Emit the StartedPayload TypeScript interface."""
    import types as _types
    import typing

    def _ts_type_nullable(annotation: object) -> tuple[str, bool]:
        """Like _ts_type but emits 'T | null' for Union[T, None] instead of just 'T'."""
        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is Union or (
            hasattr(_types, "UnionType") and isinstance(annotation, _types.UnionType)  # type: ignore[attr-defined]
        ):
            non_none = [a for a in args if a is not type(None)]
            has_none = any(a is type(None) for a in args)
            if len(non_none) == 1 and has_none:
                inner, _ = _ts_type(non_none[0])
                return f"{inner} | null", True
        return _ts_type(annotation)

    lines: list[str] = []
    lines.append("/**")
    lines.append(" * Payload of the 'started' SSE event.")
    lines.append(" * Source of truth: server/generate/event_protocol.py:StartedPayload")
    lines.append(" */")
    lines.append("export interface StartedPayload {")

    hints = typing.get_type_hints(StartedPayload)
    for field_name, field_info in StartedPayload.model_fields.items():
        annotation = hints.get(field_name, field_info.annotation)
        ts_type, optional = _ts_type_nullable(annotation)
        has_default = _field_is_optional(field_info)
        optional = optional or has_default
        suffix = "?" if optional else ""
        lines.append(f"  {field_name}{suffix}: {ts_type};")

    lines.append("}")
    return "\n".join(lines)


def generate_contract() -> str:
    """Return the full contract.ts content as a string (callable from tests)."""
    header = textwrap.dedent(f"""\
        // DO NOT EDIT — generated by {_REGEN_CMD}
        // Regenerate: {_REGEN_CMD}
        //
        // Source of truth:
        //   server/generate/models.py       -> GenerateParams
        //   server/generate/models.py       -> ResolveRequest, ResolveResponse, ResolveFieldError
        //   server/generate/event_protocol.py -> StartedPayload
        //   server/generate/marshalling.py  -> SSEEventName, EMITTED_EVENT_NAMES
    """)

    params_block = _generate_params_block()
    resolve_block = _generate_resolve_block()
    sse_block = _generate_sse_block()
    started_payload_block = _generate_started_payload_block()

    sections = [
        header,
        "// ---------------------------------------------------------------------------",
        "// Generate request params",
        "// ---------------------------------------------------------------------------",
        "",
        params_block,
        "",
        "// ---------------------------------------------------------------------------",
        "// Resolve request/response",
        "// ---------------------------------------------------------------------------",
        "",
        resolve_block,
        "",
        "// ---------------------------------------------------------------------------",
        "// SSE event vocabulary",
        "// ---------------------------------------------------------------------------",
        "",
        sse_block,
        "",
        "// ---------------------------------------------------------------------------",
        "// SSE started event payload",
        "// ---------------------------------------------------------------------------",
        "",
        started_payload_block,
    ]
    return "\n".join(sections) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate TypeScript contract from Pydantic models"
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print to stdout instead of writing to the output file",
    )
    args = parser.parse_args()

    content = generate_contract()

    if args.stdout:
        sys.stdout.write(content)
    else:
        _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _OUTPUT_PATH.write_text(content, encoding="utf-8")
        print(f"Written: {_OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
