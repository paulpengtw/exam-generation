"""QuestionMetadata carries coverage_mode_used (issue #112)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.social_studies.schemas import QuestionMetadata


def test_default_omits_coverage_mode_used() -> None:
    m = QuestionMetadata(grade=8, model="claude-sonnet-4-6")
    assert m.coverage_mode_used is None


def test_accepts_balanced_and_random() -> None:
    assert QuestionMetadata(
        grade=8, model="m", coverage_mode_used="balanced"
    ).coverage_mode_used == "balanced"
    assert QuestionMetadata(
        grade=8, model="m", coverage_mode_used="random"
    ).coverage_mode_used == "random"


def test_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        QuestionMetadata(grade=8, model="m", coverage_mode_used="round_robin")
