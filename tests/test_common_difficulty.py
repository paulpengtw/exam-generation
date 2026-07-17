"""Tests for the shared Difficulty enum + resolver."""

from __future__ import annotations

import pytest

from src.common.difficulty import DEFAULT_DIFFICULTY, Difficulty, resolve_difficulty


def test_difficulty_members_exact():
    assert [d.value for d in Difficulty] == ["easy", "medium", "hard"]


def test_difficulty_is_str_enum():
    # str-mixin so JSON serialization and dict lookups behave like plain strings
    assert Difficulty.easy == "easy"
    assert Difficulty.medium == "medium"
    assert Difficulty.hard == "hard"


def test_default_is_medium():
    assert DEFAULT_DIFFICULTY is Difficulty.medium


def test_resolve_none_returns_medium():
    assert resolve_difficulty(None) is Difficulty.medium


def test_resolve_empty_string_returns_medium():
    assert resolve_difficulty("") is Difficulty.medium


def test_resolve_string_returns_enum():
    assert resolve_difficulty("easy") is Difficulty.easy
    assert resolve_difficulty("medium") is Difficulty.medium
    assert resolve_difficulty("hard") is Difficulty.hard


def test_resolve_enum_passthrough():
    assert resolve_difficulty(Difficulty.hard) is Difficulty.hard


def test_resolve_unknown_string_raises():
    with pytest.raises(ValueError):
        resolve_difficulty("insane")
