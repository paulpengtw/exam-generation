"""Argparse-level test for the SS CLI --coverage-mode flag (issue #112)."""

from __future__ import annotations

from pathlib import Path

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


def test_core_question_callback_defaults_to_on() -> None:
    args = parse_args(["generate"])

    assert args.core_question_callback is True


def test_no_core_question_callback_flag_reaches_generation(monkeypatch, capsys) -> None:
    import src.social_studies.cli as cli
    from src.config import Config

    captured: dict[str, bool] = {}

    def fake_generate_with_corrections(**kwargs):
        captured["core_question_callback"] = kwargs["core_question_callback"]
        return "dry-run output"

    monkeypatch.setattr(cli, "generate_with_corrections", fake_generate_with_corrections)
    monkeypatch.setattr(
        cli.Config,
        "from_env",
        classmethod(
            lambda cls, _env_file=None: Config(
                data_dir=Path("data"),
                creative_planning=False,
            )
        ),
    )

    cli.main(["generate", "--dry-run", "--no-core-question-callback"])

    assert captured["core_question_callback"] is False
    assert "dry-run output" in capsys.readouterr().out
