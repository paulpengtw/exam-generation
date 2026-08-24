"""Generation-outcome metric coverage through the real SSE stream."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")
import sentry_sdk
from pydantic import BaseModel


from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SubjectSpec


class _FakeQuestion(BaseModel):
    id: str
    圖片: str | None = None


class _FakeParams:
    pass


def _make_fake_spec(generation_error: Exception | None = None) -> SubjectSpec:
    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(
        params: Any,
        count: int,
        base_seed: Any,
        overrides: dict,
        config: Any,
        creative_planning: bool,
        decoded_subquestion_configs: Any,
        **_kwargs: Any,
    ) -> list:
        return []

    def do_sample_params(
        params: Any,
        overrides: dict,
        *,
        seed: Any,
        subquestion_configs_decoded: Any,
    ) -> _FakeParams:
        return _FakeParams()

    def do_generate(
        rng_params: Any,
        overrides: dict,
        **kwargs: Any,
    ) -> _FakeQuestion:
        if generation_error is not None:
            raise generation_error
        return _FakeQuestion(id=kwargs["question_id"])

    def extract_prior_scope(question: Any) -> None:
        return None

    def plan_core_questions(
        client: Any,
        topic: str,
        **kwargs: Any,
    ) -> list:  # pragma: no cover
        return []

    def load_planner_stage(
        config_server: Any,
        grade: Any,
    ) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(
        config_server: Any,
        grade: Any,
    ) -> dict:  # pragma: no cover
        return {}

    return SubjectSpec(
        key="fake",
        question_id_prefix="fake_",
        exam_question_cls=_FakeQuestion,
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        do_sample_params=do_sample_params,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        patch_metadata=None,
        plan_core_questions=plan_core_questions,
        load_planner_stage=load_planner_stage,
        build_schemas=build_schemas,
    )


def test_successful_generation_records_one_success_outcome(
    monkeypatch,
    tmp_path: Path,
) -> None:
    metric_calls: list[dict] = []

    def capture_count(name: str, value: int, **kwargs: Any) -> None:
        metric_calls.append({"name": name, "value": value, **kwargs})

    monkeypatch.setattr(sentry_sdk.metrics, "count", capture_count)
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    params = GenerateParams(subject="fake", count=1, skip_verify=True)
    app_state = SimpleNamespace(renderer_pool=None)
    spec = _make_fake_spec()

    async def collect() -> list[dict]:
        events: list[dict] = []
        async for event in generate_question_stream(
            params,
            config,
            app_state,
            subjects={"fake": spec},
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())

    assert [event for event in events if event["event"] == "result"]
    assert metric_calls == [
        {
            "name": "generation.outcome",
            "value": 1,
            "attributes": {"outcome": "success", "subject": "other"},
        }
    ]


def test_failed_generation_records_one_failure_outcome(
    monkeypatch,
    tmp_path: Path,
) -> None:
    metric_calls: list[dict] = []

    def capture_count(name: str, value: int, **kwargs: Any) -> None:
        metric_calls.append({"name": name, "value": value, **kwargs})

    monkeypatch.setattr(sentry_sdk.metrics, "count", capture_count)
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    params = GenerateParams(subject="fake", count=1, skip_verify=True)
    app_state = SimpleNamespace(renderer_pool=None)
    spec = _make_fake_spec(generation_error=RuntimeError("generation failed"))

    async def collect() -> list[dict]:
        events: list[dict] = []
        async for event in generate_question_stream(
            params,
            config,
            app_state,
            subjects={"fake": spec},
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())

    error_events = [event for event in events if event["event"] == "error"]
    assert len(error_events) == 1
    assert metric_calls == [
        {
            "name": "generation.outcome",
            "value": 1,
            "attributes": {"outcome": "failure", "subject": "other"},
        }
    ]
