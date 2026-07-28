"""Drift guard: contract.ts must match what generate_ts_contract.py emits.

If this test fails, the checked-in file is stale. Regenerate with:

    python scripts/generate_ts_contract.py
"""

from __future__ import annotations

from pathlib import Path

from scripts.generate_ts_contract import generate_contract

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "web" / "src" / "api" / "generated" / "contract.ts"
REGEN_CMD = "python scripts/generate_ts_contract.py"


def test_ts_contract_matches_generator() -> None:
    """The checked-in contract.ts must be byte-identical to generate_contract() output."""
    expected = generate_contract()
    actual = CONTRACT_PATH.read_text(encoding="utf-8")

    assert expected == actual, (
        f"web/src/api/generated/contract.ts is out of date with the Pydantic models.\n"
        f"Regenerate with:\n\n    {REGEN_CMD}\n"
    )
