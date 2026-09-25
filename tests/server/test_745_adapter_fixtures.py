"""Real-publisher fixed-slot fixtures for the NS and grouped-math adapters (#745)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

FIXTURE_PATHS = {
    "natural_sciences": (
        Path(__file__).parent.parent
        / "fixtures"
        / "generation_v2"
        / "natural_sciences_groups_interleaved.jsonl"
    ),
    "math": (
        Path(__file__).parent.parent
        / "fixtures"
        / "generation_v2"
        / "math_groups_interleaved.jsonl"
    ),
}


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


def _mask_item(
    item: dict[str, Any],
    run_id: str,
    *,
    operation_names: dict[str, str] | None = None,
    call_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Mask run/timestamp/opaque operation identities for a stable fixture."""
    raw = json.dumps(item, ensure_ascii=False).replace(run_id, "RUN")
    raw = re.sub(r'"ts":\s*\d+(?:\.\d+)?', '"ts": 0.0', raw)
    raw = re.sub(r'"generation_log_id":\s*"[^"]*"', '"generation_log_id": "LOG"', raw)
    raw = re.sub(
        r'"[^"\n]*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^"\n]*"',
        '"TS"',
        raw,
    )
    operation_names = operation_names if operation_names is not None else {}
    call_names = call_names if call_names is not None else {}

    def mask_operation(match: re.Match[str]) -> str:
        value = match.group(0)
        operation_names.setdefault(value, f"RUN:operation:OP{len(operation_names) + 1}")
        return operation_names[value]

    def mask_call(match: re.Match[str]) -> str:
        value = match.group(0)
        call_names.setdefault(value, f"RUN:call:CALL{len(call_names) + 1}")
        return call_names[value]

    raw = re.sub(r"RUN:operation:[0-9a-f]+", mask_operation, raw)
    raw = re.sub(r"RUN:call:[0-9a-f]+", mask_call, raw)
    return json.loads(raw)


def _subquestion(subject: str, qid: str, slot: int, label: str, params: Any) -> Any:
    if subject == "natural_sciences":
        from src.natural_sciences.schemas import LearningContentRef, SubQuestion

        cfg = params.subquestion_configs[slot - 1]
        sub = SubQuestion(
            id=f"{qid}-sq{slot:03d}",
            序號=slot,
            年級=8,
            科目=["自然科學"],
            科學能力=list(params.科學能力),
            學習內容=[LearningContentRef(編碼=code, 說明="") for code in cfg.learning_content],
            學習表現=[LearningContentRef(編碼=code, 說明="") for code in cfg.learning_performance],
            reporting_scale=cfg.reporting_scale,
            題型=params.題型,
            題目=f"{label} 小題 {slot}",
            答案="A",
            答案解析="解析",
        )
    else:
        from src.schemas import SubQuestion

        sub = SubQuestion(
            id=f"{qid}-sq{slot:03d}",
            序號=slot,
            年級=8,
            題型=params.題型,
            題目=f"{label} 小題 {slot}",
            答案="A",
            答案解析="解析",
            學習內容=list(params.學習內容),
            學習表現=list(params.學習表現),
        )
    sub._plan_index = slot
    return sub


def _shell(subject: str, qid: str, label: str, params: Any) -> Any:
    if subject == "natural_sciences":
        from src.natural_sciences.schemas import ExamQuestion

        return ExamQuestion(
            id=qid,
            核心問題=f"核心問題 {label}",
            文本=f"文本 {label}",
            取材來源=[f"來源 {label}"],
            情境=list(params.情境),
            情境子類別=params.情境子類別,
            題型種類=params.題型種類,
            題型=params.題型,
            科學能力=list(params.科學能力),
            題目內容類型=params.題目內容類型,
        )

    from src.schemas import ExamQuestion

    return ExamQuestion(
        id=qid,
        核心問題=f"核心問題 {label}",
        文本=f"文本 {label}",
        取材來源=[f"來源 {label}"],
        情境=list(params.情境),
        題型種類=params.題型種類,
        題型=params.題型,
        數學思考=list(params.數學思考),
        學習內容=list(params.學習內容),
        學習表現=list(params.學習表現),
        題目內容類型=params.題目內容類型,
        題目=[],
        正確解題分析=[],
    )


