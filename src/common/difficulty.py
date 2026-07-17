"""Shared difficulty enum used by all three subject pipelines (issue #116).

Difficulty is a pure passthrough — samplers never randomize it. Default is
medium. The str-mixin lets values round-trip through JSON / query strings /
Pydantic Literals interchangeably.
"""

from __future__ import annotations

from enum import Enum


class Difficulty(str, Enum):
    """easy = 直接擷取 / 一步; medium = 中等; hard = 多步整合、批判與評估。"""

    easy = "easy"
    medium = "medium"
    hard = "hard"


DEFAULT_DIFFICULTY: Difficulty = Difficulty.medium


def resolve_difficulty(value: "str | Difficulty | None") -> Difficulty:
    """Map None / empty / str / Difficulty to a Difficulty enum member.

    None or empty string → DEFAULT_DIFFICULTY (medium). A Difficulty is
    returned unchanged. An unknown string raises ValueError.
    """
    if value is None or value == "":
        return DEFAULT_DIFFICULTY
    if isinstance(value, Difficulty):
        return value
    return Difficulty(value)
