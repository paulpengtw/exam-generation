"""Pure validation helpers for question figure-routing policy."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from numbers import Real

from src.social_studies.figure_kind_loader import (
    CANONICAL_FIGURE_KINDS,
    FIGURE_KIND_ALIASES,
)

__all__ = [
    "CONTENT_TYPE_ALLOWED_RENDER_MODES",
    "FIGURE_DATA_ABSOLUTE_EPSILON",
    "FIGURE_DATA_RELATIVE_TOLERANCE",
    "FIGURE_DATA_REPAIR_MARKER",
    "FigureConsistencySpec",
    "FigureDataInconsistency",
    "FigureDataConsistencyResult",
    "build_figure_consistency_entries",
    "allowed_render_modes",
    "enforce_figure_data_consistency",
    "effective_figure_kind",
    "find_data_inconsistencies",
    "find_figure_kind_collisions",
    "normalize_figure_kind",
    "reconcile_figure_data_consistency",
    "repair_figure_data_specs",
    "validate_figure_routing",
    "validate_question_figure_routing",
]


CONTENT_TYPE_ALLOWED_RENDER_MODES: dict[str, frozenset[str] | None] = {
    "純文字": frozenset(),
    "含圖片": frozenset({"gpt_image", "html"}),
    "graphs/charts/tables": frozenset({"chart", "html"}),
    "customized": None,
}

# Cross-figure data is considered inconsistent only when the difference is
# larger than both the relative tolerance and the small-value epsilon.  The
# epsilon keeps harmless rounding noise around zero from becoming a warning.
FIGURE_DATA_RELATIVE_TOLERANCE = 0.05
FIGURE_DATA_ABSOLUTE_EPSILON = 0.1
FIGURE_DATA_REPAIR_MARKER = "__figure_data_consistency__"


@dataclass(frozen=True)
class FigureDataInconsistency:
    """One conflicting value shared by two visual specifications."""

    left_index: int
    right_index: int
    series: str
    x: object
    left_value: float
    right_value: float
    unit: str


@dataclass(frozen=True)
class FigureConsistencySpec:
    """A visual spec plus the subject-owned setter used by one repair call."""

    index: int
    label: str
    spec: object
    repair_key: str
    set_spec: Callable[[object], bool]


@dataclass(frozen=True)
class FigureDataConsistencyResult:
    """Initial/final detector state and the one shared repair attempt."""

    initial_conflicts: list[FigureDataInconsistency]
    final_conflicts: list[FigureDataInconsistency]
    repair_attempted: bool = False
    repair_succeeded: bool = False
    repair_error: str | None = None


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


_SERIES_NAME_ALIASES = {
    "oil": "oil",
    "petroleum": "oil",
    "crude oil": "oil",
    "石油": "oil",
    "原油": "oil",
    "coal": "coal",
    "煤": "coal",
    "煤炭": "coal",
    "natural gas": "natural gas",
    "天然氣": "natural gas",
    "天然气": "natural gas",
    "renewable": "renewable energy",
    "renewables": "renewable energy",
    "renewable energy": "renewable energy",
    "再生能源": "renewable energy",
}


@dataclass(frozen=True)
class _FigureSeries:
    name: str
    points: dict[str, tuple[object, float]]
    unit: str | None


def _field(value: object, name: str, default: object | None = None) -> object | None:
    try:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)
    except Exception:
        return default


def _normalized_text(value: object) -> str:
    return re.sub(r"[\s_-]+", " ", str(value).strip()).casefold()


def _normalized_series_name(value: object) -> str:
    normalized = _normalized_text(value)
    return _SERIES_NAME_ALIASES.get(normalized, normalized)


def _x_key(value: object) -> str:
    if isinstance(value, Real) and not isinstance(value, bool):
        number = float(value)
        if isfinite(number) and number.is_integer():
            return str(int(number))
    return _normalized_text(value)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Real):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().replace(",", ""))
        except ValueError:
            return None
    else:
        return None
    return number if isfinite(number) else None


def _unit_from_axis_label(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    label = value.strip()
    parenthetical = re.search(r"[（(]\s*([^()（）]+?)\s*[)）]\s*$", label)
    if parenthetical:
        return _normalized_text(parenthetical.group(1))
    if "%" in label or "％" in label:
        return "%"
    return _normalized_text(label)


def _spec_unit(spec: object, data: Mapping) -> str | None:
    for source in (spec, data, _field(spec, "labels", {})):
        if not isinstance(source, Mapping):
            continue
        for key in ("unit", "y_unit", "value_unit"):
            unit = _unit_from_axis_label(source.get(key))
            if unit:
                return unit
        if source is _field(spec, "labels", {}):
            unit = _unit_from_axis_label(source.get("y"))
            if unit:
                return unit
    return None


def _x_labels(data: Mapping, series: Mapping | None = None) -> list[object] | None:
    for source in (series, data):
        if not isinstance(source, Mapping):
            continue
        for key in ("x_labels", "x_values", "x"):
            values = source.get(key)
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                return list(values)
    return None


def _series_points(
    values: object,
    x_labels: list[object] | None,
) -> dict[str, tuple[object, float]]:
    if isinstance(values, Mapping):
        pairs = values.items()
    elif (
        isinstance(values, Sequence)
        and not isinstance(values, (str, bytes))
        and x_labels is not None
    ):
        pairs = zip(x_labels, values)
    else:
        return {}

    points: dict[str, tuple[object, float]] = {}
    for x_value, y_value in pairs:
        number = _number(y_value)
        if number is not None:
            points.setdefault(_x_key(x_value), (x_value, number))
    return points


def _series_from_item(
    name: object,
    item: object,
    default_x_labels: list[object] | None,
    default_unit: str | None,
) -> _FigureSeries | None:
    if not isinstance(name, str) or not name.strip():
        return None
    if isinstance(item, Mapping):
        values = next(
            (item.get(key) for key in ("values", "y_values", "data") if key in item),
            None,
        )
        unit = _unit_from_axis_label(item.get("unit")) or default_unit
        x_labels = _x_labels({}, item) or default_x_labels
    else:
        values = item
        unit = default_unit
        x_labels = default_x_labels
    points = _series_points(values, x_labels)
    return _FigureSeries(name.strip(), points, unit) if points else None


def _extract_table_series(data: Mapping, unit: str | None) -> list[_FigureSeries]:
    """Read the repository's ``columns``/``rows`` table representation."""
    columns = data.get("columns")
    rows = data.get("rows")
    if not (
        isinstance(columns, Sequence)
        and not isinstance(columns, (str, bytes))
        and len(columns) >= 2
        and isinstance(rows, Sequence)
        and not isinstance(rows, (str, bytes))
    ):
        return []

    x_column = columns[0]
    if not isinstance(x_column, str) or not x_column.strip():
        return []
    series: list[_FigureSeries] = []
    for column_offset, name in enumerate(columns[1:], start=1):
        if not isinstance(name, str) or not name.strip():
            continue
        points: dict[str, tuple[object, float]] = {}
        for row in rows:
            if isinstance(row, Mapping):
                if x_column in row:
                    x_value = row[x_column]
                elif "x" in row:
                    x_value = row["x"]
                else:
                    continue
                if name not in row:
                    continue
                y_value = row[name]
            elif isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
                if len(row) <= column_offset:
                    continue
                x_value = row[0]
                y_value = row[column_offset]
            else:
                continue
            number = _number(y_value)
            if number is not None:
                points.setdefault(_x_key(x_value), (x_value, number))
        if points:
            series.append(_FigureSeries(name.strip(), points, unit))
    return series


