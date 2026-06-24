"""Subject-agnostic loader for 108課綱 核心素養 standalone JSON."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path


def load_core_competencies(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_core_competency_enum(
    data: dict,
    *,
    subject_prefix: str,
    enum_name: str | None = None,
) -> type[Enum]:
    """Build a str-enum of all 核心素養 values.

    `subject_prefix` is informative and defines the enum class name when
    `enum_name` is not given. The full set of `value` strings already encodes
    the subject, so we include every entry as-is.
    """
    values = [entry["value"] for entry in data["核心素養"]]
    members = {f"ITEM_{i}": v for i, v in enumerate(values)}
    name = enum_name or (f"CoreCompetency_{subject_prefix}" if subject_prefix else "CoreCompetency")
    return Enum(name, members, type=str)  # type: ignore[return-value]


def allowed_competencies(data: dict, learning_stage: str) -> list[str]:
    """Return value strings for the single stage mapped to learning_stage."""
    stage = data["學習階段_to_stage"].get(learning_stage)
    if stage is None:
        return []
    return [e["value"] for e in data["核心素養"] if e["stage"] == stage]


def competency_instructions(data: dict) -> dict[str, str]:
    """Return {value: instruction} for every 核心素養 entry."""
    return {e["value"]: e["instruction"] for e in data["核心素養"]}


def competency_meta(data: dict, value: str) -> dict:
    """Return the full row dict for a given value code."""
    for entry in data["核心素養"]:
        if entry["value"] == value:
            return entry
    return {}


def stage_code_for(data: dict, learning_stage: str) -> str:
    """Return the single stage code (E/J/U) for a 學習階段."""
    return data["學習階段_to_stage"].get(learning_stage, "J")
