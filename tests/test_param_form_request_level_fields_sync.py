"""Cross-layer contract tests for per-question request-level fields."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest
from pydantic import ValidationError

from server.generate.models import GenerateParams, REQUEST_LEVEL_FIELDS

ROOT = Path(__file__).resolve().parent.parent
PARAM_FORM_PATH = ROOT / "web" / "src" / "components" / "ParamForm.tsx"
REQUEST_LEVEL_FIELDS_LITERAL = re.compile(
    r"""
    const\s+requestLevelFields\s*=\s*new\s+Set\(\s*\[
    (?P<items>(?:\s*["'][A-Za-z_][A-Za-z0-9_]*["']\s*,?)*)\s*
    \]\s*\)
    """,
    re.VERBOSE,
)


def test_param_form_request_level_fields_match_server_contract() -> None:
    source = PARAM_FORM_PATH.read_text(encoding="utf-8")
    match = REQUEST_LEVEL_FIELDS_LITERAL.search(source)

    assert match is not None, (
        "ParamForm.tsx must define "
        "`const requestLevelFields = new Set([...])` so its per-question "
        "strip-list can be checked against "
        "server.generate.models.REQUEST_LEVEL_FIELDS"
    )

    frontend_fields = set(re.findall(r"""["']([^"']+)["']""", match.group("items")))
    assert frontend_fields == REQUEST_LEVEL_FIELDS, (
        "ParamForm.tsx requestLevelFields is out of sync with "
        "server.generate.models.REQUEST_LEVEL_FIELDS: "
        f"frontend={sorted(frontend_fields)}, "
        f"server={sorted(REQUEST_LEVEL_FIELDS)}"
    )


@pytest.mark.parametrize("request_level_field", sorted(REQUEST_LEVEL_FIELDS))
def test_generate_params_rejects_request_level_field_per_question(
    request_level_field: str,
) -> None:
    per_question_params = json.dumps([{request_level_field: None}])

    with pytest.raises(ValidationError, match="unknown parameter"):
        GenerateParams(count=1, per_question_params=per_question_params)