def _extract_series(spec: object) -> list[_FigureSeries]:
    data = _field(spec, "data", {})
    if not isinstance(data, Mapping):
        return []
    default_x_labels = _x_labels(data)
    default_unit = _spec_unit(spec, data)
    raw_series = data.get("series")
    series: list[_FigureSeries] = []

    table_series = _extract_table_series(data, default_unit)
    if table_series:
        return table_series

    if isinstance(raw_series, Sequence) and not isinstance(raw_series, (str, bytes)):
        for item in raw_series:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name", item.get("label", item.get("series_name")))
            parsed = _series_from_item(name, item, default_x_labels, default_unit)
            if parsed is not None:
                series.append(parsed)
    elif isinstance(raw_series, Mapping):
        for name, item in raw_series.items():
            parsed = _series_from_item(name, item, default_x_labels, default_unit)
            if parsed is not None:
                series.append(parsed)
    else:
        reserved = {"x_labels", "x_values", "x", "unit", "y_unit", "value_unit"}
        for name, item in data.items():
            if name in reserved:
                continue
            parsed = _series_from_item(name, item, default_x_labels, default_unit)
            if parsed is not None:
                series.append(parsed)
    return series


def build_figure_consistency_entries(
    question: object,
    parse_spec: Callable[[object], object | None],
    repair_key: Callable[[object], str],
) -> list[FigureConsistencySpec]:
    """Build shared policy entries from either subject's question models."""
    entries: list[FigureConsistencySpec] = []
    top_spec = _field(question, "chart_spec")
    if top_spec is not None:
        def set_top_level(raw_spec: object) -> bool:
            repaired = parse_spec(raw_spec)
            if repaired is None:
                return False
            current = _field(question, "chart_spec")
            changed = current != repaired
            setattr(question, "chart_spec", repaired)
            return changed

        entries.append(
            FigureConsistencySpec(
                index=len(entries),
                label="題幹",
                spec=top_spec,
                repair_key="題幹",
                set_spec=set_top_level,
            )
        )

    subquestions = _field(question, "subquestions", [])
    if not isinstance(subquestions, Sequence) or isinstance(subquestions, (str, bytes)):
        return entries
    for sub in subquestions:
        sub_spec = _field(sub, "chart_spec")
        if sub_spec is None:
            continue

        def set_subquestion(raw_spec: object, sub: object = sub) -> bool:
            repaired = parse_spec(raw_spec)
            if repaired is None:
                return False
            current = _field(sub, "chart_spec")
            changed = current != repaired
            setattr(sub, "chart_spec", repaired)
            return changed

        entries.append(
            FigureConsistencySpec(
                index=len(entries),
                label=f"小題 {_field(sub, '序號')}",
                spec=sub_spec,
                repair_key=repair_key(sub),
                set_spec=set_subquestion,
            )
        )
    return entries


