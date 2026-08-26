"""Keep the old generation-time fills visibly transitional until #608."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTE = "do not add a new drawable field here — add it to the resolver"


def test_all_generation_time_fill_sites_carry_the_resolver_note() -> None:
    paths = [
        ROOT / "server/generate/service.py",
        ROOT / "src/cli.py",
        ROOT / "src/social_studies/cli.py",
        ROOT / "src/natural_sciences/cli.py",
    ]

    assert all(NOTE in path.read_text(encoding="utf-8") for path in paths)
    assert sum(NOTE in path.read_text(encoding="utf-8") for path in paths) == 4
