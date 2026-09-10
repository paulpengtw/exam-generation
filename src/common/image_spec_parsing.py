"""Shared, never-raising ImageSpec parser for all subjects.

Issue #633: collapse the duplicated image_spec fallback ladder that existed
inside ``_parse_text_shell`` (social studies and natural sciences) and
``_parse_image_spec`` / ``_parse_subquestion_image_spec`` into one function.

The fallback ladder has three rungs:

1. Direct construction: ``model_cls(**raw_spec)`` — succeeds for all valid
   payloads and, thanks to the coercers added in #630/#631, for any payload
   whose only problems are wrong-typed ``data``, ``labels``, ``title``,
   ``description`` or ``figure_kind`` fields.

2. Chart-mode repair: if the LLM emitted a bad ``render_mode`` but left a
   recognisable ``chart_type``, force ``render_mode="chart"`` and keep
   everything else.  If this rung also fails (e.g. ``chart_type`` itself is
   not a valid literal), the function returns ``None`` rather than attempting
   the HTML rung — a model that intended a chart type but provided an invalid
   one should not silently become an HTML spec.

3. HTML-mode fallback: tried only when no ``chart_type`` is present.
   Preserves the ``html`` field, which the old ``_parse_text_shell`` ladder
   forgot to carry (fixed here as part of #633 slice 1).

If all applicable rungs fail, or if ``raw_spec`` is not a dict, the function
returns ``None``; it never re-raises.

Complexity note (ADR 0025): the ladder earns its keep only for a bad
``render_mode``.  All other field coercions now live in the model validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from pydantic import BaseModel

T = TypeVar("T", bound="BaseModel")


def parse_image_spec(raw_spec: object, model_cls: type[T]) -> T | None:
    """Parse *raw_spec* into *model_cls*, falling back gracefully on bad fields.

    Parameters
    ----------
    raw_spec:
        The raw dict from LLM output (``image_spec`` or ``chart_spec`` key).
        Any non-dict value returns ``None`` immediately.
    model_cls:
        The subject-specific ``ImageSpec`` Pydantic model class
        (``src.social_studies.schemas.ImageSpec`` or
        ``src.natural_sciences.schemas.ImageSpec``).

    Returns
    -------
    model_cls instance, or ``None`` when every applicable rung fails.
    """
    if not isinstance(raw_spec, dict):
        return None

    # Rung 1: direct construction — handles all valid payloads and every
    # wrong-typed coercible field (#630/#631 validators do the work here).
    try:
        return model_cls(**raw_spec)
    except Exception:
        pass

    # Rung 2: chart-mode repair for a bad render_mode.
    # If chart_type is present but also invalid, return None — the LLM
    # explicitly requested a chart type that cannot be honoured; silently
    # producing an HTML spec would misrepresent the intent.
    if raw_spec.get("chart_type"):
        try:
            return model_cls(
                render_mode="chart",
                chart_type=raw_spec.get("chart_type"),
                figure_kind=raw_spec.get("figure_kind", ""),
                data=raw_spec.get("data", {}),
                labels=raw_spec.get("labels", {}),
                title=raw_spec.get("title", ""),
                description=raw_spec.get("description", ""),
            )
        except Exception:
            return None

    # Rung 3: HTML-mode fallback (only reached when no chart_type is present).
    # Preserves ``html`` — omitted by the old _parse_text_shell ladder (#633
    # slice 1 fix).
    try:
        kwargs: dict[str, Any] = dict(
            render_mode="html",
            figure_kind=raw_spec.get("figure_kind", ""),
            description=raw_spec.get("description", raw_spec.get("title", "")),
            title=raw_spec.get("title", ""),
            data=raw_spec.get("data", {}),
            html=raw_spec.get("html", ""),
        )
        return model_cls(**kwargs)
    except Exception:
        return None