def find_data_inconsistencies(
    specs: Sequence[object],
    *,
    relative_tolerance: float = FIGURE_DATA_RELATIVE_TOLERANCE,
    absolute_epsilon: float = FIGURE_DATA_ABSOLUTE_EPSILON,
) -> list[FigureDataInconsistency]:
    """Find contradictory values in shared, like-unit series across specs.

    The comparison is intentionally narrower than a general chart validator:
    unnamed series, unknown units, non-overlapping x-values, different series,
    and agreeing subsets are ignored.  Both named ``data.series`` and the
    repository's named table columns are supported.  This permits a legitimate
    zoom or subset while still catching a figure that reassigns a shared data
    point.
    """
    parsed_specs = [_extract_series(spec) for spec in specs]
    inconsistencies: list[FigureDataInconsistency] = []
    for left_index, left_series in enumerate(parsed_specs):
        left_by_name = {
            _normalized_series_name(series.name): series for series in left_series
        }
        for right_index in range(left_index + 1, len(parsed_specs)):
            right_by_name = {
                _normalized_series_name(series.name): series
                for series in parsed_specs[right_index]
            }
            for name, left in left_by_name.items():
                right = right_by_name.get(name)
                if right is None or left.unit is None or left.unit != right.unit:
                    continue
                for x_key, (x_value, left_value) in left.points.items():
                    right_point = right.points.get(x_key)
                    if right_point is None:
                        continue
                    _right_x_value, right_value = right_point
                    difference = abs(left_value - right_value)
                    threshold = max(
                        absolute_epsilon,
                        relative_tolerance * max(abs(left_value), abs(right_value)),
                    )
                    if difference > threshold:
                        inconsistencies.append(
                            FigureDataInconsistency(
                                left_index=left_index,
                                right_index=right_index,
                                series=left.name,
                                x=x_value,
                                left_value=left_value,
                                right_value=right_value,
                                unit=left.unit,
                            )
                        )
    return inconsistencies


