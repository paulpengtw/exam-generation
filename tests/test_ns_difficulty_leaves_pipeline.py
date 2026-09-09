"""#282 – 難度 must not appear in any NS pipeline seam.

Slices tested here:
  1. NS 文本 prompt: no 難度
  2. NS 子題 prompt: no 難度
  3. NS verifier prompt: neither 難度 nor "Reporting Scale"
  4. NS CLI: --difficulty rejected; --reporting-scale accepted with validation
  5. NS curriculum data: no 難度 rows in schema_parameters.csv
  6. Regression – Math prompts still mention 難度
  7. Regression – SS prompts still mention 難度
  8. NS sampler: difficulty kwarg accepted but NOT stored on SampledParams.difficulty /
     NOT forwarded into prompts (accepted-and-ignored path from the server)
  9. Old persisted NS questions with metadata.difficulty deserialize without error
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Slice 1: NS 文本 prompt must NOT mention 難度
# ---------------------------------------------------------------------------

def test_ns_text_prompt_no_difficulty(tmp_path: Path) -> None:
    from src.natural_sciences.context_builder import build_text_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=42)
    prompt, _, _draws = build_text_user_prompt(params, tmp_path, rng=random.Random(42))
    assert "難度" not in prompt, "NS 文本 prompt must not mention 難度"


# ---------------------------------------------------------------------------
# Slice 2: NS 子題 prompt must NOT mention 難度
# ---------------------------------------------------------------------------

def test_ns_subquestion_prompt_no_difficulty(tmp_path: Path) -> None:
    from src.natural_sciences.context_builder import build_subquestion_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=42)
    sq_plan = {"序號": 1, "題型": "Simple-multiple-choice", "出題概念": "test"}
    prompt, _, _draws = build_subquestion_user_prompt(
        核心問題="核心",
        文本="文本內容",
        取材來源=["來源"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(42),
    )
    assert "難度" not in prompt, "NS 子題 prompt must not mention 難度"


# ---------------------------------------------------------------------------
# Slice 3: NS verifier prompt must NOT mention 難度 or Reporting Scale
# ---------------------------------------------------------------------------

def test_ns_verifier_prompt_no_difficulty(monkeypatch) -> None:
    from src.natural_sciences import verifier as mod
    from src.natural_sciences.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionSubContext,
        QuestionType,
    )

    captured: dict = {}

    def fake_generate_with_image(system, user_prompt, image_path=None, purpose="verify"):
        captured["user"] = user_prompt
        return '{"passed": true, "answer_match": true, "details": "ok"}'

    client = MagicMock()
    client.generate_with_image = fake_generate_with_image

    q = ExamQuestion(
        id="ns",
        subquestions=[],
        情境=[],
        情境子類別=next(iter(QuestionSubContext)),
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        metadata=QuestionMetadata(grade=8, model="m"),
    )
    mod.verify_question(client, q)
    assert "難度" not in captured["user"], "NS verifier prompt must NOT mention 難度"
    assert "Reporting Scale" not in captured["user"], (
        "NS verifier prompt must NOT mention Reporting Scale"
    )


# ---------------------------------------------------------------------------
# Slice 4: NS CLI --difficulty rejected; --reporting-scale accepted
# ---------------------------------------------------------------------------

def _parse_ns_args(argv: list[str]) -> argparse.Namespace:
    from src.natural_sciences.cli import parse_args
    return parse_args(argv)


def test_ns_cli_rejects_difficulty_flag() -> None:
    """--difficulty should no longer exist on the NS CLI."""
    import pytest  # noqa: PLC0415

    from src.natural_sciences.cli import parse_args

    # parse_args raises SystemExit when it encounters an unknown argument
    with pytest.raises(SystemExit):
        parse_args(["generate", "--difficulty", "hard"])


def test_ns_cli_accepts_reporting_scale_valid() -> None:
    """--reporting-scale accepts all 8 PISA levels."""
    from src.natural_sciences.reporting_scale import REPORTING_SCALE_ORDER

    for level in REPORTING_SCALE_ORDER:
        ns = _parse_ns_args(["generate", "--reporting-scale", level, "--dry-run"])
        assert ns.reporting_scale == level


def test_ns_cli_rejects_reporting_scale_invalid() -> None:
    """--reporting-scale rejects values not in REPORTING_SCALE_ORDER."""
    import pytest

    with pytest.raises(SystemExit):
        _parse_ns_args(["generate", "--reporting-scale", "超級難", "--dry-run"])


# ---------------------------------------------------------------------------
# Slice 5: NS curriculum schema_parameters.csv must have no 難度 rows
# ---------------------------------------------------------------------------

def test_ns_curriculum_no_difficulty_rows() -> None:
    from src.natural_sciences.schema_loader import load_schemas

    schemas = load_schemas()
    assert "難度" not in schemas, (
        "NS schema_parameters.csv must not contain a 難度 category"
    )


# ---------------------------------------------------------------------------
# Slice 6: Regression – Math prompts still mention 難度
# ---------------------------------------------------------------------------

def test_math_prompt_still_contains_difficulty(tmp_path: Path) -> None:
    from src.context_builder import build_user_prompt
    from src.sampler import sample_params as math_sample_params

    params = math_sample_params(seed=1)
    prompt, _, _draws = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "難度" in prompt, "Math prompt must still mention 難度 (regression guard)"


# ---------------------------------------------------------------------------
# Slice 7: Regression – SS prompts still mention 難度
# ---------------------------------------------------------------------------

def test_ss_text_prompt_still_contains_difficulty(tmp_path: Path) -> None:
    from src.social_studies.context_builder import build_text_user_prompt as ss_text
    from src.social_studies.sampler import sample_params as ss_sample

    params = ss_sample(seed=1)
    prompt, _, _draws = ss_text(params, tmp_path, rng=random.Random(1))
    assert "難度" in prompt, "SS 文本 prompt must still mention 難度 (regression guard)"


def test_ss_subquestion_prompt_still_contains_difficulty(tmp_path: Path) -> None:
    from src.social_studies.context_builder import build_subquestion_user_prompt as ss_sub
    from src.social_studies.sampler import sample_params as ss_sample

    params = ss_sample(seed=1)
    sq_plan = {"序號": 1, "題型": "選擇題", "出題概念": "test"}
    prompt, _, _draws = ss_sub(
        核心問題="核心",
        文本="文本",
        取材來源=["來源"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "難度" in prompt, "SS 子題 prompt must still mention 難度 (regression guard)"


# ---------------------------------------------------------------------------
# Slice 8: NS sampler accepted-and-ignored path
# (difficulty kwarg accepted but does not reach the prompt)
# ---------------------------------------------------------------------------

def test_ns_sampler_accepts_difficulty_kwarg() -> None:
    """sample_params must accept difficulty= without raising."""
    from src.natural_sciences.sampler import sample_params

    # Should not raise even though NS no longer uses difficulty
    params = sample_params(seed=1, difficulty="hard")
    assert params is not None


def test_ns_text_prompt_ignores_difficulty_kwarg(tmp_path: Path) -> None:
    """Even when difficulty is passed to sample_params, NS prompt has no 難度."""
    from src.natural_sciences.context_builder import build_text_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=1, difficulty="hard")
    prompt, _, _draws = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "難度" not in prompt, (
        "NS 文本 prompt must not contain 難度 even when difficulty kwarg is passed"
    )


# ---------------------------------------------------------------------------
# Slice 9: Old persisted NS JSON with metadata.difficulty still deserializes
# ---------------------------------------------------------------------------

def test_ns_old_question_with_metadata_difficulty_deserializes() -> None:
    """Existing NS JSON files that carry metadata.difficulty must still load."""
    from src.natural_sciences.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionSubContext,
        QuestionType,
    )

    # Simulate old serialised metadata that included difficulty
    old_metadata_dict = {
        "grade": 8,
        "model": "claude-sonnet-4-6",
        "seed": None,
        "difficulty": "hard",  # persisted in old files
    }
    # Construct an ExamQuestion with old-style metadata dict
    q = ExamQuestion(
        id="old-ns",
        subquestions=[],
        情境=[],
        情境子類別=next(iter(QuestionSubContext)),
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        metadata=QuestionMetadata(**old_metadata_dict),
    )
    # Round-trip through JSON
    raw = json.loads(q.model_dump_json())
    q2 = ExamQuestion(**raw)
    # The field may be present or absent — key point is no ValueError raised
    assert q2.id == "old-ns"
