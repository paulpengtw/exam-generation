"""Drift guard: contract.ts must match what generate_ts_contract.py emits.

If this test fails, the checked-in file is stale. Regenerate with:

    python scripts/generate_ts_contract.py
"""

from __future__ import annotations

import inspect
from pathlib import Path

from scripts.generate_ts_contract import generate_contract
import pytest
pytest.importorskip("fastapi", reason="requires [web] extras: uv sync --extra web")

from server.generate.models import SERVER_ONLY_GENERATE_FIELDS, GenerateParams
from server.generate.routes import generate_endpoint

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "web" / "src" / "api" / "generated" / "contract.ts"
USE_GENERATE_PATH = ROOT / "web" / "src" / "hooks" / "useGenerate.ts"
REGEN_CMD = "python scripts/generate_ts_contract.py"


def test_ts_contract_matches_generator() -> None:
    """The checked-in contract.ts must be byte-identical to generate_contract() output."""
    expected = generate_contract()
    actual = CONTRACT_PATH.read_text(encoding="utf-8")

    assert expected == actual, (
        f"web/src/api/generated/contract.ts is out of date with the Pydantic models.\n"
        f"Regenerate with:\n\n    {REGEN_CMD}\n"
    )


def test_every_generated_request_field_is_reachable_on_generate_route() -> None:
    route_parameters = set(inspect.signature(generate_endpoint).parameters)

    assert set(GenerateParams.model_fields) <= route_parameters

    # Deliberately controlled only by the server; the web client does not expose
    # or forward this retry-policy setting.
    web_client_exclusions = {"max_retries", *SERVER_ONLY_GENERATE_FIELDS}
    web_client_fields = set(GenerateParams.model_fields) - web_client_exclusions
    use_generate_source = USE_GENERATE_PATH.read_text(encoding="utf-8")

    missing_fields = {
        field
        for field in web_client_fields
        if f'qs.append("{field}",' not in use_generate_source
    }
    assert not missing_fields, (
        "Generated request fields missing from the live web query builder: "
        f"{sorted(missing_fields)}"
    )
