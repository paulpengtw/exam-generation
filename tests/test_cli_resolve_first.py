from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.resolver import resolve
from src.config import Config


def test_math_generate_prints_resolved_payload_before_generation_and_pins_params(
    monkeypatch, capsys, tmp_path
) -> None:
    import src.cli as cli

    captured: dict[str, object] = {}

    def fake_generate_with_corrections(**kwargs):
        captured["params"] = kwargs["params"]
        return "generated output"

    monkeypatch.setattr(cli, "generate_with_corrections", fake_generate_with_corrections)
    monkeypatch.setattr(
        cli.Config,
        "from_env",
        classmethod(
            lambda cls, _env_file=None: Config(
                api_key="test",
                data_dir=Path("data"),
                output_dir=tmp_path,
            )
        ),
    )

    cli.main(["generate", "--dry-run", "--seed", "42", "--grade", "8"])

    output_lines = capsys.readouterr().out.splitlines()
    payload_lines = [line for line in output_lines if line.startswith("{") and '"payload"' in line]
    assert payload_lines, "generate must print its resolved payload before generation"

    expected = resolve({"subject": "math", "seed": 42, "grade": 8})
    assert json.loads(payload_lines[0]) == {
        "payload": expected.payload,
        "drawn": expected.drawn,
    }

    params = captured["params"]
    assert params.grade == 8
    assert params.seed == 42
    assert [item.value for item in params.情境] == expected.payload["context"]
    assert params.題型.value == expected.payload["q_type"][0]
    assert params.style.value == expected.payload["style"][0]
    assert [item.value for item in params.數學思考] == expected.payload["math_thinking"]
    assert params.題目內容類型 == expected.payload["content_type"]


def test_math_resolve_prints_payload_without_constructing_llm_client(
    monkeypatch, capsys
) -> None:
    import src.cli as cli

    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("resolve must not construct an LLM client")

    monkeypatch.setattr(cli, "LLMClient", forbidden_client)

    cli.main(["resolve", "--seed", "42", "--grade", "8"])

    result = json.loads(capsys.readouterr().out)
    assert result["payload"]["subject"] == "math"
    assert result["payload"]["seed"] == 42
    assert result["payload"]["grade"] == 8
    assert result["drawn"]


def test_social_studies_generate_prints_resolved_payload_and_pins_params(
    monkeypatch, capsys, tmp_path
) -> None:
    import src.social_studies.cli as cli

    captured: dict[str, object] = {}

    def fake_generate_with_corrections(**kwargs):
        captured["params"] = kwargs["params"]
        return "generated output"

    monkeypatch.setattr(cli, "generate_with_corrections", fake_generate_with_corrections)
    monkeypatch.setattr(
        cli.Config,
        "from_env",
        classmethod(
            lambda cls, _env_file=None: Config(
                api_key="test",
                data_dir=Path("data"),
                output_dir=tmp_path,
                creative_planning=False,
            )
        ),
    )

    cli.main(
        [
            "generate",
            "--dry-run",
            "--seed",
            "42",
            "--grade",
            "8",
            "--subject",
            "歷史",
        ]
    )

    output_lines = capsys.readouterr().out.splitlines()
    payload_lines = [line for line in output_lines if line.startswith("{") and '"payload"' in line]
    assert payload_lines, "generate must print its resolved payload before generation"

    expected = resolve(
        {"subject": "social_studies", "seed": 42, "grade": 8, "subject_filter": ["歷史"]}
    )
    assert json.loads(payload_lines[0]) == {
        "payload": expected.payload,
        "drawn": expected.drawn,
    }

    params = captured["params"]
    assert params.grade == 8
    assert params.seed == 42
    assert params.科目.value == "歷史"
    assert params.內容領域.value == expected.payload["content_domain"]


