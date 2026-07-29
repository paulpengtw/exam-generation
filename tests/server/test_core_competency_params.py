"""Subject-specific handling of core_competency request parameters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from server.generate.models import GenerateParams
from server.generate.subjects import SUBJECTS


def test_social_studies_uses_requested_core_competencies() -> None:
    params = GenerateParams(
        subject="social_studies",
        core_competency=["社-J-A1", "社-J-C3"],
    )
    spec = SUBJECTS[params.subject]
    overrides = spec.coerce_overrides(params, SimpleNamespace())

    sampled = spec.do_sample_params(
        params,
        overrides,
        seed=1,
        subquestion_configs_decoded=None,
    )

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
