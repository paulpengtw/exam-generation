"""Static guards for values that must be complete before generation."""

from __future__ import annotations

from pathlib import Path


def test_model_decided_subquestion_count_prompt_is_removed() -> None:
    prompt_sources = (
        Path("src/context_builder.py"),
        Path("src/social_studies/context_builder.py"),
        Path("src/natural_sciences/context_builder.py"),
    )
    retired = "3–7（由命題教師自行決定）"
    assert all(retired not in path.read_text(encoding="utf-8") for path in prompt_sources)


def test_social_sampler_has_no_legacy_global_or_phantom_slot_mode() -> None:
    source = Path("src/social_studies/sampler.py").read_text(encoding="utf-8").lower()
    assert "legacy" not in source
    assert "global" not in source
    assert "phantom" not in source
    assert "_max_subquestion_slots" not in source
