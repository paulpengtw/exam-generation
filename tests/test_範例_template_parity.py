"""Guard: 範例_ reference templates must mirror the live-era CSV shape.

Two seams:
- data/social_studies/few_shot/範例_few_shot_examples.csv  — header must equal live header
- data/social_studies/curriculum/範例_schema_parameters.csv — 類別 set must equal live 類別 set

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


def test_範例_few_shot_body_iccs_coverage() -> None:
    """AC1 row-level: exactly 3 demo groups; 認知歷程 covers all 4 ICCS buckets; 內容領域 from schema.

    Guards that a template with a correct header but fabricated row values (wrong group
    count, made-up 認知歷程, or 內容領域 absent from the live schema) cannot slip past
    the gate undetected.

    Expected values come from the live schema_parameters.csv (authoritative ICCS source),
    not recomputed from the template under test.
    """
    template_path = ROOT / "data/social_studies/few_shot/範例_few_shot_examples.csv"
    schema_path = ROOT / "data/social_studies/curriculum/schema_parameters.csv"

    # Load live authoritative values from schema_parameters.csv (independent source).
    with schema_path.open(encoding="utf-8-sig", newline="") as fh:
        schema_rows = list(csv.DictReader(fh))
    live_認知歷程 = {r["value"] for r in schema_rows if r["類別"] == "認知歷程"}
    live_內容領域 = {r["value"] for r in schema_rows if r["類別"] == "內容領域"}

    # Read every data row from the template (body, not just the header).
    with template_path.open(encoding="utf-8-sig", newline="") as fh:
        template_rows = list(csv.DictReader(fh))

    assert template_rows, "範例_few_shot_examples.csv has no data rows — template body is empty."

    template_groups = {row["範例編號"] for row in template_rows}
    template_認知歷程 = {row["認知歷程"] for row in template_rows}
    template_內容領域 = {row["內容領域"] for row in template_rows}

    # AC1 sub-criterion 1: exactly three demo 題組 groups.
    expected_groups = {"demo01", "demo02", "demo03"}
    assert template_groups == expected_groups, (
        f"範例_few_shot_examples.csv must have exactly 3 demo groups {sorted(expected_groups)}.\n"
        f"Found: {sorted(template_groups)}"
    )

    # AC1 sub-criterion 2: 認知歷程 values cover all four launched ICCS buckets.
    assert template_認知歷程 == live_認知歷程, (
        f"範例_few_shot_examples.csv 認知歷程 values must equal the four ICCS buckets "
        f"from schema_parameters.csv.\n"
        f"Schema (live): {sorted(live_認知歷程)}\n"
        f"Template:      {sorted(template_認知歷程)}\n"
        f"Missing:       {sorted(live_認知歷程 - template_認知歷程)}\n"
        f"Extra:         {sorted(template_認知歷程 - live_認知歷程)}"
    )

    # AC1 sub-criterion 3: every 內容領域 value in the template is drawn from schema_parameters.csv.
    rogue_domains = template_內容領域 - live_內容領域
    assert not rogue_domains, (
        f"範例_few_shot_examples.csv contains 內容領域 values not present in schema_parameters.csv.\n"
        f"Rogue values: {sorted(rogue_domains)}\n"
        f"Allowed (live schema): {sorted(live_內容領域)}"
    )
