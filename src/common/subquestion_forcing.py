"""Helpers that override LLM-emitted fields with deterministic sampled values.

Issue #286: 自然科學 年級 must be forced from sampled params, not trusted
from the LLM response.  The same pattern already exists for 科目 (forced to
``["自然科學"]`` in the NS parser).

Issue #290 (future): 社會領域 will call ``force_grade`` here to apply the
identical fix to its own ``_parse_subquestion``.  Both ``SubQuestion``
models carry a mutable ``年級: int`` attribute, so the helper works for
either subject without importing the concrete model class.
"""

from __future__ import annotations

from typing import Any


def force_grade(subquestion: Any, grade: int) -> None:
    """Stamp *grade* onto *subquestion.年級*, ignoring any LLM-emitted value.

    The LLM sometimes copies the 年級 from the prompt's own JSON example
    (which may be a different grade) instead of using the requested grade.
    This function is the single authoritative place that corrects the field.

    Args:
        subquestion: A ``SubQuestion`` instance from either
            ``src.natural_sciences.schemas`` or ``src.social_studies.schemas``.
        grade: The grade sampled by the caller (``params.grade``).
    """
    subquestion.年級 = grade