def test_natural_sciences_generate_prints_resolved_payload_and_pins_params(
    monkeypatch, capsys, tmp_path
) -> None:
    import src.natural_sciences.cli as cli

    captured: dict[str, object] = {}

    def fake_generate_with_corrections(**kwargs):
        captured["params"] = kwargs["params"]
        return "generated output"

    monkeypatch.setattr(cli, "generate_with_corrections", fake_generate_with_corrections)
    monkeypatch.setattr(
        cli.Config,
        "from_env",
        classmethod(
            lambda cls, _env_file=None: Config(
                api_key="test",
                data_dir=Path("data"),
                output_dir=tmp_path,
            )
        ),
    )

    cli.main(
        [
            "generate",
            "--dry-run",
            "--seed",
            "42",
            "--grade",
            "8",
            "--context",
            "Personal",
            "--sub-context",
            "Maintenance of health",
        ]
    )

    output_lines = capsys.readouterr().out.splitlines()
    payload_lines = [line for line in output_lines if line.startswith("{") and '"payload"' in line]
    assert payload_lines, "generate must print its resolved payload before generation"

    expected = resolve(
        {
            "subject": "natural_sciences",
            "seed": 42,
            "grade": 8,
            "context": ["Personal"],
            "sub_context": "Maintenance of health",
        }
    )
    assert json.loads(payload_lines[0]) == {
        "payload": expected.payload,
        "drawn": expected.drawn,
    }

    params = captured["params"]
    assert params.grade == 8
    assert params.seed == 42
    assert [item.value for item in params.情境] == ["Personal"]
    assert params.情境子類別.value == "Maintenance of health"


@pytest.mark.parametrize(
    ("module_name", "subject"),
    [
        ("src.cli", "math"),
        ("src.social_studies.cli", "social_studies"),
        ("src.natural_sciences.cli", "natural_sciences"),
    ],
)
def test_resolve_subcommand_is_client_free_and_replays_seed(
    monkeypatch, capsys, module_name, subject
) -> None:
    from importlib import import_module

    cli = import_module(module_name)

    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("resolve must not construct an LLM client")

    monkeypatch.setattr(cli, "LLMClient", forbidden_client)

    argv = ["resolve", "--seed", "42"]
    cli.main(argv)
    first = json.loads(capsys.readouterr().out)
    cli.main(argv)
    second = json.loads(capsys.readouterr().out)

    assert first == second
    assert first["payload"]["subject"] == subject
    assert first["payload"]["seed"] == 42
    assert first["drawn"]


def test_natural_sciences_resolve_reports_incompatible_pins_on_stderr(
    capsys,
) -> None:
    import src.natural_sciences.cli as cli

    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "resolve",
                "--context",
                "Personal",
                "--sub-context",
                "Control of disease",
            ]
        )

    assert exc_info.value.code == 2
    error = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert error["errors"][0]["field"] == "sub_context"
    assert error["errors"][0]["code"] == "incompatible_parent"


def test_math_resolve_count_uses_one_seeded_payload_per_question(capsys) -> None:
    import src.cli as cli

    cli.main(["resolve", "--seed", "42", "--count", "2", "--grade", "8"])

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [record["payload"]["seed"] for record in records] == [42, 43]
    assert all(record["payload"]["grade"] == 8 for record in records)


