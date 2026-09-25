"""Real-publisher A/B/C/D evidence fixture for issue #747."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from server.config import ServerConfig
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from src.schemas import ExamQuestion, ImageSpec
from tests.server.generate_test_utils import resolved_generate_params

FIXTURE = Path(__file__).parents[1] / "fixtures" / "generation_v2" / "math_abcd_transport.jsonl"


class _FakeClient:
    def __init__(self, _config: Any) -> None:
        self._observer = None

    def set_observer(self, observer: Any) -> None:
        self._observer = observer

    def clear_observer(self) -> None:
        self._observer = None


def _question(qid: str, text: str, *, chart: bool = False) -> ExamQuestion:
    return ExamQuestion(
        id=qid,
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[{"編碼": "A-7-7", "說明": "fixture"}],
        題目=[text],
        正確解題分析=["fixture answer"],
        學習表現=[{"編碼": "s-IV-12", "說明": "fixture"}],
        chart_spec=ImageSpec(description="fixture chart") if chart else None,
    )


def _normalize(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    started = events[0]
    actual_run_id = started["context"]["run_id"]
    question_ids = {
        question["question_id"]: f"q_RUN_{question['index'] + 1:03d}"
        for question in started["payload"]["questions"]
    }

    def replace(value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {name: replace(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [replace(item, key) for item in value]
        if key == "run_id" and value == actual_run_id:
            return "RUN"
        if key in {"question_id", "subquestion_id", "id"} and value in question_ids:
            return question_ids[value]
        if key == "operation_id" and isinstance(value, str):
            return "RUN:operation:planner"
        if key == "call_id" and isinstance(value, str):
            return "RUN:call:planner"
        if isinstance(value, str) and actual_run_id in value:
            return value.replace(actual_run_id, "RUN")
        if key == "ts":
            return 0.0
        return value

    return [replace(event) for event in events]


def test_real_publisher_fixture_captures_transport_omitted_terminal(tmp_path: Path) -> None:
    def do_generate(rng_params: Any, _overrides: Any, **kwargs: Any) -> ExamQuestion:
        qid = kwargs["question_id"]
        index = int(qid.rsplit("_", 1)[-1])
        q = _question(qid, f"question {index}", chart=index == 2)
        if index == 3:
            kwargs["on_question_update"](q, "draft")
            raise RuntimeError("C final generation failed")
        return q

    fake_spec = dataclasses.replace(SUBJECTS["math"], do_generate=do_generate)
    params = resolved_generate_params({
        "subject": "math",
        "count": 4,
        "skip_verify": True,
        "style": ["text_only"],
    })
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    server_events: list[dict[str, Any]] = []

    async def collect() -> None:
        async for event in generate_question_stream(
            params,
            config,
            MagicMock(renderer_pool=None),
            subjects={"math": fake_spec},
            client_factory=_FakeClient,
        ):
            server_events.append(event)

    asyncio.run(collect())

    d_id = next(
        question["question_id"]
        for question in server_events[0]["payload"]["questions"]
        if question["index"] == 3
    )
    assert any(
        event["event"] == "question_terminal"
        and event["context"].get("question_id") == d_id
        for event in server_events
    ), "the server must publish D's terminal before the transport adapter removes it"

    transport_events = [
        event for event in server_events
        if not (
            event["event"] == "question_terminal"
            and event["context"].get("question_id") == d_id
        )
    ]
    normalized = _normalize(transport_events)
    if os.environ.get("GENERATE_747_FIXTURE") == "1":
        FIXTURE.write_text(
            "".join(
                json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
                for event in normalized
            ),
            encoding="utf-8",
        )
    else:
        assert FIXTURE.exists(), "fixture must be generated with GENERATE_747_FIXTURE=1"

    terminal_by_index = {
        event["context"]["index"]: event["payload"]
        for event in transport_events
        if event["event"] == "question_terminal"
    }
    assert set(terminal_by_index) == {0, 1, 2}
    assert terminal_by_index[0]["delivery_status"] == "complete"
    assert terminal_by_index[1]["delivery_status"] == "partial"
    assert terminal_by_index[2]["delivery_status"] == "none"
    assert any(
        event["event"] == "question_update" and event["context"].get("index") == 2
        for event in transport_events
    ), "C's draft must survive its failed final generation"
    assert any(
        event["event"] == "result" and event["context"].get("index") == 3
        for event in transport_events
    ), "D's final content must survive the terminal omission"
