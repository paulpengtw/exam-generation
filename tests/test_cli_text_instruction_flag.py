"""Tests for --text-instruction CLI flag on 社會領域 and 自然科學 CLIs (issue #636).

Slices:
  1. SS CLI: --text-instruction value appears in dry-run 文本生成器 prompt.
  2. NS CLI: --text-instruction value appears in dry-run 文本生成器 prompt.
  3. Parity: CLI dry-run 文本生成器 user prompt is byte-identical to the server
     build_prompt_previews seam called with the same resolved payload and
     text_instruction (issue #636 requirement: CLI parity with server).
  4. Omission: flag defaults to None in parse_args; omitting it produces no
     文本出題指示 section in the prompt.
"""
from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers: parse the 文本生成器 user prompt from CLI dry-run stdout
# ---------------------------------------------------------------------------

_USER_PROMPT_RE = re.compile(
    r"=== TEXT USER PROMPT \([^)]*\) ===\n(.*)",
    re.DOTALL,
)


def _parse_cli_user_prompt(out: str) -> str:
    """Extract the full 文本生成器 user prompt from CLI dry-run stdout.

    The dry-run output format is:
      === TEXT USER PROMPT (N chars[, X few-shot images]) ===
      {user_prompt}
    followed by one trailing newline added by print().
    """
    match = _USER_PROMPT_RE.search(out)
    assert match, f"No TEXT USER PROMPT marker in CLI stdout:\n{out[:500]}"
    # print(result) appends one \n after the raw result string; strip it.
    raw = match.group(1)
    if raw.endswith("\n"):
        raw = raw[:-1]
    return raw


# ---------------------------------------------------------------------------
# Slice 1: 社會領域 CLI --text-instruction flag
# ---------------------------------------------------------------------------


def test_ss_parse_args_text_instruction_default_is_none() -> None:
    from src.social_studies.cli import parse_args

    ns = parse_args(["generate"])
    assert ns.text_instruction is None


def test_ss_parse_args_text_instruction_is_captured() -> None:
    from src.social_studies.cli import parse_args

    ns = parse_args(["generate", "--text-instruction", "請聚焦地方自治"])
    assert ns.text_instruction == "請聚焦地方自治"


def test_ss_dry_run_with_text_instruction_contains_value(monkeypatch, capsys) -> None:
    """--text-instruction value appears in the dry-run 文本生成器 user prompt (SS)."""
    import src.social_studies.cli as cli
    from src.config import Config

    instruction = "請聚焦地方自治中的證據比較"

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

    cli.main([
        "generate",
        "--dry-run",
        "--seed", "42",
        "--grade", "8",
        "--text-instruction", instruction,
    ])

    out = capsys.readouterr().out
    user_prompt = _parse_cli_user_prompt(out)
    assert instruction in user_prompt
    assert "文本出題指示" in user_prompt


# ---------------------------------------------------------------------------
# Slice 2: 自然科學 CLI --text-instruction flag
# ---------------------------------------------------------------------------


def test_ns_parse_args_text_instruction_default_is_none() -> None:
    from src.natural_sciences.cli import parse_args

    ns = parse_args(["generate"])
    assert ns.text_instruction is None


def test_ns_parse_args_text_instruction_is_captured() -> None:
    from src.natural_sciences.cli import parse_args

    ns = parse_args(["generate", "--text-instruction", "請聚焦電磁波"])
    assert ns.text_instruction == "請聚焦電磁波"


def test_ns_dry_run_with_text_instruction_contains_value(monkeypatch, capsys) -> None:
    """--text-instruction value appears in the dry-run 文本生成器 user prompt (NS)."""
    import src.natural_sciences.cli as cli
    from src.config import Config

    instruction = "請聚焦電磁波的能量傳遞概念"

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

    cli.main([
        "generate",
        "--dry-run",
        "--seed", "42",
        "--grade", "8",
        "--text-instruction", instruction,
    ])

    out = capsys.readouterr().out
    user_prompt = _parse_cli_user_prompt(out)
    assert instruction in user_prompt
    assert "文本出題指示" in user_prompt


# ---------------------------------------------------------------------------
# Slice 3: Parity — CLI dry-run == server build_prompt_previews (same resolved payload)
#
# Strategy: resolve the same partial payload the CLI would use, set text_instruction,
# JSON-encode list fields as the server/generate/routes.py does, call
# build_prompt_previews (the server seam), and assert the CLI 文本生成器 user prompt
# is byte-identical to the server preview entry without subquestion_index.
#
# This compares the CLI against the SERVER, not against itself — using the same
# reference as production (ADR 0019/0022).
#
# Red/green confirmation: demonstrated manually by temporarily removing the
# text_instruction= forwarding line from social-studies main and running this test.
# ---------------------------------------------------------------------------


