"""Request-boundary validation for generation parameters."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.generate.models import GenerateParams


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("set_type", ""),
        ("sub_context", ""),
        ("style", [""]),
        ("q_type", [""]),
        ("context", [""]),
        ("subject_filter", [""]),
        ("science_competency", [""]),
    ],
)
def test_generate_params_rejects_empty_enum_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        GenerateParams(**{field: value})


def test_generate_params_rejects_incompatible_context_and_sub_context() -> None:
    with pytest.raises(
        ValidationError,
        match=r"context.*sub_context.*incompatible",
    ):
        GenerateParams(
            subject="natural_sciences",
            context=["Global"],
            sub_context="Maintenance of health",
        )
