"""Real-publisher replay fixture for social-studies fixed-slot delivery (#744)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "generation_v2"
    / "social_groups_interleaved.jsonl"
)


class _FakeClient:
    def __init__(self, _config: Any) -> None:
        self._observer = None

    def set_observer(self, observer: Any) -> None:
        self._observer = observer

    def clear_observer(self) -> None:
        self._observer = None

    def emit(self, event: dict[str, Any]) -> None:
        if self._observer is not None:
            self._observer(event)


def _mask_item(item: dict[str, Any], run_id: str) -> dict[str, Any]:
    raw = json.dumps(item, ensure_ascii=False)
    raw = raw.replace(run_id, "RUN")
    raw = re.sub(r'"ts":\s*\d+(?:\.\d+)?', '"ts": 0.0', raw)
    raw = re.sub(r'"generation_log_id":\s*"[^"]*"', '"generation_log_id": "LOG"', raw)
    raw = re.sub(
        r'"[^"\n]*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^"\n]*"',
        '"TS"',
        raw,
    )
    return json.loads(raw)


def _subquestion(qid: str, slot: int, label: str):
    from src.social_studies.schemas import SubQuestion

    sub = SubQuestion(
        id=f"{qid}-sq{slot:03d}",
        序號=slot,
        年級=8,
        科目=["地理"],
        題型="選擇題",
        題目=f"{label} 小題 {slot}",
        答案="A",
        答案解析="解析",
    )
    sub._plan_index = slot
    return sub


def _run_stream(tmp_path: Path) -> tuple[list[dict[str, Any]], str]:
    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from src.common.generation_events import new_call_scope, new_operation_scope
    from src.social_studies.schemas import ExamQuestion, QuestionType
    from tests.server.generate_test_utils import resolved_generate_params

    params = resolved_generate_params({
        "subject": "social_studies",
        "seed": 744,
        "count": 2,
        "sub_question_count": 3,
        "skip_verify": True,
    })
    b_done = threading.Event()

    def fake_do_generate(rng_params: Any, _overrides: Any, **kwargs: Any) -> Any:
        qid = kwargs["question_id"]
        client: _FakeClient = kwargs["client"]
        on_update = kwargs["on_question_update"]
        context = kwargs["question_context"]
        is_b = context.index == 1
        label = "B" if is_b else "A"

        def stage(scope: Any, status: str, *, supersedes: str | None = None) -> None:
            event = {
                "type": "stage",
                "agent": "sub_generator#2" if scope.kind == "subquestion" else "generator",
                "stage": "llm_generate",
                "status": status,
                "run_id": scope.run_id,
                "operation_id": scope.operation_id,
                "subquestion_index": scope.subquestion_index,
                "ts": 0.0,
            }
            if supersedes is not None:
                event["supersedes_operation_id"] = supersedes
            client.emit(event)

        def call(scope: Any, *, retry_of: str | None = None) -> None:
            call_scope = new_call_scope(scope, retry_of_call_id=retry_of)
            base = {
                "run_id": call_scope.run_id,
                "operation_id": call_scope.operation_id,
                "call_id": call_scope.call_id,
                "agent": "sub_generator#2",
                "purpose": "generate",
                "subquestion_index": scope.subquestion_index,
                "ts": 0.0,
            }
            if retry_of is not None:
                base["retry_of_call_id"] = retry_of
            client.emit({"type": "llm_request", **base})
            client.emit({"type": "llm_response", **base})
            return call_scope

        text_scope = new_operation_scope(context, kind="text")
        stage(text_scope, "start")
        call(text_scope)
        stage(text_scope, "end")
        client.emit({
            "type": "plan",
            "agent": "generator",
            "run_id": text_scope.run_id,
            "operation_id": text_scope.operation_id,
            "sub_question_total": 3,
            "slots": [
                {
                    "subquestion_index": slot - 1,
                    "id": f"{qid}-sq{slot:03d}",
                    "序號": slot,
                }
                for slot in (1, 2, 3)
            ],
            "ts": 0.0,
        })

        shell = ExamQuestion(
            id=qid,
            核心問題=f"核心問題 {label}",
            文本=f"文本 {label}",
            取材來源=[f"來源 {label}"],
            情境=list(rng_params.情境),
            題型種類=rng_params.題型種類,
            題型=rng_params.題型[0] if rng_params.題型 else QuestionType("選擇題"),
            題目內容類型=rng_params.題目內容類型,
        )
        on_update(shell, "draft")

        if is_b:
            for slot in (1, 2, 3):
                shell.subquestions.append(_subquestion(qid, slot, label))
                on_update(shell, "draft")
            b_done.set()
        else:
            shell.subquestions.append(_subquestion(qid, 1, label))
            on_update(shell, "draft")
            old_scope = new_operation_scope(context, kind="subquestion", subquestion_index=1)
            stage(old_scope, "start")
            old_call = call(old_scope)
            stage(old_scope, "error")
            retry_scope = new_operation_scope(
                context,
                kind="subquestion",
                subquestion_index=1,
                supersedes_operation_id=old_scope.operation_id,
            )
            stage(retry_scope, "start", supersedes=old_scope.operation_id)
            call(retry_scope, retry_of=old_call.call_id)
            stage(retry_scope, "end")
            shell.subquestions.append(_subquestion(qid, 3, label))
            on_update(shell, "draft")
            b_done.wait(timeout=10)

        return shell

    spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)
    config = ServerConfig(
        api_key="x",
        gemini_api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    app_state = SimpleNamespace(renderer_pool=None)

    async def collect() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in generate_question_stream(
            params,
            config,
            app_state,
            subjects={"social_studies": spec},
            client_factory=_FakeClient,
        ):
            events.append(event)
        return events

    with patch("server.observability.record_generation_outcome"):
        events = asyncio.run(collect())
    return events, events[0]["context"]["run_id"]


def test_social_fixed_slot_fixture_and_terminal(tmp_path: Path) -> None:
    from server.generate.event_protocol import QuestionTerminalPayload

    events, run_id = _run_stream(tmp_path)
    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "done"
    assert [event["context"]["event_seq"] for event in events] == list(range(1, len(events) + 1))

    plans = [event for event in events if event["event"] == "plan"]
    assert len(plans) == 2
    assert plans[0]["payload"]["slots"][1] == {
        "subquestion_index": 1,
        "id": f'{plans[0]["context"]["question_id"]}-sq002',
        "序號": 2,
    }

    announced_by_question = {
        plan["context"]["question_id"]: {
            slot["subquestion_index"]: slot
            for slot in plan["payload"]["slots"]
        }
        for plan in plans
    }
    operation_slots: dict[str, int] = {}
    for event in events:
        context = event["context"]
        subquestion_index = context.get("subquestion_index")
        if subquestion_index is None:
            continue
        question_slots = announced_by_question[context["question_id"]]
        agent = event["payload"].get("agent", "")
        announced_index = int(agent.rsplit("#", 1)[1]) - 1
        assert subquestion_index == question_slots[announced_index]["subquestion_index"]
        operation_id = context["operation_id"]
        prior_index = operation_slots.setdefault(operation_id, subquestion_index)
        assert prior_index == subquestion_index

    result_a = next(
        event for event in events
        if event["event"] == "result" and event["context"]["index"] == 0
    )
    result_b = next(
        event for event in events
        if event["event"] == "result" and event["context"]["index"] == 1
    )
    assert result_b["context"]["event_seq"] < result_a["context"]["event_seq"]
    assert [sub["id"] for sub in result_a["payload"]["subquestions"]] == [
        f'{result_a["context"]["question_id"]}-sq001',
        f'{result_a["context"]["question_id"]}-sq003',
    ]
    updates_a = [
        event for event in events
        if event["event"] == "question_update" and event["context"]["index"] == 0
    ]
    assert [event["context"]["content_revision"] for event in updates_a] == [1, 2, 3]
    assert [len(event["payload"]["question"]["subquestions"]) for event in updates_a] == [0, 1, 2]

    terminal_a = next(
        event for event in events
        if event["event"] == "question_terminal" and event["context"]["index"] == 0
    )
    terminal_b = next(
        event for event in events
        if event["event"] == "question_terminal" and event["context"]["index"] == 1
    )
    QuestionTerminalPayload.model_validate(terminal_a["payload"])
    QuestionTerminalPayload.model_validate(terminal_b["payload"])
    assert terminal_a["payload"]["delivery_status"] == "partial"
    assert terminal_a["payload"]["missing"][0]["subquestion_id"].endswith("-sq002")
    assert terminal_b["payload"]["delivery_status"] == "complete"

    a_operations = {
        event["context"].get("operation_id")
        for event in events
        if event["context"].get("index") == 0
        and event["context"].get("operation_id")
    }
    assert len(a_operations) >= 3
    retry_starts = [
        event for event in events
        if event["event"] == "stage"
        and event["context"].get("index") == 0
        and event["payload"].get("supersedes_operation_id")
    ]
    assert len(retry_starts) == 1

    masked = sorted(
        (_mask_item(event, run_id) for event in events),
        key=lambda item: item["context"]["event_seq"],
    )
    if os.environ.get("GENERATE_V2_FIXTURE") == "1" or not FIXTURE_PATH.exists():
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in masked),
            encoding="utf-8",
        )
    else:
        committed = [
            json.loads(line)
            for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        def key(event: dict[str, Any]) -> tuple[Any, ...]:
            context = event.get("context", {})
            return (
                event.get("event"),
                context.get("index", -1),
                context.get("question_id", ""),
            )

        assert sorted(map(key, masked)) == sorted(map(key, committed))
