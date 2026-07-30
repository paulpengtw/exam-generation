"""Tests for GenerateParams effort_plan / effort_execute fields (issue #254)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.generate.models import GenerateParams, PlanCoreQuestionsRequest


# ---------------------------------------------------------------------------
# 1. GenerateParams: optional fields, defaults None
# ---------------------------------------------------------------------------


def test_generate_params_effort_fields_default_none() -> None:
    params = GenerateParams()
    assert params.effort_plan is None
    assert params.effort_execute is None


def test_generate_params_accepts_valid_effort_plan() -> None:
    for level in ("low", "medium", "high", "xhigh", "max"):
        params = GenerateParams(effort_plan=level)
        assert params.effort_plan == level


def test_generate_params_accepts_valid_effort_execute() -> None:
    for level in ("low", "medium", "high", "xhigh", "max"):
        params = GenerateParams(effort_execute=level)
        assert params.effort_execute == level


# ---------------------------------------------------------------------------
# 2. GenerateParams: invalid level → ValidationError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_level", ["ultra", "none", "MEDIUM", "1", ""])
def test_generate_params_rejects_invalid_effort_plan(bad_level: str) -> None:
    with pytest.raises(ValidationError, match="effort_plan"):
        GenerateParams(effort_plan=bad_level)


@pytest.mark.parametrize("bad_level", ["ultra", "none", "HIGH", "2", ""])
def test_generate_params_rejects_invalid_effort_execute(bad_level: str) -> None:
    with pytest.raises(ValidationError, match="effort_execute"):
        GenerateParams(effort_execute=bad_level)


# ---------------------------------------------------------------------------
# 3. PlanCoreQuestionsRequest: optional effort_plan field
# ---------------------------------------------------------------------------


def test_plan_core_questions_request_effort_plan_default_none() -> None:
    req = PlanCoreQuestionsRequest(topic="民主政治")
    assert req.effort_plan is None


def test_plan_core_questions_request_accepts_valid_effort_plan() -> None:
    req = PlanCoreQuestionsRequest(topic="民主政治", effort_plan="high")
    assert req.effort_plan == "high"


def test_plan_core_questions_request_rejects_invalid_effort_plan() -> None:
    with pytest.raises(ValidationError, match="effort_plan"):
        PlanCoreQuestionsRequest(topic="民主政治", effort_plan="bogus")
