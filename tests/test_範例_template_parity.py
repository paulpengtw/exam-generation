"""Guard: 範例_ reference templates must mirror the live-era CSV shape.

Two seams:
- data/social_studies/few_shot/範例_few_shot_examples.csv  — header must equal live header
- data/social_studies/curriculum/範例_schema_parameters.csv — 類別 set must equal live 類別 set

The few_shot guard reads only the header row (not data rows), so it stays green
after issue #542 reduces the live file to header-only.
The schema_parameters guard reads the set of 類別 values, which is stable regardless
of which representative values are present.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_範例_few_shot_header_matches_live() -> None:
    """範例_ few_shot template header must be byte-identical to the live CSV header."""
    live_path = ROOT / "data/social_studies/few_shot/few_shot_examples.csv"
    template_path = ROOT / "data/social_studies/few_shot/範例_few_shot_examples.csv"

    with live_path.open(encoding="utf-8-sig", newline="") as fh:
        live_header = next(csv.reader(fh))

    with template_path.open(encoding="utf-8-sig", newline="") as fh:
        template_header = next(csv.reader(fh))

    assert template_header == live_header, (
        f"範例_few_shot_examples.csv header does not match live few_shot_examples.csv header.\n"
        f"Live:     {live_header}\n"
        f"Template: {template_header}"
    )


def test_範例_schema_params_categories_match_live() -> None:
    """範例_ schema template 類別 set must equal the live schema_parameters.csv 類別 set."""
    live_path = ROOT / "data/social_studies/curriculum/schema_parameters.csv"
    template_path = ROOT / "data/social_studies/curriculum/範例_schema_parameters.csv"

    with live_path.open(encoding="utf-8-sig", newline="") as fh:
        live_categories = {row["類別"] for row in csv.DictReader(fh)}

    with template_path.open(encoding="utf-8-sig", newline="") as fh:
        template_categories = {row["類別"] for row in csv.DictReader(fh)}

    assert template_categories == live_categories, (
        f"範例_schema_parameters.csv 類別 set does not match live schema_parameters.csv.\n"
        f"Live:     {sorted(live_categories)}\n"
        f"Template: {sorted(template_categories)}\n"
        f"Missing:  {sorted(live_categories - template_categories)}\n"
        f"Extra:    {sorted(template_categories - live_categories)}"
    )