@pytest.mark.parametrize(
    ("module_name", "argv", "pinned_values"),
    [
        (
            "src.cli",
            [
                "resolve",
                "--seed",
                "42",
                "--grade",
                "8",
                "--style",
                "text_only",
                "--context",
                "個人",
                "--q-type",
                "選擇題",
                "--subject-filter",
                "代數",
                "--core-competency",
                "數-J-A2",
                "--learning-content",
                "A-7-1",
                "--learning-performance",
                "a-IV-2",
                "--content-type",
                "純文字",
                "--difficulty",
                "hard",
            ],
            {
                "grade": 8,
                "style": ["text_only"],
                "context": ["個人"],
                "q_type": ["選擇題"],
                "subject_filter": "代數",
                "core_competency": ["數-J-A2"],
                "learning_content": ["A-7-1"],
                "learning_performance": ["a-IV-2"],
                "content_type": "純文字",
                "difficulty": "hard",
            },
        ),
        (
            "src.social_studies.cli",
            [
                "resolve",
                "--seed",
                "42",
                "--grade",
                "8",
                "--context",
                "個人",
                "--q-type",
                "選擇題",
                "--subject",
                "歷史",
                "--core-competency",
                "社-J-A2",
                "--content-type",
                "純文字",
                "--difficulty",
                "hard",
            ],
            {
                "grade": 8,
                "context": ["個人"],
                "q_type": ["選擇題"],
                "subject_filter": ["歷史"],
                "core_competency": ["社-J-A2"],
                "content_type": "純文字",
                "difficulty": "hard",
            },
        ),
        (
            "src.natural_sciences.cli",
            [
                "resolve",
                "--seed",
                "42",
                "--grade",
                "8",
                "--context",
                "Personal",
                "--sub-context",
                "Maintenance of health",
                "--q-type",
                "Simple multiple-choice",
                "--science-competency",
                "能力一：以科學的角度解釋現象",
                "--content-type",
                "純文字",
                "--reporting-scale",
                "2",
            ],
            {
                "grade": 8,
                "context": ["Personal"],
                "sub_context": "Maintenance of health",
                "q_type": ["Simple multiple-choice"],
                "science_competency": ["能力一：以科學的角度解釋現象"],
                "content_type": "純文字",
                "reporting_scale": "2",
            },
        ),
    ],
)
def test_resolve_subcommand_preserves_each_cli_pin(
    capsys, module_name, argv, pinned_values
) -> None:
    from importlib import import_module

    cli = import_module(module_name)

    cli.main(argv)

    record = json.loads(capsys.readouterr().out)
    for field, value in pinned_values.items():
        assert record["payload"][field] == value


@pytest.mark.parametrize(
    ("module_name", "extra_args"),
    [
        ("src.cli", []),
        ("src.social_studies.cli", ["--subject", "歷史"]),
        (
            "src.natural_sciences.cli",
            ["--context", "Personal", "--sub-context", "Maintenance of health"],
        ),
    ],
)
def test_generate_resolves_before_generation_and_replays_seeded_payload(
    monkeypatch, capsys, tmp_path, module_name, extra_args
) -> None:
    from importlib import import_module

    cli = import_module(module_name)
    events: list[str] = []

    real_resolve_and_print = cli.resolve_and_print

    def spy_resolve_and_print(payload, **kwargs):
        events.append("resolve-start")
        result = real_resolve_and_print(payload, **kwargs)
        events.append("resolve-finished")
        return result

    def fake_generate_with_corrections(**_kwargs):
        assert events[-1] == "resolve-finished"
        events.append("generate")
        return "generated output"

    monkeypatch.setattr(cli, "resolve_and_print", spy_resolve_and_print)
    monkeypatch.setattr(cli, "generate_with_corrections", fake_generate_with_corrections)
    config_kwargs = {
        "api_key": "test",
        "data_dir": Path("data"),
        "output_dir": tmp_path,
    }
    if module_name == "src.social_studies.cli":
        config_kwargs["creative_planning"] = False
    monkeypatch.setattr(
        cli.Config,
        "from_env",
        classmethod(lambda cls, _env_file=None: Config(**config_kwargs)),
    )

    argv = ["generate", "--dry-run", "--seed", "42", "--grade", "8", *extra_args]
    cli.main(argv)
    first_output = capsys.readouterr().out
    assert events == ["resolve-start", "resolve-finished", "generate"]

    events.clear()
    cli.main(argv)
    second_output = capsys.readouterr().out
    assert events == ["resolve-start", "resolve-finished", "generate"]

    def records(output: str) -> list[dict]:
        return [
            json.loads(line)
            for line in output.splitlines()
            if line.startswith("{") and '"payload"' in line
        ]

    assert records(first_output) == records(second_output)
