"""Tests for reference example entries returned by each prompt builder.

Acceptance criteria for feature #670: every builder returns a non-empty list of
reference-example entries when few-shot examples are available, and an empty list when
disabled (where supported).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.context_builder import (
    build_subquestion_user_prompt as math_build_subquestion_user_prompt,
)
from src.context_builder import (
    build_text_user_prompt as math_build_text_user_prompt,
)
from src.context_builder import (
    build_user_prompt as math_build_user_prompt,
)
from src.natural_sciences.context_builder import (
    build_subquestion_user_prompt as ns_build_subquestion_user_prompt,
)
from src.natural_sciences.context_builder import (
    build_text_user_prompt as ns_build_text_user_prompt,
)
from src.natural_sciences.context_builder import (
    build_user_prompt as ns_build_user_prompt,
)
from src.natural_sciences.data_loader import folder_for_question_type
from src.natural_sciences.sampler import sample_params as ns_sample_params
from src.sampler import sample_params as math_sample_params
from src.social_studies.context_builder import (
    build_subquestion_user_prompt as ss_build_subquestion_user_prompt,
)
from src.social_studies.context_builder import (
    build_text_user_prompt as ss_build_text_user_prompt,
)
from src.social_studies.context_builder import (
    build_user_prompt as ss_build_user_prompt,
)
from src.social_studies.sampler import sample_params as ss_sample_params

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MATH_EXAMPLE = {
    "description": "test math example",
    "question": {"題型": "選擇題", "題目": ["test question text"]},
}
_SS_EXAMPLE = [
    {
        "description": "test ss example",
        "question": {"題型": "選擇題", "題目": ["test question text"]},
    }
]
_NS_EXAMPLE = {
    "description": "test ns example",
    "question": {"題型": "Simple multiple-choice", "題目": ["test question text"]},
}


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _seed_math_fewshot(tmp_path: Path, style: str) -> None:
    _write_json(tmp_path / style / "example.json", _MATH_EXAMPLE)


def _seed_math_grouped_fewshot(tmp_path: Path) -> None:
    _write_json(tmp_path / "grouped" / "example.json", _MATH_EXAMPLE)


def _seed_ss_fewshot(tmp_path: Path, content_type: str) -> None:
    _write_json(tmp_path / content_type / "example.json", _SS_EXAMPLE)


def _seed_ns_fewshot(tmp_path: Path, q_type: str) -> None:
    folder = folder_for_question_type(q_type) or q_type.replace(" ", "-")
    _write_json(tmp_path / folder / "example.json", _NS_EXAMPLE)


# ---------------------------------------------------------------------------
# Math: build_user_prompt
# ---------------------------------------------------------------------------


def test_math_build_user_prompt_returns_ref_entries_when_examples_exist(tmp_path: Path) -> None:
    params = math_sample_params(seed=1)
    _seed_math_fewshot(tmp_path, params.style.value)

    _, _, entries = math_build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert len(entries) > 0
    entry = entries[0]
    assert entry["code"] == "reference_example"
    assert entry["kind"] == "example"
    assert entry["stage"] == "generator"
    assert "source" in entry
    assert "description" in entry


def test_math_build_user_prompt_returns_empty_when_no_examples(tmp_path: Path) -> None:
    params = math_sample_params(seed=1)
    # No few-shot files → empty entries
    _, _, entries = math_build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert entries == []


# ---------------------------------------------------------------------------
# Math: build_text_user_prompt
# ---------------------------------------------------------------------------


def test_math_build_text_user_prompt_returns_ref_entries_when_examples_exist(
    tmp_path: Path,
) -> None:
    params = math_sample_params(seed=1)
    _seed_math_grouped_fewshot(tmp_path)

    _, _, entries = math_build_text_user_prompt(params, tmp_path, rng=random.Random(1))

    assert len(entries) > 0
    entry = entries[0]
    assert entry["code"] == "reference_example"
    assert entry["kind"] == "example"
    assert entry["stage"] == "text_generator"
    assert "source" in entry


def test_math_build_text_user_prompt_disable_returns_empty(tmp_path: Path) -> None:
    params = math_sample_params(seed=1)
    _seed_math_grouped_fewshot(tmp_path)

    _, _, entries = math_build_text_user_prompt(
        params, tmp_path, rng=random.Random(1), disable_reference_fewshot=True
    )

    assert entries == []


# ---------------------------------------------------------------------------
# Math: build_subquestion_user_prompt
# ---------------------------------------------------------------------------


def test_math_build_subquestion_user_prompt_returns_ref_entries_when_examples_exist(
    tmp_path: Path,
) -> None:
    params = math_sample_params(seed=1)
    _seed_math_grouped_fewshot(tmp_path)
    sq_plan = {"序號": 1, "題型": "選擇題", "出題概念": "test concept"}

    _, _, entries = math_build_subquestion_user_prompt(
        核心問題="test core question",
        文本="test text",
        取材來源=["source A"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )

    assert len(entries) > 0
    entry = entries[0]
    assert entry["code"] == "reference_example"
    assert entry["kind"] == "example"
    assert entry["stage"] == "subquestion_generator"
    assert entry["slot"] == 1


def test_math_build_subquestion_user_prompt_disable_returns_empty(tmp_path: Path) -> None:
    params = math_sample_params(seed=1)
    _seed_math_grouped_fewshot(tmp_path)
    sq_plan = {"序號": 1, "題型": "選擇題", "出題概念": "test concept"}

    _, _, entries = math_build_subquestion_user_prompt(
        核心問題="test core question",
        文本="test text",
        取材來源=["source A"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
        disable_reference_fewshot=True,
    )

    assert entries == []


# ---------------------------------------------------------------------------
# Social Studies: build_user_prompt
# ---------------------------------------------------------------------------


def test_ss_build_user_prompt_returns_ref_entries_when_examples_exist(tmp_path: Path) -> None:
    params = ss_sample_params(seed=1)
    content_type = params.題目內容類型 or "純文字"
    _seed_ss_fewshot(tmp_path, content_type)

    _, _, entries = ss_build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert len(entries) > 0
    entry = entries[0]
    assert entry["code"] == "reference_example"
    assert entry["kind"] == "example"
    assert entry["stage"] == "generator"
    assert "source" in entry


def test_ss_build_user_prompt_disable_returns_empty(tmp_path: Path) -> None:
    params = ss_sample_params(seed=1)
    content_type = params.題目內容類型 or "純文字"
    _seed_ss_fewshot(tmp_path, content_type)

    _, _, entries = ss_build_user_prompt(
        params, tmp_path, rng=random.Random(1), disable_reference_fewshot=True
    )

    assert entries == []


# ---------------------------------------------------------------------------
# Social Studies: build_text_user_prompt
# ---------------------------------------------------------------------------


def test_ss_build_text_user_prompt_returns_ref_entries_when_examples_exist(
    tmp_path: Path,
) -> None:
    params = ss_sample_params(seed=1)
    content_type = params.題目內容類型 or "純文字"
    _seed_ss_fewshot(tmp_path, content_type)

    _, _, entries = ss_build_text_user_prompt(params, tmp_path, rng=random.Random(1))

    assert len(entries) > 0
    entry = entries[0]
    assert entry["code"] == "reference_example"
    assert entry["kind"] == "example"
    assert entry["stage"] == "text_generator"
    assert "source" in entry


def test_ss_build_text_user_prompt_disable_returns_empty(tmp_path: Path) -> None:
    params = ss_sample_params(seed=1)
    content_type = params.題目內容類型 or "純文字"
    _seed_ss_fewshot(tmp_path, content_type)

    _, _, entries = ss_build_text_user_prompt(
        params, tmp_path, rng=random.Random(1), disable_reference_fewshot=True
    )

    assert entries == []


# ---------------------------------------------------------------------------
# Social Studies: build_subquestion_user_prompt
# ---------------------------------------------------------------------------


def test_ss_build_subquestion_user_prompt_example_entry_has_correct_shape(
    tmp_path: Path,
) -> None:
    params = ss_sample_params(seed=1)
    content_type = params.題目內容類型 or "純文字"
    _seed_ss_fewshot(tmp_path, content_type)
    sq_plan = {"序號": 2, "題型": "選擇題", "出題概念": "test concept"}

    _, _, entries = ss_build_subquestion_user_prompt(
        核心問題="test core question",
        文本={"文本": "test passage"},
        取材來源=["source A"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )

    assert isinstance(entries, list)
    for entry in entries:
        assert entry["code"] == "reference_example"
        assert entry["stage"] == "subquestion_generator"
        assert entry["slot"] == 2
        assert entry["kind"] in {"example", "process_exemplar"}


def test_ss_build_subquestion_user_prompt_disable_suppresses_example_entries(
    tmp_path: Path,
) -> None:
    params = ss_sample_params(seed=1)
    content_type = params.題目內容類型 or "純文字"
    _seed_ss_fewshot(tmp_path, content_type)
    sq_plan = {"序號": 1, "題型": "選擇題", "出題概念": "test concept"}

    _, _, entries = ss_build_subquestion_user_prompt(
        核心問題="test core question",
        文本={"文本": "test passage"},
        取材來源=["source A"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
        disable_reference_fewshot=True,
    )

    example_entries = [e for e in entries if e.get("kind") == "example"]
    assert example_entries == []


# ---------------------------------------------------------------------------
# Natural Sciences: build_user_prompt
# ---------------------------------------------------------------------------


def test_ns_build_user_prompt_returns_ref_entries_when_examples_exist(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1)
    _seed_ns_fewshot(tmp_path, params.題型.value)

    _, _, entries = ns_build_user_prompt(params, tmp_path, rng=random.Random(1))

    assert len(entries) > 0
    entry = entries[0]
    assert entry["code"] == "reference_example"
    assert entry["kind"] == "example"
    assert entry["stage"] == "generator"
    assert "source" in entry


def test_ns_build_user_prompt_disable_returns_empty(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1)
    _seed_ns_fewshot(tmp_path, params.題型.value)

    _, _, entries = ns_build_user_prompt(
        params, tmp_path, rng=random.Random(1), disable_reference_fewshot=True
    )

    assert entries == []


# ---------------------------------------------------------------------------
# Natural Sciences: build_text_user_prompt
# ---------------------------------------------------------------------------


def test_ns_build_text_user_prompt_returns_ref_entries_when_examples_exist(
    tmp_path: Path,
) -> None:
    params = ns_sample_params(seed=1)
    _seed_ns_fewshot(tmp_path, params.題型.value)

    _, _, entries = ns_build_text_user_prompt(params, tmp_path, rng=random.Random(1))

    assert len(entries) > 0
    entry = entries[0]
    assert entry["code"] == "reference_example"
    assert entry["kind"] == "example"
    assert entry["stage"] == "text_generator"
    assert "source" in entry


def test_ns_build_text_user_prompt_disable_returns_empty(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1)
    _seed_ns_fewshot(tmp_path, params.題型.value)

    _, _, entries = ns_build_text_user_prompt(
        params, tmp_path, rng=random.Random(1), disable_reference_fewshot=True
    )

    assert entries == []


# ---------------------------------------------------------------------------
# Natural Sciences: build_subquestion_user_prompt
# ---------------------------------------------------------------------------


def test_ns_build_subquestion_user_prompt_returns_ref_entries_when_examples_exist(
    tmp_path: Path,
) -> None:
    params = ns_sample_params(seed=1)
    _seed_ns_fewshot(tmp_path, params.題型.value)
    sq_plan = {"序號": 2, "題型": params.題型.value, "出題概念": "test concept"}

    _, _, entries = ns_build_subquestion_user_prompt(
        核心問題="test core question",
        文本="test passage text",
        取材來源=["source A"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )

    assert len(entries) > 0
    entry = entries[0]
    assert entry["code"] == "reference_example"
    assert entry["kind"] == "example"
    assert entry["stage"] == "subquestion_generator"
    assert entry["slot"] == 2


def test_ns_build_subquestion_user_prompt_disable_returns_empty(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1)
    _seed_ns_fewshot(tmp_path, params.題型.value)
    sq_plan = {"序號": 1, "題型": params.題型.value, "出題概念": "test concept"}

    _, _, entries = ns_build_subquestion_user_prompt(
        核心問題="test core question",
        文本="test passage text",
        取材來源=["source A"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
        disable_reference_fewshot=True,
    )

    assert entries == []
