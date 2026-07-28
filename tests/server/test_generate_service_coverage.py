"""Balanced-coverage wiring in the SS service branch (issue #112)."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from types import SimpleNamespace

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from src.social_studies.schemas import (
    ExamQuestion,
    QuestionMetadata,
    QuestionType,
    SampledParams,
)


def _fake_generate_with_corrections(**kwargs):
    params: SampledParams = kwargs["params"]
    return ExamQuestion(
        id=kwargs["question_id"],
        情境=[c for c in params.情境],
        題型種類=params.題型種類,
        題型=params.題型[0] if params.題型 else QuestionType("選擇題"),
        閱讀歷程=params.閱讀歷程,
        文本形式=params.文本形式,
        題目內容類型=params.題目內容類型,
        # Surface the sampler's resolved 學習內容_pool via 取材來源 (list[str])
        # so tests can assert on it through the normal SSE result payload.
        取材來源=list(params.學習內容_pool),
        metadata=QuestionMetadata(grade=params.grade, model="test-model"),
    )


def _fake_do_generate(rng_params, overrides, **kwargs):
    return _fake_generate_with_corrections(params=rng_params, **kwargs)


_fake_ss_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=_fake_do_generate)


def _run_stream(params: GenerateParams, tmp_path: Path) -> list[dict]:
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    app_state = SimpleNamespace(renderer_pool=None)
    events: list[dict] = []

    async def collect() -> None:
        async for ev in generate_question_stream(
            params, config, app_state,
            subjects={"social_studies": _fake_ss_spec},
        ):
            events.append(ev)

    asyncio.run(collect())
    return events


def test_balanced_batch_covers_distinct_q_types(tmp_path) -> None:
    params = GenerateParams(
        subject="social_studies",
        count=4,
        skip_verify=True,
        coverage_mode="balanced",
        seed=13,
    )
    events = _run_stream(params, tmp_path)
    results = [e["data"] for e in events if e["event"] == "result"]
    assert len(results) == 4

    q_types = [r["題型"] for r in results]
    # 4 questions over the 3-value QuestionType pool: each of the 3 types
    # must appear at least once (⌊4/3⌋+1 balancing guarantee).
    from src.social_studies.schemas import QuestionType as QT

    assert set(q_types) >= {t.value for t in QT}

    assert all(r["metadata"]["coverage_mode_used"] == "balanced" for r in results)


def test_random_mode_skips_batch_sampler_and_stamps_metadata(tmp_path) -> None:
    params = GenerateParams(
        subject="social_studies",
        count=3,
        skip_verify=True,
        coverage_mode="random",
        seed=13,
    )
    events = _run_stream(params, tmp_path)
    results = [e["data"] for e in events if e["event"] == "result"]
    assert len(results) == 3
    assert all(r["metadata"]["coverage_mode_used"] == "random" for r in results)


def test_count_one_stamps_random_regardless_of_flag(tmp_path) -> None:
    params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
        coverage_mode="balanced",
        seed=5,
    )
    events = _run_stream(params, tmp_path)
    results = [e["data"] for e in events if e["event"] == "result"]
    assert len(results) == 1
    assert results[0]["metadata"]["coverage_mode_used"] == "random"


def test_user_q_type_pool_wins_over_balanced_assignment(tmp_path) -> None:
    # User pinned q_type; balanced assignment must be a no-op for 題型.
    params = GenerateParams(
        subject="social_studies",
        count=3,
        skip_verify=True,
        coverage_mode="balanced",
        q_type=["開放式建構反應題"],
        seed=13,
    )
    events = _run_stream(params, tmp_path)
    results = [e["data"] for e in events if e["event"] == "result"]
    assert {r["題型"] for r in results} == {"開放式建構反應題"}


def test_user_learning_content_wins_over_balanced_assignment(tmp_path) -> None:
    # User pinned 學習內容; balanced batch planning must never zero it out —
    # every emitted question's sampled LC pool must equal the user's pin.
    params = GenerateParams(
        subject="social_studies",
        count=2,
        skip_verify=True,
        coverage_mode="balanced",
        learning_content=["公Aa-Ⅳ-1"],
        seed=13,
    )
    events = _run_stream(params, tmp_path)
    results = [e["data"] for e in events if e["event"] == "result"]
    assert len(results) == 2
    assert all(r["取材來源"] == ["公Aa-Ⅳ-1"] for r in results)
