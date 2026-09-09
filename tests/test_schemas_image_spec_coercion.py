"""Issue #632: src/schemas.py ImageSpec (legacy/math copy) must tolerate mistyped fields.

Model-level coercion tests for the ``ImageSpec`` class in ``src/schemas.py``.
This copy is not on the Sentry parse path but must be hardened consistently.
"""

from __future__ import annotations


def test_image_spec_coerces_mistyped_fields_at_model_level() -> None:
    """ImageSpec(data='x', labels='y', title={}) yields {} / {} / '' (#632)."""
    from src.schemas import ImageSpec

    spec = ImageSpec(data="x", labels="y", title={})

    assert spec.data == {}
    assert spec.labels == {}
    assert spec.title == ""

    other_spec = ImageSpec(description={"a": 1})

    assert other_spec.description == ""
