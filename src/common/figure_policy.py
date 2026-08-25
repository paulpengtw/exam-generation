"""Pure validation helpers for question figure-routing policy."""

from __future__ import annotations

from src.social_studies.figure_kind_loader import (
    CANONICAL_FIGURE_KINDS,
    FIGURE_KIND_ALIASES,
)

__all__ = [
    "CONTENT_TYPE_ALLOWED_RENDER_MODES",
    "allowed_render_modes",
    "effective_figure_kind",
    "find_figure_kind_collisions",
    "normalize_figure_kind",
    "validate_figure_routing",
    "validate_question_figure_routing",
]


CONTENT_TYPE_ALLOWED_RENDER_MODES: dict[str, frozenset[str] | None] = {
    "純文字": frozenset(),
    "含圖片": frozenset({"gpt_image", "html"}),
    "graphs/charts/tables": frozenset({"chart", "html"}),
    "customized": None,
}


_CANONICAL_FIGURE_KIND_BY_KEY = {
    kind.casefold(): kind for kind in CANONICAL_FIGURE_KINDS
}


def allowed_render_modes(content_type: str | None) -> frozenset[str] | None:
    """Return the allowed render modes, or None for an unconstrained type."""
    try:
        return CONTENT_TYPE_ALLOWED_RENDER_MODES.get(content_type)
    except Exception:
        return None


def _get_attribute(value: object, name: str) -> object | None:
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def _get_render_mode(chart_spec: object) -> object | None:
    try:
        if isinstance(chart_spec, dict):
            return chart_spec.get("render_mode")
        return getattr(chart_spec, "render_mode", None)
    except Exception:
        return None


def effective_figure_kind(spec: object | None) -> str:
    """Return the declared kind, or a chart type fallback for chart specs.

    The field remains free text.  A non-chart spec without ``figure_kind`` has
    no comparable kind rather than borrowing its renderer or description.
    """
    if spec is None:
        return ""
    try:
        figure_kind = (
            spec.get("figure_kind")
            if isinstance(spec, dict)
            else getattr(spec, "figure_kind", "")
        )
        if isinstance(figure_kind, str) and figure_kind.strip():
            return figure_kind.strip()

        render_mode = _get_render_mode(spec)
        chart_type = (
            spec.get("chart_type")
            if isinstance(spec, dict)
            else getattr(spec, "chart_type", None)
        )
        if render_mode == "chart" and isinstance(chart_type, str):
            return chart_type.strip()
    except Exception:
        return ""
    return ""


def normalize_figure_kind(value: str) -> str:
    """Return the canonical key for a known kind, or normalized free text.

    Canonical labels and their data-backed aliases resolve to the canonical
    label. Unknown labels remain legal free text and only receive the existing
    strip/casefold normalization.
    """
    if not isinstance(value, str):
        return ""
    normalized = value.strip().casefold()
    if not normalized:
        return ""
    return _CANONICAL_FIGURE_KIND_BY_KEY.get(
        normalized,
        FIGURE_KIND_ALIASES.get(normalized, normalized),
    )


def _normalized_figure_kind(spec: object | None) -> str:
    return normalize_figure_kind(effective_figure_kind(spec))


def find_figure_kind_collisions(
    specs: list,
    pinned: set[int],
    allow_duplicates: bool,
) -> list[tuple[int, int, str]]:
    """Return pairwise figure-kind collisions as ``(left, right, normalized_kind)``.

    Empty kinds never collide.  Pinned specs reserve their kind for the
    unpinned specs to yield to, while two pinned specs are allowed to share a
    kind.  When ``allow_duplicates`` is true the request-level kill-switch
    makes this a no-op.
    """
    if allow_duplicates:
        return []

    pinned_indices = set(pinned)
    collisions: list[tuple[int, int, str]] = []
    seen: dict[str, list[int]] = {}
    for index, spec in enumerate(specs):
        normalized = _normalized_figure_kind(spec)
        if not normalized:
            continue
        for previous in seen.get(normalized, []):
            if not (previous in pinned_indices and index in pinned_indices):
                collisions.append((previous, index, normalized))
        seen.setdefault(normalized, []).append(index)
    return collisions


def _allowed_modes_text(allowed: frozenset[str]) -> str:
    return "{" + ", ".join(sorted(allowed)) + "}"


def validate_figure_routing(content_type: str | None, chart_spec: object | None) -> list[str]:
    """Return routing violations for one content type and chart specification."""
    try:
        allowed = allowed_render_modes(content_type)
        if allowed is None:
            return []

        if not allowed:
            if chart_spec is None:
                return []
            return [f"{content_type} 題目不得有 chart_spec；chart_spec 必須為 None。"]

        modes_text = _allowed_modes_text(allowed)
        if chart_spec is None:
            return [f"{content_type} 題目必須有 chart_spec，render_mode 必須是 {modes_text}。"]

        render_mode = _get_render_mode(chart_spec)
        if not isinstance(render_mode, str) or render_mode not in allowed:
            return [
                f"{content_type} 的 chart_spec.render_mode 必須是 {modes_text}；"
                f"目前為 {render_mode!r}。"
            ]
        return []
    except Exception:
        return [f"{content_type} 的 chart_spec routing 無法驗證。"]


def validate_question_figure_routing(question: object) -> list[str]:
    """Return routing violations for a question and each of its subquestions."""
    violations: list[str] = []
    try:
        violations.extend(
            validate_figure_routing(
                _get_attribute(question, "題目內容類型"),
                _get_attribute(question, "chart_spec"),
            )
        )

        subquestions = _get_attribute(question, "subquestions")
        if not subquestions:
            return violations

        for index, subquestion in enumerate(subquestions, start=1):
            subquestion_violations = validate_figure_routing(
                _get_attribute(subquestion, "題目內容類型"),
                _get_attribute(subquestion, "chart_spec"),
            )
            if not subquestion_violations:
                continue
            sequence = _get_attribute(subquestion, "序號")
            label = f"小題 {sequence}" if sequence is not None else f"小題 {index}"
            violations.extend(f"{label}: {violation}" for violation in subquestion_violations)
    except Exception:
        return violations
    return violations
