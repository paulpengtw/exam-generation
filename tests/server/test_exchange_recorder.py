from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest

from server.generate.exchange_recorder import ExchangeRecorder


@pytest.fixture
def sink() -> tuple[list[dict[str, Any]], Any]:
    rows: list[dict[str, Any]] = []

    def write(row: dict[str, Any]) -> None:
        rows.append(row)

    return rows, write


def _req(agent: str, purpose: str = "generate") -> dict:
    return {
        "type": "llm_request",
        "agent": agent,
        "purpose": purpose,
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ],
        "params": {"max_tokens": 8192, "temperature": 0.7},
    }


def _resp(agent: str, purpose: str = "generate") -> dict:
    return {
        "type": "llm_response",
        "agent": agent,
        "purpose": purpose,
        "model": "claude-sonnet-4-6",
        "content": "ok",
        "reasoning": None,
        "usage": {"input": 12, "output": 3, "cache_read": 0, "cache_creation": 0},
    }


def test_request_response_pair_produces_one_row(sink):
    rows, write = sink
    log_id = uuid.uuid4()
    rec = ExchangeRecorder(log_id, write)

    rec(_req("generator"))
    assert rows == []  # no row until response arrives
    rec(_resp("generator"))

    assert len(rows) == 1
    row = rows[0]
    assert row["generation_log_id"] == log_id
    assert row["exchange_order"] == 1
    assert row["agent"] == "generator"
    assert row["purpose"] == "generate"
    assert row["model_used"] == "claude-sonnet-4-6"
    assert row["prompt_tokens"] == 12
    assert row["completion_tokens"] == 3
    assert row["request_body"]["messages"][1]["content"] == "hello"
    assert row["response_body"]["content"] == "ok"


def test_order_counter_increments_and_is_stable(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)

    rec(_req("generator"))
    rec(_resp("generator"))
    rec(_req("verifier", purpose="verify"))
    rec(_resp("verifier", purpose="verify"))

    assert [r["exchange_order"] for r in rows] == [1, 2]
    assert [r["agent"] for r in rows] == ["generator", "verifier"]


def test_parallel_agents_are_matched_by_agent_id(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)

    # Interleaved events from three parallel sub-generators.
    rec(_req("sub_generator#1"))
    rec(_req("sub_generator#2"))
    rec(_req("sub_generator#3"))
    rec(_resp("sub_generator#2"))
    rec(_resp("sub_generator#1"))
    rec(_resp("sub_generator#3"))

    agents = {r["agent"] for r in rows}
    assert agents == {"sub_generator#1", "sub_generator#2", "sub_generator#3"}
    assert len(rows) == 3
    orders = sorted(r["exchange_order"] for r in rows)
    assert orders == [1, 2, 3]


def test_response_without_request_writes_null_request(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)

    rec(_resp("verifier", purpose="verify"))

    assert len(rows) == 1
    assert rows[0]["request_body"] is None
    assert rows[0]["response_body"]["content"] == "ok"
    assert rows[0]["agent"] == "verifier"
    assert rows[0]["purpose"] == "verify"


def test_write_failures_are_swallowed_and_logged(sink, caplog):
    def boom(_row):
        raise RuntimeError("db down")

    rec = ExchangeRecorder(uuid.uuid4(), boom)
    with caplog.at_level("WARNING"):
        rec(_req("generator"))
        rec(_resp("generator"))
    assert any("ExchangeRecorder" in r.getMessage() for r in caplog.records)


def test_thread_safety_under_concurrent_events(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)

    def hammer(agent: str) -> None:
        for _ in range(50):
            rec(_req(agent))
            rec(_resp(agent))

    threads = [
        threading.Thread(target=hammer, args=(f"sub_generator#{i}",))
        for i in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(rows) == 4 * 50
    orders = sorted(r["exchange_order"] for r in rows)
    assert orders == list(range(1, 4 * 50 + 1))


def test_non_llm_events_are_ignored(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)
    rec({"type": "stage", "agent": "generator", "stage": "llm_generate", "status": "start"})
    rec({"type": "llm_content_delta", "agent": "generator", "text": "hi"})
    assert rows == []
