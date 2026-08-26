"""Subject-specific handling of core_competency request parameters."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.generate.models import GenerateParams
from src.common.resolver import resolve
from src.social_studies.cli import _ss_params_from_resolved


def test_social_studies_uses_requested_core_competencies() -> None:
    params = GenerateParams(
        subject="social_studies",
        core_competency=["社-J-A1", "社-J-C3"],
    )
    result = resolve(
        {
            **params.model_dump(mode="json"),
            "seed": 1,
        }
    )
    sampled = _ss_params_from_resolved(result.payload)

    assert [competency.value for competency in sampled.核心素養] == [
        "社-J-A1",
        "社-J-C3",
    ]


def test_natural_sciences_rejects_core_competency() -> None:
    with pytest.raises(ValidationError, match="core_competency"):
        GenerateParams(
            subject="natural_sciences",
            core_competency=["自-J-A1"],
        )


@pytest.mark.parametrize("extra_params", [{}, {"core_competency": []}])
def test_natural_sciences_accepts_empty_or_absent_core_competency(
    extra_params: dict[str, object],
) -> None:
    params = GenerateParams(subject="natural_sciences", **extra_params)

    assert not params.core_competency