def test_ss_parity_cli_dry_run_matches_build_prompt_previews(monkeypatch, capsys) -> None:
    """SS CLI dry-run 文本生成器 user prompt is byte-identical to server build_prompt_previews.

    Both sides resolve the same partial payload
    {"subject": "social_studies", "seed": 300, "grade": 8} and use
    text_instruction="請聚焦地方自治中的證據比較". The server reference uses
    build_prompt_previews from server.generate.service — the real server seam —
    not the CLI module's own build_generation_prompts (which would compare CLI
    against itself rather than against the server).
    """
    import json
    from types import SimpleNamespace

    import src.social_studies.cli as cli
    from server.config import ServerConfig
    from server.generate.models import GenerateParams
    from server.generate.service import build_prompt_previews
    from src.common.resolver import resolve
    from src.config import Config

    _SEED = 300
    _GRADE = 8
    instruction = "請聚焦地方自治中的證據比較"

    config = Config(data_dir=Path("data"), creative_planning=False)
    monkeypatch.setattr(cli.Config, "from_env", classmethod(lambda cls, _ef=None: config))

    # ── CLI side: run main with --dry-run and capture the 文本生成器 user prompt ──
    cli.main([
        "generate",
        "--dry-run",
        "--seed", str(_SEED),
        "--grade", str(_GRADE),
        "--text-instruction", instruction,
    ])
    cli_out = capsys.readouterr().out
    cli_user_prompt = _parse_cli_user_prompt(cli_out)

    # ── Server reference side: build_prompt_previews with same resolved payload ──
    payload = resolve({"subject": "social_studies", "seed": _SEED, "grade": _GRADE}).payload
    payload["text_instruction"] = instruction
    configs = payload.get("subquestion_configs")
    if isinstance(configs, list):
        payload["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)
    rows = payload.get("per_question_params")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("subquestion_configs"), list):
                row["subquestion_configs"] = json.dumps(
                    row["subquestion_configs"], ensure_ascii=False
                )
        payload["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    payload = {k: v for k, v in payload.items() if v is not None}
    params = GenerateParams.model_validate(payload)
    server_config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    previews = build_prompt_previews(params, server_config, SimpleNamespace())
    server_preview = next(p for p in previews if "subquestion_index" not in p)
    server_user_prompt = server_preview["user_prompt"]

    # ── Assert byte-identity ──
    assert "文本出題指示" in cli_user_prompt, (
        "CLI prompt is missing ## 文本出題指示 — text_instruction not forwarded from main()"
    )
    assert "文本出題指示" in server_user_prompt
    assert cli_user_prompt == server_user_prompt, (
        "CLI dry-run user prompt differs from server build_prompt_previews.\n"
        "First differing line:\n" + _first_diff(cli_user_prompt, server_user_prompt)
    )


def test_ns_parity_cli_dry_run_matches_build_prompt_previews(monkeypatch, capsys) -> None:
    """NS CLI dry-run 文本生成器 user prompt is byte-identical to server build_prompt_previews.

    Both sides resolve the same partial payload
    {"subject": "natural_sciences", "seed": 300, "grade": 8} and use
    text_instruction="請聚焦電磁波的能量傳遞概念". The server reference uses
    build_prompt_previews from server.generate.service — the real server seam.
    """
    import json
    from types import SimpleNamespace

    import src.natural_sciences.cli as cli
    from server.config import ServerConfig
    from server.generate.models import GenerateParams
    from server.generate.service import build_prompt_previews
    from src.common.resolver import resolve
    from src.config import Config

    _SEED = 300
    _GRADE = 8
    instruction = "請聚焦電磁波的能量傳遞概念"

    config = Config(data_dir=Path("data"), creative_planning=False)
    monkeypatch.setattr(cli.Config, "from_env", classmethod(lambda cls, _ef=None: config))

    # ── CLI side: run main with --dry-run and capture the 文本生成器 user prompt ──
    cli.main([
        "generate",
        "--dry-run",
        "--seed", str(_SEED),
        "--grade", str(_GRADE),
        "--text-instruction", instruction,
    ])
    cli_out = capsys.readouterr().out
    cli_user_prompt = _parse_cli_user_prompt(cli_out)

    # ── Server reference side: build_prompt_previews with same resolved payload ──
    payload = resolve({"subject": "natural_sciences", "seed": _SEED, "grade": _GRADE}).payload
    payload["text_instruction"] = instruction
    configs = payload.get("subquestion_configs")
    if isinstance(configs, list):
        payload["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)
    rows = payload.get("per_question_params")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("subquestion_configs"), list):
                row["subquestion_configs"] = json.dumps(
                    row["subquestion_configs"], ensure_ascii=False
                )
        payload["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    payload = {k: v for k, v in payload.items() if v is not None}
    params = GenerateParams.model_validate(payload)
    server_config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    previews = build_prompt_previews(params, server_config, SimpleNamespace())
    server_preview = next(p for p in previews if "subquestion_index" not in p)
    server_user_prompt = server_preview["user_prompt"]

    # ── Assert byte-identity ──
    assert "文本出題指示" in cli_user_prompt, (
        "CLI prompt is missing ## 文本出題指示 — text_instruction not forwarded from main()"
    )
    assert "文本出題指示" in server_user_prompt
    assert cli_user_prompt == server_user_prompt, (
        "CLI dry-run user prompt differs from server build_prompt_previews.\n"
        "First differing line:\n" + _first_diff(cli_user_prompt, server_user_prompt)
    )


# ---------------------------------------------------------------------------
# Slice 4: Omission — flag defaults to None; prompt byte-identical without flag
# ---------------------------------------------------------------------------


def test_ss_omitting_text_instruction_flag_gives_none_in_parse_args() -> None:
    from src.social_studies.cli import parse_args

    ns = parse_args(["generate", "--seed", "42"])
    assert ns.text_instruction is None


def test_ns_omitting_text_instruction_flag_gives_none_in_parse_args() -> None:
    from src.natural_sciences.cli import parse_args

    ns = parse_args(["generate", "--seed", "42"])
    assert ns.text_instruction is None


def test_ss_omitting_flag_does_not_add_text_instruction_section(monkeypatch, capsys) -> None:
    """Omitting --text-instruction on SS CLI produces no 文本出題指示 section."""
    import src.social_studies.cli as cli
    from src.config import Config

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

    cli.main([
        "generate",
        "--dry-run",
        "--seed", "42",
        "--grade", "8",
    ])

    out = capsys.readouterr().out
    user_prompt = _parse_cli_user_prompt(out)
    assert "文本出題指示" not in user_prompt


def test_ns_omitting_flag_does_not_add_text_instruction_section(monkeypatch, capsys) -> None:
    """Omitting --text-instruction on NS CLI produces no 文本出題指示 section."""
    import src.natural_sciences.cli as cli
    from src.config import Config

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

    cli.main([
        "generate",
        "--dry-run",
        "--seed", "42",
        "--grade", "8",
    ])

    out = capsys.readouterr().out
    user_prompt = _parse_cli_user_prompt(out)
    assert "文本出題指示" not in user_prompt


def test_ss_blank_text_instruction_acts_like_omission(monkeypatch, capsys) -> None:
    """Blank/whitespace --text-instruction on SS CLI behaves like omission."""
    import src.social_studies.cli as cli
    from src.config import Config

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

    cli.main([
        "generate",
        "--dry-run",
        "--seed", "42",
        "--grade", "8",
        "--text-instruction", "   ",
    ])

    out = capsys.readouterr().out
    user_prompt = _parse_cli_user_prompt(out)
    assert "文本出題指示" not in user_prompt


def test_ns_blank_text_instruction_acts_like_omission(monkeypatch, capsys) -> None:
    """Blank/whitespace --text-instruction on NS CLI behaves like omission."""
    import src.natural_sciences.cli as cli
    from src.config import Config

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

    cli.main([
        "generate",
        "--dry-run",
        "--seed", "42",
        "--grade", "8",
        "--text-instruction", "   ",
    ])

    out = capsys.readouterr().out
    user_prompt = _parse_cli_user_prompt(out)
    assert "文本出題指示" not in user_prompt


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _first_diff(a: str, b: str) -> str:
    """Return the first pair of lines where a and b differ."""
    a_lines = a.splitlines()
    b_lines = b.splitlines()
    for i, (la, lb) in enumerate(zip(a_lines, b_lines)):
        if la != lb:
            return f"line {i+1}\n  CLI: {la!r}\n  ref: {lb!r}"
    if len(a_lines) != len(b_lines):
        return f"different line count: CLI={len(a_lines)}, ref={len(b_lines)}"
    return "(no diff found)"
