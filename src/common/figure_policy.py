"""Pure validation helpers for question figure-routing policy."""

from __future__ import annotations

__all__ = [
    "CONTENT_TYPE_ALLOWED_RENDER_MODES",
    "allowed_render_modes",
    "validate_figure_routing",
    "validate_question_figure_routing",
]


CONTENT_TYPE_ALLOWED_RENDER_MODES: dict[str, frozenset[str] | None] = {
    "純文字": frozenset(),
    "含圖片": frozenset({"gpt_image", "html"}),
    "graphs/charts/tables": frozenset({"chart", "html"}),
    "customized": None,
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
