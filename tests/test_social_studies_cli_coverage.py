"""Argparse-level test for the SS CLI --coverage-mode flag (issue #112)."""

from __future__ import annotations

import pytest

from src.social_studies.cli import parse_args


def test_default_coverage_mode_is_balanced() -> None:
    ns = parse_args(["generate"])
    assert ns.coverage_mode == "balanced"


def test_can_set_random() -> None:
    ns = parse_args(["generate", "--coverage-mode", "random"])
    assert ns.coverage_mode == "random"


def test_rejects_unknown_value() -> None:
    with pytest.raises(SystemExit):
        parse_args(["generate", "--coverage-mode", "chaotic"])
