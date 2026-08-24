"""Pure scoring helpers for digital social-studies interactions."""

from __future__ import annotations

from collections.abc import Mapping

from src.social_studies.schemas import DragDropSpec, SliderSpec


def score_interaction(
    spec: DragDropSpec | SliderSpec,
    response: Mapping[str, object] | float | int,
) -> tuple[int, int]:
    """Return ``(score, max_score)`` for the locked interaction response shape.

    Drag-drop responses may be either the placement map itself or
    ``{"placements": placement_map}``; slider responses may be a numeric value
    or ``{"value": numeric_value}``.
    """
    if isinstance(spec, DragDropSpec):
        placements: object = response
        if isinstance(response, Mapping) and "placements" in response:
            placements = response["placements"]
        if not isinstance(placements, Mapping):
            raise TypeError("drag-drop response must contain a placements mapping")

        max_score = len(spec.correct_mapping)
        correct_count = sum(
            placements.get(draggable_id) == target_id
            for draggable_id, target_id in spec.correct_mapping.items()
        )
        if spec.exact_match:
            all_placements_correct = (
                set(placements) == set(spec.correct_mapping)
                and correct_count == max_score
            )
            score = max_score if all_placements_correct else 0
        else:
            score = correct_count
        return int(score), max_score

    if isinstance(spec, SliderSpec):
        value: object = response
        if isinstance(response, Mapping):
            value = response.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("slider response must contain a numeric value")
        score = int(abs(float(value) - spec.correct_value) <= spec.tolerance)
        return score, 1

    raise TypeError(f"unsupported interaction spec: {type(spec).__name__}")
