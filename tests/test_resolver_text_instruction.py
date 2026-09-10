"""Resolver contract for per-row text_instruction overrides (issue #637).

Acceptance criteria (slice A):
- A non-blank per_question_params[i].text_instruction survives resolution for
  that row only and does NOT appear in other rows.
- A blank (empty string, whitespace-only) or absent row value does NOT create
  an override entry in the resolved row.
"""

from __future__ import annotations

import json

import pytest

from src.common.resolver import resolve


def _resolve_two_row_payload(
    row0: dict,
    row1: dict,
    *,
    request_text_instruction: str = "request-level",
) -> list[dict]:
    """Resolve a count=2 social_studies payload and return the resolved per-question rows."""
    result = resolve(
        {
            "subject": "social_studies",
            "count": 2,
            "seed": 42,
            "text_instruction": request_text_instruction,
            "per_question_params": json.dumps([row0, row1]),
        }
    )
    rows = result.payload["per_question_params"]
    assert isinstance(rows, list) and len(rows) == 2
    return rows


# ── Slice A-1: non-blank row value survives ────────────────────────────────

def test_non_blank_row_text_instruction_survives_in_resolved_row() -> None:
    """A non-blank per-row text_instruction is preserved in that row's resolved output."""
    rows = _resolve_two_row_payload(
        {},
        {"text_instruction": "override-for-second"},
    )
    # Row 0 has no override — must not carry text_instruction
    assert rows[0].get("text_instruction") is None or rows[0].get("text_instruction") == ""
    # Row 1 has an override — must survive
    assert rows[1]["text_instruction"] == "override-for-second"


def test_non_blank_row_text_instruction_does_not_leak_to_sibling() -> None:
    """An override on row 1 must not appear in row 0's resolved output."""
    rows = _resolve_two_row_payload(
        {},
        {"text_instruction": "only-for-second"},
    )
    assert rows[0].get("text_instruction") != "only-for-second"


def test_both_rows_can_carry_independent_overrides() -> None:
    """Each row may carry its own distinct override independently."""
    rows = _resolve_two_row_payload(
        {"text_instruction": "first-override"},
        {"text_instruction": "second-override"},
    )
    assert rows[0]["text_instruction"] == "first-override"
    assert rows[1]["text_instruction"] == "second-override"


# ── Slice A-2: blank/absent row value does NOT create an override ──────────

@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_row_text_instruction_does_not_create_override(blank: str | None) -> None:
    """A blank or absent row-level text_instruction does not appear in resolved_row."""
    row: dict = {} if blank is None else {"text_instruction": blank}
    rows = _resolve_two_row_payload(row, {})
    # The resolved row must not carry a non-empty text_instruction override
    val = rows[0].get("text_instruction")
    assert val is None or (isinstance(val, str) and not val.strip()), (
        f"Expected blank/absent text_instruction in resolved row 0, got {val!r}"
    )


def test_request_level_text_instruction_is_not_duplicated_into_resolved_rows() -> None:
    """The request-level text_instruction must not appear in any resolved row
    when the rows themselves did not supply an override.
    This confirms the resolver does not propagate the base value into resolved_row.
    """
    rows = _resolve_two_row_payload(
        {},
        {},
        request_text_instruction="request-level",
    )
    # Neither row supplied a text_instruction override, so neither resolved row
    # should carry one (the workers fall back to params.text_instruction directly).
    for i, row in enumerate(rows):
        val = row.get("text_instruction")
        assert val is None or (isinstance(val, str) and not val.strip()), (
            f"Request-level text_instruction leaked into resolved row {i}: {val!r}"
        )
