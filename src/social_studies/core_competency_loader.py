"""Load 108課綱 社會領域核心素養 from the standalone core_competencies.json."""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path

_DEFAULT_PATH = (
    Path(__file__).parent.parent.parent
    / "data" / "social_studies" / "curriculum" / "core_competencies.json"
)


def load_core_competencies(path: Path | None = None) -> dict:
    if path is None:
        env = os.environ.get("SOCIAL_STUDIES_CORE_COMPETENCIES_PATH")
        path = Path(env) if env else _DEFAULT_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_core_competency_enum(data: dict) -> type:
    """Build a str-enum of all 27 核心素養 values (社-E-*, 社-J-*, 社-U-*)."""
    values = [entry["value"] for entry in data["核心素養"]]
    members = {f"ITEM_{i}": v for i, v in enumerate(values)}
    return Enum("CoreCompetency", members, type=str)  # type: ignore[return-value]


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
