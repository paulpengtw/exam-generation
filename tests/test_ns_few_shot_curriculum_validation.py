"""Validate NS few-shot examples against the canonical 108課綱 curriculum.

For each of the 60 JSON files under
``data/natural_sciences/few_shot/{Simple-multiple-choice,Complex-multiple-choice,
Constructed-response}/``, every ``學習內容`` and ``學習表現`` 編碼 appearing in
a subquestion is checked against the canonical curriculum via
``src.natural_sciences.curriculum_codes.canonical_lc`` /
``canonical_lp``, which already normalises Unicode Ⅰ–Ⅴ ↔ ASCII roman-numeral
spellings (the routine from issue #92 is reused, not reimplemented).

Baseline of known-bad codes (as of 2026-07-28)
------------------------------------------------
32 references to 15 distinct codes that do not resolve.  The causes are:

LC codes that do not exist in the curriculum JSON:

  ``INa-IV-2``, ``INa-IV-3``, ``INa-IV-4``
    Prefix ``INa-IV-*`` has no entries in the curriculum.  The first valid
    INa code is at 第二學習階段 (grades 3-4).  These appear in
    ``Complex-multiple-choice/pisa_examples.json`` (a batch of 3 PISA
    adaptation examples).

  ``INc-IV-2``, ``INc-IV-4``
    ``INc-IV-*`` also has no 第四學習階段 entries.  Appear in
    ``Simple-multiple-choice/pisa_examples.json``.

  ``Lb-IV-4``
    ``Lb-IV`` exists but only has 3 entries (Lb-IV-1, Lb-IV-2, Lb-IV-3).
    Appears in ``Complex-multiple-choice/pisa_examples.json``.

  ``Ea-IV-4``, ``Ea-IV-5``
    ``Ea-IV`` exists but only has 3 entries.  ``Ea-IV-4`` is in
    ``Constructed-response/typhoon-database.json``; ``Ea-IV-5`` is in
    ``Constructed-response/weather-proverbs.json``.

  ``Bb-IV-6``
    ``Bb-IV`` exists but only has 5 entries.  Appears in
    ``Simple-multiple-choice/pisa_examples.json``.

LP codes that do not exist in the curriculum JSON:

  ``tr-IV-2``
    ``tr`` items only go up to ``tr-IV-1`` at the 第四學習階段 level.  This
    code appears 8 times across 5 files: both ``pisa_examples.json`` files,
    ``Complex-multiple-choice/self-heating-pack.json``,
    ``Constructed-response/truck-cornering.json``, and
    ``Constructed-response/weather-proverbs.json``.

  ``tm-IV-2``, ``tm-IV-3``
    ``tm`` only has 1 entry per stage.  Appear in
    ``Simple-multiple-choice/pisa_examples.json`` (tm-IV-2) and
    ``Complex-multiple-choice/pisa_examples.json`` (tm-IV-3).

  ``pe-IV-3``, ``pe-IV-4``, ``pe-IV-5``
    ``pe-IV`` only has 2 entries (pe-IV-1, pe-IV-2).  ``pe-IV-3`` is in
    ``Constructed-response/truck-cornering.json``; ``pe-IV-4`` is in
    ``Constructed-response/fasting-method.json``; ``pe-IV-5`` is in
    ``Constructed-response/weather-proverbs.json``.

These codes are NOT silently ignored.  The test asserts the exact set so
that no NEW unresolvable code can be introduced without a deliberate update
to the baseline here.  Fixing the data files is a separate human task.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.natural_sciences.curriculum_codes import canonical_lc, canonical_lp

_FEW_SHOT_DIR = Path(__file__).parent.parent / "data" / "natural_sciences" / "few_shot"

# ---------------------------------------------------------------------------
# Known-bad baselines (codes, not file paths).
# Update these sets only when fixing or deliberately adding data files.
# ---------------------------------------------------------------------------

_KNOWN_BAD_LC: frozenset[str] = frozenset(
    {
        "INa-IV-2",
        "INa-IV-3",
        "INa-IV-4",
        "INc-IV-2",
        "INc-IV-4",
        "Lb-IV-4",
        "Ea-IV-4",
        "Ea-IV-5",
        "Bb-IV-6",
    }
)

_KNOWN_BAD_LP: frozenset[str] = frozenset(
    {
        "tr-IV-2",
        "tm-IV-2",
        "tm-IV-3",
        "pe-IV-3",
        "pe-IV-4",
        "pe-IV-5",
    }
)


# ---------------------------------------------------------------------------
# Reusable helper
# ---------------------------------------------------------------------------


def collect_code_refs(
    few_shot_dir: Path,
) -> list[tuple[str, int, str, str]]:
    """Return (relative_path, subq_seq, code_type, code) for every LC/LP ref.

    Scans all ``*.json`` files recursively under *few_shot_dir*.  Each
    subquestion's ``學習內容`` and ``學習表現`` lists are walked; only entries
    that have a non-empty ``編碼`` string are included.  The returned list is
    suitable for filtering by ``code_type`` ("LC" or "LP") or by file path.
    """
    refs: list[tuple[str, int, str, str]] = []
    for json_file in sorted(few_shot_dir.rglob("*.json")):
        with open(json_file, encoding="utf-8") as fh:
            raw = json.load(fh)
        items = raw if isinstance(raw, list) else [raw]
        rel = str(json_file.relative_to(few_shot_dir.parent.parent))
        for item in items:
            q = item.get("question", item)
            for sq in q.get("subquestions", []):
                seq: int = sq.get("序號", 0)
                for ref in sq.get("學習內容") or []:
                    code = ref.get("編碼", "")
                    if code:
                        refs.append((rel, seq, "LC", code))
                for ref in sq.get("學習表現") or []:
                    code = ref.get("編碼", "")
                    if code:
                        refs.append((rel, seq, "LP", code))
    return refs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_collect_code_refs_finds_all_expected_files() -> None:
    """Helper sanity-check: 60 JSON files → at least 560 code refs."""
    refs = collect_code_refs(_FEW_SHOT_DIR)
    assert len(refs) >= 560, (
        f"Expected ≥560 code references across all few-shot files, got {len(refs)}"
    )


def test_no_new_unresolvable_lc_codes() -> None:
    """Every 學習內容 code must resolve, or be in the documented bad baseline.

    If this test fails with codes that are NOT in _KNOWN_BAD_LC, a new
    data file has introduced an unresolvable code — fix it before merging.

    If it fails with a message like "resolved codes still in baseline", a
    previously bad code was fixed in the curriculum JSON — remove it from
    _KNOWN_BAD_LC.
    """
    refs = collect_code_refs(_FEW_SHOT_DIR)
    bad_found: set[str] = set()
    for _path, _seq, code_type, code in refs:
        if code_type == "LC" and canonical_lc(code) is None:
            bad_found.add(code)

    new_bad = bad_found - _KNOWN_BAD_LC
    assert not new_bad, (
        f"Found {len(new_bad)} new unresolvable 學習內容 code(s) not in the baseline:\n"
        + "\n".join(f"  {c}" for c in sorted(new_bad))
        + "\nUpdate the few-shot data file or add to _KNOWN_BAD_LC with a comment."
    )

    resolved_from_baseline = _KNOWN_BAD_LC - bad_found
    assert not resolved_from_baseline, (
        f"These 學習內容 codes are in the known-bad baseline but now resolve "
        f"(curriculum was fixed?): {sorted(resolved_from_baseline)}\n"
        "Remove them from _KNOWN_BAD_LC so the baseline stays accurate."
    )


def test_no_new_unresolvable_lp_codes() -> None:
    """Every 學習表現 code must resolve, or be in the documented bad baseline.

    Same policy as test_no_new_unresolvable_lc_codes — see that test's
    docstring for the update procedure.
    """
    refs = collect_code_refs(_FEW_SHOT_DIR)
    bad_found: set[str] = set()
    for _path, _seq, code_type, code in refs:
        if code_type == "LP" and canonical_lp(code) is None:
            bad_found.add(code)

    new_bad = bad_found - _KNOWN_BAD_LP
    assert not new_bad, (
        f"Found {len(new_bad)} new unresolvable 學習表現 code(s) not in the baseline:\n"
        + "\n".join(f"  {c}" for c in sorted(new_bad))
        + "\nUpdate the few-shot data file or add to _KNOWN_BAD_LP with a comment."
    )

    resolved_from_baseline = _KNOWN_BAD_LP - bad_found
    assert not resolved_from_baseline, (
        f"These 學習表現 codes are in the known-bad baseline but now resolve "
        f"(curriculum was fixed?): {sorted(resolved_from_baseline)}\n"
        "Remove them from _KNOWN_BAD_LP so the baseline stays accurate."
    )


def test_total_bad_code_reference_count() -> None:
    """Confirm the total count of bad references (32) matches the documented baseline.

    This catches cases where a code already in the baseline appears in
    more files than expected (i.e. the bad code is spreading).
    """
    refs = collect_code_refs(_FEW_SHOT_DIR)
    all_known_bad = _KNOWN_BAD_LC | _KNOWN_BAD_LP
    bad_refs = [
        (path, seq, code_type, code)
        for path, seq, code_type, code in refs
        if code in all_known_bad
    ]
    assert len(bad_refs) == 32, (
        f"Expected exactly 32 bad-code references; found {len(bad_refs)}.\n"
        "If you added or removed a few-shot file, update this count."
    )


@pytest.mark.parametrize(
    "filename, expected_bad_lc, expected_bad_lp",
    [
        (
            "Complex-multiple-choice/pisa_examples.json",
            {"INa-IV-2", "INa-IV-3", "INa-IV-4", "Lb-IV-4"},
            {"tr-IV-2", "tm-IV-3"},
        ),
        (
            "Simple-multiple-choice/pisa_examples.json",
            {"Bb-IV-6", "INc-IV-2", "INc-IV-4"},
            {"tr-IV-2", "tm-IV-2"},
        ),
        (
            "Constructed-response/typhoon-database.json",
            {"Ea-IV-4"},
            set(),
        ),
        (
            "Constructed-response/weather-proverbs.json",
            {"Ea-IV-5"},
            {"tr-IV-2", "pe-IV-5"},
        ),
        (
            "Complex-multiple-choice/self-heating-pack.json",
            set(),
            {"tr-IV-2"},
        ),
        (
            "Constructed-response/truck-cornering.json",
            set(),
            {"tr-IV-2", "pe-IV-3"},
        ),
        (
            "Constructed-response/fasting-method.json",
            set(),
            {"pe-IV-4"},
        ),
    ],
)
def test_per_file_bad_codes(
    filename: str,
    expected_bad_lc: set[str],
    expected_bad_lp: set[str],
) -> None:
    """Per-file audit: each offending file exposes exactly its documented bad codes."""
    json_path = _FEW_SHOT_DIR.parent / "few_shot" / filename
    with open(json_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    items = raw if isinstance(raw, list) else [raw]

    found_bad_lc: set[str] = set()
    found_bad_lp: set[str] = set()
    for item in items:
        q = item.get("question", item)
        for sq in q.get("subquestions", []):
            for ref in sq.get("學習內容") or []:
                code = ref.get("編碼", "")
                if code and canonical_lc(code) is None:
                    found_bad_lc.add(code)
            for ref in sq.get("學習表現") or []:
                code = ref.get("編碼", "")
                if code and canonical_lp(code) is None:
                    found_bad_lp.add(code)

    assert found_bad_lc == expected_bad_lc, (
        f"{filename}: unexpected bad LC codes.\n"
        f"  expected: {sorted(expected_bad_lc)}\n"
        f"  found:    {sorted(found_bad_lc)}"
    )
    assert found_bad_lp == expected_bad_lp, (
        f"{filename}: unexpected bad LP codes.\n"
        f"  expected: {sorted(expected_bad_lp)}\n"
        f"  found:    {sorted(found_bad_lp)}"
    )
