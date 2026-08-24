"""Pure composition-rule checks for social-studies ICCS pins."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

KNOWING_DEFINING_LIMIT_RULE = "至多1題 Knowing–Defining and Describing"
CROSS_SUBJECT_RELATE_RULE = "跨科需含 Relate-or-Integrate"

_KNOWING_DEFINING = "Knowing–Defining and Describing"
_KNOWING_ILLUSTRATING = "Knowing–Illustrating with examples"
_REASONING_INTERPRET = "Reasoning and Applying–Interpret information"
_REASONING_RELATE = "Reasoning and Applying–Relate or Integrate"
_COGNITIVE_PROCESS_VALUES = frozenset(
    {
        _KNOWING_DEFINING,
        _KNOWING_ILLUSTRATING,
        _REASONING_INTERPRET,
        _REASONING_RELATE,
    }
)


def _assignment_value(assignment: Any) -> str | None:
    if assignment is None:
        return None
    if isinstance(assignment, str):
        value = assignment
    elif isinstance(assignment, dict):
        value = assignment.get("cognitive_process") or assignment.get("認知歷程")
    else:
        value = getattr(assignment, "認知歷程", None)
        if value is None:
            value = getattr(assignment, "cognitive_process", None)
    if isinstance(value, str) and value in _COGNITIVE_PROCESS_VALUES:
        return value
    return None


def find_pin_rule_violations(
    pinned_assignments: Iterable[Any],
    subject: Any,
) -> list[str]:
    """Return composition rules already made impossible by the supplied pins.

    ``None`` represents an unpinned slot. Such a slot can still satisfy the
    cross-subject Relate-or-Integrate guarantee, so that rule is reported only
    when every supplied slot is pinned and none is Relate-or-Integrate.
    """
    assignments = [_assignment_value(item) for item in pinned_assignments]
    violations: list[str] = []

    if assignments.count(_KNOWING_DEFINING) > 1:
        violations.append(KNOWING_DEFINING_LIMIT_RULE)

    subject_value = getattr(subject, "value", subject)
    if (
        subject_value == "跨科"
        and _REASONING_RELATE not in assignments
        and assignments
        and all(assignment is not None for assignment in assignments)
    ):
        violations.append(CROSS_SUBJECT_RELATE_RULE)

    return violations


# Short aliases keep the helper discoverable for callers that describe this as
# a composition-rule check rather than a pin check.
find_composition_rule_violations = find_pin_rule_violations
composition_rule_violations = find_pin_rule_violations
