"""Issue #747: independent question termination and batch-fatal closure."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from types import SimpleNamespace

from server.config import ServerConfig
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from src.social_studies.schemas import ExamQuestion, QuestionMetadata, QuestionType
from tests.server.generate_test_utils import resolved_generate_params


def test_batch_planner_failure_attributes_every_allocated_question_and_closes(
    tmp_path: Path,
) -> None:
    planner_calls = 0

    def fail_planner(*_args, **_kwargs):
        nonlocal planner_calls
        planner_calls += 1
        raise RuntimeError("planner unavailable")

    def must_not_start_worker(*_args, **_kwargs):
        raise AssertionError("workers must not start after a batch-fatal planner error")

    fake_spec = dataclasses.replace(
        SUBJECTS["social_studies"],
        plan_all_batch_briefs=fail_planner,
        do_generate=must_not_start_worker,
    )
    params = resolved_generate_params({
        "subject": "social_studies",
        "count": 2,
        "skip_verify": True,
    })
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    app_state = SimpleNamespace(renderer_pool=None)
    events: list[dict] = []

    async def collect() -> None:
        async for event in generate_question_stream(
            params,
            config,
            app_state,
            subjects={"social_studies": fake_spec},
        ):
            events.append(event)

    asyncio.run(collect())

    assert planner_calls == 1
    assert events[-1]["event"] == "done"
    batch_errors = [
        event for event in events
        if event["event"] == "error" and "question_id" not in event["context"]
    ]
    assert len(batch_errors) == 1
    assert batch_errors[0]["payload"]["code"] == "batch_generation_failed"

    started = events[0]["payload"]
    manifest = {question["index"]: question["question_id"] for question in started["questions"]}
    terminals = [event for event in events if event["event"] == "question_terminal"]
    assert {event["context"]["question_id"] for event in terminals} == set(manifest.values())
    assert all(event["payload"]["termination_reason"] == "failed" for event in terminals)
    assert all(event["payload"]["has_final"] is False for event in terminals)


def test_one_question_failure_does_not_stop_an_unrelated_sibling(tmp_path: Path) -> None:
    def do_generate(rng_params, _overrides, **kwargs):
        if kwargs["question_id"].endswith("_001"):
            raise RuntimeError("question A failed")
        return ExamQuestion(
            id=kwargs["question_id"],
            情境=list(rng_params.情境),
            題型種類=rng_params.題型種類,
            題型=rng_params.題型[0] if rng_params.題型 else QuestionType("選擇題"),
            取材來源=[],
            metadata=QuestionMetadata(grade=rng_params.grade, model="test-model"),
        )

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=do_generate)
    params = resolved_generate_params({
        "subject": "social_studies",
        "count": 2,
        "skip_verify": True,
    })
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    events: list[dict] = []

    async def collect() -> None:
        async for event in generate_question_stream(
            params,
            config,
            SimpleNamespace(renderer_pool=None),
            subjects={"social_studies": fake_spec},
        ):
            events.append(event)

    asyncio.run(collect())

    result_ids = {event["payload"]["id"] for event in events if event["event"] == "result"}
    terminals = {
        event["context"]["question_id"]: event["payload"]
        for event in events
        if event["event"] == "question_terminal"
    }
    assert len(result_ids) == 1
    assert next(iter(result_ids)).endswith("_002")
    assert len(terminals) == 2
    assert sum(payload["termination_reason"] == "failed" for payload in terminals.values()) == 1
    assert sum(payload["termination_reason"] == "normal" for payload in terminals.values()) == 1
    assert events[-1]["event"] == "done"