def _dump_spec(spec: object) -> dict:
    if hasattr(spec, "model_dump"):
        try:
            dumped = spec.model_dump(mode="json", exclude_none=True)
        except TypeError:
            dumped = spec.model_dump(exclude_none=True)
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return dict(spec) if isinstance(spec, Mapping) else {}


def _repair_response_updates(response: object) -> tuple[dict[str, object], object | None]:
    """Extract labelled chart specs and an optional one-spec fallback."""
    if not isinstance(response, Mapping):
        return {}, None
    updates: dict[str, object] = {}
    raw_updates = response.get("chart_specs") or response.get("reconciled_specs")
    if isinstance(raw_updates, Mapping):
        for label, raw in raw_updates.items():
            if isinstance(raw, Mapping) and (
                "chart_spec" in raw or "image_spec" in raw
            ):
                raw = raw.get("chart_spec") or raw.get("image_spec")
            updates[str(label)] = raw
    elif isinstance(raw_updates, Sequence) and not isinstance(raw_updates, (str, bytes)):
        for item in raw_updates:
            if not isinstance(item, Mapping):
                continue
            label = item.get("label", item.get("target"))
            if label is None and item.get("index") is not None:
                label = f"__index_{item['index']}"
            raw = item.get("chart_spec") or item.get("image_spec") or item.get("spec")
            if label is not None and isinstance(raw, Mapping):
                updates[str(label)] = raw

    raw_subquestions = response.get("subquestions")
    if isinstance(raw_subquestions, Sequence) and not isinstance(raw_subquestions, (str, bytes)):
        for item in raw_subquestions:
            if not isinstance(item, Mapping):
                continue
            index = item.get("序號", item.get("index"))
            raw = item.get("chart_spec") or item.get("image_spec")
            if index is not None and isinstance(raw, Mapping):
                updates[f"__index_{index}"] = raw

    generic = response.get("chart_spec") or response.get("image_spec")
    if generic is None and "render_mode" in response and (
        "data" in response or "description" in response
    ):
        generic = response
    return updates, generic


_FIGURE_DATA_REPAIR_SYSTEM_PROMPT = """\
你是題組視覺資料一致性修復器。請只輸出合法 JSON 物件，不要輸出其他文字。
你會收到一個題幹圖與一個或多個小題圖；題幹圖（若存在）是 single source of truth。
若沒有題幹圖，請以提供的第一張圖作為 single source of truth。
保留每張圖原本的 render_mode、chart_type、標題與圖像種類，只修正互相矛盾的資料值。
輸出格式必須是 {"chart_specs": [{"label": "小題 1", "chart_spec": {...}}]}，
每個待修復的小題都要輸出一個完整的 chart_spec。
"""


def repair_figure_data_specs(
    client: object,
    source: FigureConsistencySpec,
    candidates: Sequence[FigureConsistencySpec],
    conflicts: Sequence[FigureDataInconsistency],
) -> bool:
    """Ask one model call to reconcile every non-source conflicting spec."""
    labels = {source.index: source.label}
    labels.update({entry.index: entry.label for entry in candidates})
    conflict_lines = [
        (
            f"{conflict.series} @ {conflict.x!r}: "
            f"{labels.get(conflict.left_index, conflict.left_index)}="
            f"{conflict.left_value:g}, "
            f"{labels.get(conflict.right_index, conflict.right_index)}="
            f"{conflict.right_value:g} {conflict.unit}"
        )
        for conflict in conflicts
    ]
    user_prompt = (
        "single source of truth: "
        f"{source.label}\n\n"
        "conflicting values to reconcile:\n"
        f"{chr(10).join(conflict_lines)}\n\n"
        f"source figure ({source.label}): {_dump_spec(source.spec)}\n\n"
        "figures to repair:\n"
        + "\n".join(
            f"{entry.label}: {_dump_spec(entry.spec)}" for entry in candidates
        )
    )
    response = client.generate_json(
        _FIGURE_DATA_REPAIR_SYSTEM_PROMPT,
        user_prompt,
        purpose="generate",
    )
    updates, generic = _repair_response_updates(response)
    applied = False
    for entry in candidates:
        raw_spec = updates.get(entry.label)
        if raw_spec is None:
            raw_spec = updates.get(f"__index_{entry.index}")
        if raw_spec is None:
            raw_spec = generic
        if isinstance(raw_spec, Mapping):
            applied = bool(entry.set_spec(raw_spec)) or applied
    return applied