def _run_stream(subject: str, tmp_path: Path) -> tuple[list[dict[str, Any]], str]:
    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from src.common.generation_events import new_call_scope, new_operation_scope
    from tests.server.generate_test_utils import publisher_enqueue_gate, resolved_generate_params

    params = resolved_generate_params({
        "subject": subject,
        "seed": 745,
        "count": 3,
        "sub_question_count": 3,
        "skip_verify": True,
    })
    b_done = threading.Event()

    def fake_do_generate(rng_params: Any, _overrides: Any, **kwargs: Any) -> Any:
        qid = kwargs["question_id"]
        client: _FakeClient = kwargs["client"]
        on_update = kwargs["on_question_update"]
        context = kwargs["question_context"]
        label = ("A", "B", "C")[context.index]

        def stage(scope: Any, status: str, *, supersedes: str | None = None) -> None:
            agent = (
                f"sub_generator#{scope.subquestion_index + 1}"
                if scope.kind == "subquestion" and scope.subquestion_index is not None
                else "generator"
            )
            event = {
                "type": "stage",
                "agent": agent,
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

        def call(scope: Any, *, retry_of: str | None = None) -> Any:
            call_scope = new_call_scope(scope, retry_of_call_id=retry_of)
            base = {
                "run_id": call_scope.run_id,
                "operation_id": call_scope.operation_id,
                "call_id": call_scope.call_id,
                "agent": (
                    f"sub_generator#{scope.subquestion_index + 1}"
                    if scope.kind == "subquestion" and scope.subquestion_index is not None
                    else "generator"
                ),
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

        shell = _shell(subject, qid, label, rng_params)
        on_update(shell, "draft")

        if context.index == 1:
            for slot in (1, 2, 3):
                shell.subquestions.append(_subquestion(subject, qid, slot, label, rng_params))
                on_update(shell, "draft")
        elif context.index == 0:
            shell.subquestions.append(_subquestion(subject, qid, 1, label, rng_params))
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
            shell.subquestions.append(_subquestion(subject, qid, 3, label, rng_params))
            on_update(shell, "draft")
            # A waits until B's result has entered the stream queue.
            assert b_done.wait(timeout=10)
        else:
            # C demonstrates that the text shell remains final when every
            # announced subquestion attempt fails.
            for slot in (1, 2, 3):
                failed_scope = new_operation_scope(
                    context,
                    kind="subquestion",
                    subquestion_index=slot - 1,
                )
                stage(failed_scope, "start")
                call(failed_scope)
                stage(failed_scope, "error")

        return shell

    spec = dataclasses.replace(SUBJECTS[subject], do_generate=fake_do_generate)
    config = ServerConfig(
        api_key="x",
        gemini_api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    app_state = type(
        "AppState",
        (),
        {
            "renderer_pool": None,
            "curriculum": [],
            "performance": {},
            "intro_text": "",
            "grade_content": {},
            "math_curriculum_context": None,
        },
    )()

    async def collect() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in generate_question_stream(
            params,
            config,
            app_state,
            subjects={subject: spec},
            client_factory=_FakeClient,
        ):
            events.append(event)
        return events

    with (
        patch("server.observability.record_generation_outcome"),
        publisher_enqueue_gate(b_done, question_index=1),
    ):
        events = asyncio.run(collect())
    return events, events[0]["context"]["run_id"]


def _event_key(event: dict[str, Any]) -> tuple[Any, ...]:
    context = event.get("context", {})
    return (
        event.get("event"),
        context.get("index", -1),
        context.get("question_id", ""),
        context.get("subquestion_index", -1),
        event.get("payload", {}).get("event_name", ""),
    )


@pytest.mark.parametrize("subject", ["natural_sciences", "math"])
def test_fixed_adapter_fixture_and_terminal(subject: str, tmp_path: Path) -> None:
    from server.generate.event_protocol import QuestionTerminalPayload

    events, run_id = _run_stream(subject, tmp_path)
    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "done"
    assert [event["context"]["event_seq"] for event in events] == list(
        range(1, len(events) + 1)
    )

    plans = [event for event in events if event["event"] == "plan"]
    assert len(plans) == 3
    for plan in plans:
        assert plan["payload"]["slots"] == [
            {
                "subquestion_index": index,
                "id": f'{plan["context"]["question_id"]}-sq{index + 1:03d}',
                "序號": index + 1,
            }
            for index in range(3)
        ]

    announced_by_question = {
        plan["context"]["question_id"]: {
            slot["subquestion_index"]: slot for slot in plan["payload"]["slots"]
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
        if agent.startswith("sub_generator#"):
            announced_index = int(agent.rsplit("#", 1)[1]) - 1
            assert subquestion_index == question_slots[announced_index]["subquestion_index"]
        operation_id = context["operation_id"]
        assert operation_slots.setdefault(operation_id, subquestion_index) == subquestion_index

    result_a = next(
        event for event in events
        if event["event"] == "result" and event["context"]["index"] == 0
    )
    result_b = next(
        event for event in events
        if event["event"] == "result" and event["context"]["index"] == 1
    )
    result_c = next(
        event for event in events
        if event["event"] == "result" and event["context"]["index"] == 2
    )
    assert result_b["context"]["event_seq"] < result_a["context"]["event_seq"]
    assert [sub["id"] for sub in result_a["payload"]["subquestions"]] == [
        f'{result_a["context"]["question_id"]}-sq001',
        f'{result_a["context"]["question_id"]}-sq003',
    ]
    assert [sub["序號"] for sub in result_b["payload"]["subquestions"]] == [1, 2, 3]
    assert result_c["payload"]["文本"] == "文本 C"
    assert result_c["payload"].get("subquestions", []) == []
    for result in (result_a, result_b, result_c):
        serialized = json.dumps(result["payload"], ensure_ascii=False)
        assert "operation_id" not in serialized
        assert "call_id" not in serialized

    updates_a = [
        event for event in events
        if event["event"] == "question_update" and event["context"]["index"] == 0
    ]
    updates_b = [
        event for event in events
        if event["event"] == "question_update" and event["context"]["index"] == 1
    ]
    updates_c = [
        event for event in events
        if event["event"] == "question_update" and event["context"]["index"] == 2
    ]
    assert [event["context"]["content_revision"] for event in updates_a] == [1, 2, 3]
    assert [
        len(event["payload"]["question"].get("subquestions", []))
        for event in updates_a
    ] == [0, 1, 2]
    assert [event["context"]["content_revision"] for event in updates_b] == [1, 2, 3, 4]
    assert [event["context"]["content_revision"] for event in updates_c] == [1]

    terminals = {
        event["context"]["index"]: event
        for event in events
        if event["event"] == "question_terminal"
    }
    assert len(terminals) == 3
    for terminal in terminals.values():
        QuestionTerminalPayload.model_validate(terminal["payload"])
    assert terminals[0]["payload"]["delivery_status"] == "partial"
    assert terminals[0]["payload"]["missing"][0]["subquestion_id"].endswith("-sq002")
    assert terminals[1]["payload"]["delivery_status"] == "complete"
    assert terminals[2]["payload"]["delivery_status"] == "partial"
    assert [
        slot["subquestion_id"] for slot in terminals[2]["payload"]["missing"]
    ] == [
        f'{result_c["context"]["question_id"]}-sq001',
        f'{result_c["context"]["question_id"]}-sq002',
        f'{result_c["context"]["question_id"]}-sq003',
    ]

    retry_starts = [
        event for event in events
        if event["event"] == "stage"
        and event["context"].get("index") == 0
        and event["payload"].get("supersedes_operation_id")
    ]
    assert len(retry_starts) == 1
    assert any(
        event["event"] == "llm_request"
        and event["context"].get("index") == 0
        and event["payload"].get("retry_of_call_id")
        for event in events
    )

    fixture_path = FIXTURE_PATHS[subject]
    operation_names: dict[str, str] = {}
    call_names: dict[str, str] = {}
    masked = [
        _mask_item(
            event,
            run_id,
            operation_names=operation_names,
            call_names=call_names,
        )
        for event in sorted(events, key=lambda item: item["context"]["event_seq"])
    ]
    if os.environ.get("GENERATE_V2_FIXTURE") == "1" or not fixture_path.exists():
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in masked),
            encoding="utf-8",
        )
    else:
        committed = [
            json.loads(line)
            for line in fixture_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert sorted(map(_event_key, masked)) == sorted(map(_event_key, committed))


@pytest.mark.parametrize("subject", ["natural_sciences", "math"])
def test_fixed_adapter_resend_allocates_new_question_ids(subject: str, tmp_path: Path) -> None:
    first, _ = _run_stream(subject, tmp_path / "first")
    second, _ = _run_stream(subject, tmp_path / "second")
    first_ids = [
        item["question_id"] for item in first[0]["payload"]["questions"]
    ]
    second_ids = [
        item["question_id"] for item in second[0]["payload"]["questions"]
    ]
    assert first_ids != second_ids
    assert [item.rsplit("_", 1)[-1] for item in first_ids] == ["001", "002", "003"]
    assert [item.rsplit("_", 1)[-1] for item in second_ids] == ["001", "002", "003"]
