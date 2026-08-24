"""Coverage mode does not drive SS draws and metadata reflects requests (#211)."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

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


def test_balanced_and_random_draw_identically_for_the_same_seed(tmp_path) -> None:
    balanced_params = GenerateParams(
        subject="social_studies",
        count=4,
        skip_verify=True,
        coverage_mode="balanced",
        seed=13,
    )
    random_params = GenerateParams(
        subject="social_studies",
        count=4,
        skip_verify=True,
        coverage_mode="random",
        seed=13,
    )
    balanced_events = _run_stream(balanced_params, tmp_path)
    random_events = _run_stream(random_params, tmp_path)
    balanced_results = [
        e["data"] for e in balanced_events if e["event"] == "result"
    ]
    random_results = [e["data"] for e in random_events if e["event"] == "result"]

    assert len(balanced_results) == 4
    assert len(random_results) == 4

    # Workers run concurrently so results may arrive in any order; sort by the
    # numeric suffix of the question ID (e.g. "ss_20250101_001" → "001") to
    # align the two lists by worker index before comparing.
    def _by_worker(r: dict) -> str:
        return r.get("id", "").rsplit("_", 1)[-1]

    balanced_sorted = sorted(balanced_results, key=_by_worker)
    random_sorted = sorted(random_results, key=_by_worker)

    assert [r["題型"] for r in balanced_sorted] == [
        r["題型"] for r in random_sorted
    ]
    assert [r["取材來源"] for r in balanced_sorted] == [
        r["取材來源"] for r in random_sorted
    ]


def test_random_mode_stamps_metadata(tmp_path) -> None:
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


def test_count_one_stamps_the_requested_mode(tmp_path) -> None:
    balanced_params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
        coverage_mode="balanced",
        seed=5,
    )
    random_params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
        coverage_mode="random",
        seed=5,
    )
    balanced_events = _run_stream(balanced_params, tmp_path)
    random_events = _run_stream(random_params, tmp_path)
    balanced_results = [
        e["data"] for e in balanced_events if e["event"] == "result"
    ]
    random_results = [e["data"] for e in random_events if e["event"] == "result"]

    assert len(balanced_results) == 1
    assert len(random_results) == 1
    assert balanced_results[0]["metadata"]["coverage_mode_used"] == "balanced"
    assert random_results[0]["metadata"]["coverage_mode_used"] == "random"


def test_coverage_mode_used_reflects_the_requested_mode_for_a_batch(tmp_path) -> None:
    balanced_params = GenerateParams(
        subject="social_studies",
        count=3,
        skip_verify=True,
        coverage_mode="balanced",
        seed=13,
    )
    random_params = GenerateParams(
        subject="social_studies",
        count=3,
        skip_verify=True,
        coverage_mode="random",
        seed=13,
    )
    balanced_events = _run_stream(balanced_params, tmp_path)
    random_events = _run_stream(random_params, tmp_path)
    balanced_results = [
        e["data"] for e in balanced_events if e["event"] == "result"
    ]
    random_results = [e["data"] for e in random_events if e["event"] == "result"]

    assert len(balanced_results) == 3
    assert len(random_results) == 3
    assert all(
        r["metadata"]["coverage_mode_used"] == "balanced"
        for r in balanced_results
    )
    assert all(
        r["metadata"]["coverage_mode_used"] == "random" for r in random_results
    )


def test_user_q_type_pool_wins_over_balanced_assignment(tmp_path) -> None:
    # An explicit user q_type pin must determine every 題型 draw.
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
    # Every emitted question's sampled LC pool must equal the user's explicit pin.
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