def reconcile_figure_data_consistency(
    entry_provider: Callable[[], Sequence[FigureConsistencySpec]],
    *,
    attempted: set[str],
    repair: Callable[
        [FigureConsistencySpec, Sequence[FigureConsistencySpec],
         Sequence[FigureDataInconsistency]], bool
    ] | None = None,
) -> FigureDataConsistencyResult:
    """Detect once, spend the shared repair budget once, and detect again.

    The provider must return the 題幹 first when it exists.  Every non-source
    spec involved in a conflict is a repair candidate; candidates whose
    existing declaration/spec budget was already spent are left for the
    degrade-never-block warning path.
    """
    entries = list(entry_provider())
    initial_conflicts = find_data_inconsistencies([entry.spec for entry in entries])
    if not initial_conflicts:
        return FigureDataConsistencyResult([], [])

    source = entries[0]
    candidate_indices = sorted({
        index
        for conflict in initial_conflicts
        for index in (conflict.left_index, conflict.right_index)
        if index != source.index
    })
    candidates = [
        entries[index]
        for index in candidate_indices
        if index < len(entries) and entries[index].repair_key not in attempted
    ]
    repair_attempted = False
    repair_succeeded = False
    repair_error: str | None = None
    if candidates and repair is not None and FIGURE_DATA_REPAIR_MARKER not in attempted:
        repair_attempted = True
        attempted.add(FIGURE_DATA_REPAIR_MARKER)
        attempted.update(entry.repair_key for entry in candidates)
        try:
            repair_succeeded = repair(source, candidates, initial_conflicts)
        except Exception as exc:  # pragma: no cover - caller warning covers failures
            repair_error = str(exc)

    final_entries = list(entry_provider())
    final_conflicts = find_data_inconsistencies(
        [entry.spec for entry in final_entries]
    )
    return FigureDataConsistencyResult(
        initial_conflicts=initial_conflicts,
        final_conflicts=final_conflicts,
        repair_attempted=repair_attempted,
        repair_succeeded=repair_succeeded,
        repair_error=repair_error,
    )


def enforce_figure_data_consistency(
    entry_provider: Callable[[], Sequence[FigureConsistencySpec]],
    *,
    attempted: set[str],
    client: object | None,
    on_unresolved: Callable[
        [FigureDataInconsistency, Sequence[FigureConsistencySpec]], None
    ] | None = None,
) -> FigureDataConsistencyResult:
    """Run shared data policy and report each remaining conflict to a caller."""
    repair = None
    if client is not None:
        def repair(
            source: FigureConsistencySpec,
            candidates: Sequence[FigureConsistencySpec],
            conflicts: Sequence[FigureDataInconsistency],
        ) -> bool:
            return repair_figure_data_specs(client, source, candidates, conflicts)

    result = reconcile_figure_data_consistency(
        entry_provider,
        attempted=attempted,
        repair=repair,
    )
    if result.final_conflicts and on_unresolved is not None:
        entries = list(entry_provider())
        for conflict in result.final_conflicts:
            if conflict.left_index >= len(entries) or conflict.right_index >= len(entries):
                continue
            on_unresolved(conflict, entries)
    return result


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
