"""Schema loaders must expose the 難度 category via build_instructions()."""

from __future__ import annotations


def test_math_build_instructions_exposes_難度():
    from src.schema_loader import build_instructions, load_schemas
    instr = build_instructions(load_schemas())
    assert "難度" in instr
    assert set(instr["難度"]) == {"easy", "medium", "hard"}
    assert all(instr["難度"][k].strip() for k in ("easy", "medium", "hard"))


def test_social_studies_build_instructions_exposes_難度():
    from src.social_studies.schema_loader import build_instructions, load_schemas
    instr = build_instructions(load_schemas())
    assert "難度" in instr
    assert set(instr["難度"]) == {"easy", "medium", "hard"}


def test_natural_sciences_build_instructions_exposes_難度():
    from src.natural_sciences.schema_loader import build_instructions, load_schemas
    instr = build_instructions(load_schemas())
    assert "難度" in instr
    assert set(instr["難度"]) == {"easy", "medium", "hard"}
