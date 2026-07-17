"""Schema tests for CreativeBrief + SampledParams.creative_brief."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.social_studies.sampler import sample_params
from src.social_studies.schemas import CreativeBrief, SampledParams


def test_creative_brief_accepts_valid_payload() -> None:
    brief = CreativeBrief(
        selected_context="個人",
        題材_angle="以居家防疫日記串起個人與公共衛生決策",
        framing_hooks=["病患日記", "決策會議紀錄"],
    )
    assert brief.selected_context == "個人"
    assert brief.題材_angle.startswith("以居家防疫日記")
    assert brief.framing_hooks == ["病患日記", "決策會議紀錄"]


def test_creative_brief_requires_selected_context_and_angle() -> None:
    with pytest.raises(ValidationError):
        CreativeBrief(題材_angle="only angle", framing_hooks=[])
    with pytest.raises(ValidationError):
        CreativeBrief(selected_context="個人", framing_hooks=[])


def test_creative_brief_framing_hooks_defaults_to_empty_list() -> None:
    brief = CreativeBrief(selected_context="公共", 題材_angle="市議會辯論觀點")
    assert brief.framing_hooks == []


def test_sampled_params_creative_brief_defaults_to_none() -> None:
    params = sample_params(seed=1)
    assert params.creative_brief is None


def test_sampled_params_can_attach_creative_brief() -> None:
    params = sample_params(seed=1)
    brief = CreativeBrief(selected_context="個人", 題材_angle="角度說明")
    updated: SampledParams = params.model_copy(update={"creative_brief": brief})
    assert updated.creative_brief == brief
    assert params.creative_brief is None  # original untouched
