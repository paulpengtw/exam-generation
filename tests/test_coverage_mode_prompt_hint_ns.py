from __future__ import annotations

import random
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.generate.service import build_prompt_previews
from src.common.batch_dedup import PriorScope
from src.natural_sciences.context_builder import build_text_user_prompt
from src.natural_sciences.sampler import sample_params
from tests.server.generate_test_utils import resolved_generate_params


def test_ns_default_call_is_byte_identical(tmp_path) -> None:
    params = sample_params(seed=5)

    default_prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
    )
    explicit_random_prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
        balanced_batch=False,
    )

    assert default_prompt == explicit_random_prompt
    assert "## 出題模式：均衡" not in default_prompt
    assert "## 出題模式：均衡" not in explicit_random_prompt


def test_ns_balanced_batch_injects_the_spread_instruction(tmp_path) -> None:
    params = sample_params(seed=5)

    prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
        balanced_batch=True,
    )

    assert "## 出題模式：均衡" in prompt
    assert "題型" in prompt
    assert "取材角度" in prompt


def test_ns_server_balanced_batch_produces_prompt_with_spread_instruction(tmp_path) -> None:
    """build_prompt_previews with NS coverage_mode=balanced count>1 → 均衡 block in user prompt."""
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ns_curriculum_context=None)
    params = resolved_generate_params(
        {
            "subject": "natural_sciences",
            "count": 3,
            "coverage_mode": "balanced",
            "seed": 193,
        }
    )

    previews = build_prompt_previews(params, config, app_state)
    text_previews = [p for p in previews if "subquestion_index" not in p]

    assert len(text_previews) == 3
    assert all("## 出題模式：均衡" in p["user_prompt"] for p in text_previews)


def test_ns_server_random_mode_omits_the_spread_instruction(tmp_path) -> None:
    """build_prompt_previews with NS coverage_mode=random → no 均衡 block."""
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ns_curriculum_context=None)
    params = resolved_generate_params(
        {
            "subject": "natural_sciences",
            "count": 3,
            "coverage_mode": "random",
            "seed": 194,
        }
    )

    previews = build_prompt_previews(params, config, app_state)
    text_previews = [p for p in previews if "subquestion_index" not in p]

    assert len(text_previews) == 3
    assert all("## 出題模式：均衡" not in p["user_prompt"] for p in text_previews)


def test_ns_server_count_one_omits_spread_instruction_even_under_balanced(tmp_path) -> None:
    """count=1 → no 均衡 block even when coverage_mode=balanced."""
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ns_curriculum_context=None)
    params = resolved_generate_params(
        {
            "subject": "natural_sciences",
            "count": 1,
            "coverage_mode": "balanced",
            "seed": 195,
        }
    )

    previews = build_prompt_previews(params, config, app_state)
    text_previews = [p for p in previews if "subquestion_index" not in p]

    assert len(text_previews) == 1
    assert "## 出題模式：均衡" not in text_previews[0]["user_prompt"]


def test_ns_metadata_echo_carries_coverage_mode_used(tmp_path) -> None:
    """NS QuestionMetadata must have a coverage_mode_used field."""
    from src.natural_sciences.schemas import QuestionMetadata
    meta = QuestionMetadata(grade=7, model="test")
    assert hasattr(meta, "coverage_mode_used")
    assert meta.coverage_mode_used is None

    meta_balanced = QuestionMetadata(grade=7, model="test", coverage_mode_used="balanced")
    assert meta_balanced.coverage_mode_used == "balanced"

    meta_random = QuestionMetadata(grade=7, model="test", coverage_mode_used="random")
    assert meta_random.coverage_mode_used == "random"


def test_ns_server_stamps_coverage_mode_used_on_metadata(tmp_path) -> None:
    """generate_question_stream must stamp coverage_mode_used on NS question metadata."""
    import asyncio
    import dataclasses

    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from src.natural_sciences.schemas import (
        ExamQuestion as NSExamQuestion,
    )
    from src.natural_sciences.schemas import (
        QuestionContext as NSQuestionContext,
    )
    from src.natural_sciences.schemas import (
        QuestionMetadata as NSQuestionMetadata,
    )
    from src.natural_sciences.schemas import (
        QuestionSetType as NSQuestionSetType,
    )
    from src.natural_sciences.schemas import (
        QuestionType as NSQuestionType,
    )

    def _fake_ns_do_generate(rng_params, overrides, **kwargs):
        return NSExamQuestion(
            id=kwargs["question_id"],
            情境=[NSQuestionContext("Personal")],
            題型種類=NSQuestionSetType("題組題"),
            題型=NSQuestionType("Simple multiple-choice"),
            metadata=NSQuestionMetadata(grade=rng_params.grade, model="test-model"),
        )

    fake_ns_spec = dataclasses.replace(
        SUBJECTS["natural_sciences"], do_generate=_fake_ns_do_generate
    )

    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    app_state = SimpleNamespace(renderer_pool=None)
    params = resolved_generate_params(
        {
            "subject": "natural_sciences",
            "count": 3,
            "skip_verify": True,
            "coverage_mode": "balanced",
            "seed": 13,
        }
    )
    events: list[dict] = []

    async def collect() -> None:
        async for ev in generate_question_stream(
            params, config, app_state,
            subjects={"natural_sciences": fake_ns_spec},
        ):
            events.append(ev)

    asyncio.run(collect())
    results = [e["data"] for e in events if e["event"] == "result"]
    assert len(results) == 3
    assert all(r["metadata"]["coverage_mode_used"] == "balanced" for r in results)


def test_ns_balanced_instruction_coexists_with_prior_scopes_block(tmp_path) -> None:
    params = sample_params(seed=5)
    scopes = [
        PriorScope(summary="光合作用如何將光能轉換為化學能？", codes=["INc-IV-1"]),
    ]

    prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
        balanced_batch=True,
        prior_scopes=scopes,
    )

    assert "## 出題模式：均衡" in prompt
    assert "## 已生成題目（請避免相似範圍）" in prompt
