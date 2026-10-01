"""Issue #932 — sidecar key contract drift guard.

Asserts that CONTENT_SIGNATURE_EXCLUDED_KEYS in
src/common/generation_events.py matches contracts/content-sidecar-keys.json
exactly, so a rename or extension that touches only one side fails loudly.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.common.generation_events import CONTENT_SIGNATURE_EXCLUDED_KEYS

CONTRACT_PATH = Path(__file__).parent.parent / "contracts" / "content-sidecar-keys.json"


def test_contract_file_exists() -> None:
    assert CONTRACT_PATH.is_file(), (
        f"Contract file not found: {CONTRACT_PATH}. "
        "It must exist and list the sidecar keys shared by the Python snapshot "
        "ledger and the TypeScript evidence reducer."
    )


def test_python_constant_matches_contract() -> None:
    """CONTENT_SIGNATURE_EXCLUDED_KEYS must equal contracts/content-sidecar-keys.json."""
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract_keys = set(contract["keys"])

    assert CONTENT_SIGNATURE_EXCLUDED_KEYS == contract_keys, (
        "CONTENT_SIGNATURE_EXCLUDED_KEYS in src/common/generation_events.py "
        "does not match contracts/content-sidecar-keys.json.\n"
        f"  Python only: {CONTENT_SIGNATURE_EXCLUDED_KEYS - contract_keys}\n"
        f"  Contract only: {contract_keys - CONTENT_SIGNATURE_EXCLUDED_KEYS}\n"
        "Update both files together and keep contracts/content-sidecar-keys.json "
        "as the single source of truth."
    )
