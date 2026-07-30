"""Malformed subquestion_configs emits a stage error event to the SSE stream (issue #257 slice 3).

The error event must appear in the stream AND generation must still proceed
(existing fail-open / discard behavior preserved).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SubjectSpec


class _FakeQuestion(BaseModel):
    id: str
    圖片: str | None = None


def _make_fake_spec() -> SubjectSpec:
    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(
        params: Any, count: int, base_seed: Any, overrides: dict,
        config: Any, creative_planning: bool, decoded_subquestion_configs: Any,
        **_kwargs: Any,
    ) -> list:
        return []

    def do_sample_params(
        params: Any, overrides: dict, *, seed: Any, subquestion_configs_decoded: Any,
    ) -> object:
        return object()

    def do_generate(rng_params: Any, overrides: dict, **kwargs: Any) -> _FakeQuestion:
        return _FakeQuestion(id=kwargs["question_id"])

    def extract_prior_scope(question: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kwargs: Any) -> list:
        return []

    def load_planner_stage(config_server: Any, grade: Any) -> str:
        return "第四學習階段"

    def build_schemas(config_server: Any, grade: Any) -> dict:
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


def _collect_events(params: GenerateParams, config: ServerConfig) -> list[dict]:
    app_state = SimpleNamespace(renderer_pool=None)
    fake_spec = _make_fake_spec()

    async def _run() -> list[dict]:
        events: list[dict] = []
        async for evt in generate_question_stream(
            params,
            config,
            app_state,
            subjects={"fake": fake_spec},
        ):
            events.append(evt)
        return events

    return asyncio.run(_run())


def test_malformed_json_emits_stage_error_event(tmp_path: Path) -> None:
    """Malformed subquestion_configs JSON → stage error event in SSE stream."""
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    params = GenerateParams(
        subject="fake",
        count=1,
        skip_verify=True,
        subquestion_configs="INVALID JSON!@#$",
    )

    events = _collect_events(params, config)

    stage_errors = [
        e for e in events
        if e.get("event") == "stage"
        and isinstance(e.get("data"), dict)
        and e["data"].get("status") == "error"
        and e["data"].get("stage") == "subquestion_configs"
    ]
    assert len(stage_errors) == 1, f"Expected 1 stage error, got: {stage_errors}"
    msg = stage_errors[0]["data"].get("message", "")
    assert "subquestion_configs" in msg.lower() or "parse" in msg.lower() or "JSON" in msg, \
        f"Error message not informative: {msg!r}"


def test_generation_proceeds_despite_malformed_configs(tmp_path: Path) -> None:
    """Generation still produces a result even with malformed subquestion_configs."""
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    params = GenerateParams(
        subject="fake",
        count=1,
        skip_verify=True,
        subquestion_configs='{"not": "an array"}',
    )

    events = _collect_events(params, config)

    # A result event must appear
    result_events = [e for e in events if e.get("event") == "result"]
    assert len(result_events) == 1, f"Expected 1 result event, got events: {[e['event'] for e in events]}"

    # A stage error must also appear for subquestion_configs
    stage_errors = [
        e for e in events
        if e.get("event") == "stage"
        and isinstance(e.get("data"), dict)
        and e["data"].get("status") == "error"
        and e["data"].get("stage") == "subquestion_configs"
    ]
    assert len(stage_errors) == 1
