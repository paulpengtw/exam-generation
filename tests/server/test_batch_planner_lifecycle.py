"""Planner teardown and recording policy through the real generation HTTP stream."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from server.auth.dependencies import get_config
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.models import GenerationLog
from tests.server.test_generate_body_transport import transport_client  # noqa: F401


class PlannerProvider:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.plan_calls: list[dict[str, Any]] = []
        self.execute_calls: list[dict[str, Any]] = []
        self.fail_planning = False
        self.fail_generation = False

    def stream(self, **kwargs: Any) -> Any:
        self.plan_calls.append(kwargs)
        probe = self

        class Stream:
            def __enter__(self) -> Stream:
                return self

            def __exit__(self, *args: Any) -> None:
                pass

            def __iter__(self) -> Iterator[Any]:
                yield SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="thinking_delta", thinking="planning evidence"),
                )
                assert probe.release.wait(timeout=10), "provider response was not released"
                if probe.fail_planning:
                    raise RuntimeError("fixture planning failure")
                yield SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="text_delta", text='{"briefs": []}'),
                )

            def get_final_message(self) -> Any:
                return SimpleNamespace(usage=SimpleNamespace(input_tokens=5, output_tokens=3))

        return Stream()

    def execute(self, **kwargs: Any) -> Iterator[Any]:
        self.execute_calls.append(kwargs)
        if self.fail_generation:
            raise RuntimeError("fixture generation failure")
        if "## 本小題規劃" in kwargs["messages"][-1]["content"]:
            answer = {"題目": "哪個選項有證據？ A.甲 B.乙", "答案": "A", "答案解析": "甲有紀錄。"}
        else:
            answer = {
                "核心問題": "如何比較證據？", "文本": "甲有紀錄，乙是推測。",
                "subquestions": [{"序號": i, "出題概念": "比較證據"} for i in (1, 2, 3)],
            }
        return iter([SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=json.dumps(answer, ensure_ascii=False)),
        )])])


@pytest.fixture
def planner_case(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    client: TestClient = request.getfixturevalue("transport_client")
    config = client.app.dependency_overrides[get_config]()
    config.creative_planning = True
    config.llm_models_allowed += ("claude-opus-4-6",)
    probe = PlannerProvider()
    monkeypatch.setattr(
        "anthropic.resources.messages.Messages.stream", lambda _self, **kw: probe.stream(**kw),
    )

    def reject_nonstreaming(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("planner must use the observed streaming SDK path")

    monkeypatch.setattr("anthropic.resources.messages.Messages.create", reject_nonstreaming)
    monkeypatch.setattr(
        "openai.resources.chat.completions.Completions.create",
        lambda _self, **kw: probe.execute(**kw),
    )
    payload = json.loads(
        (Path(__file__).parents[1] / "fixtures/transport-social-batch.json").read_text(),
    )
    payload.update(model_plan="claude-opus-4-6", effort_plan="max", stream_version=3)
    try:
        yield client, probe, payload
    finally:
        probe.release.set()


async def recorded_planner(reader: httpx.AsyncClient, log_id: str) -> list[dict[str, Any]]:
    async def read_until_committed() -> list[dict[str, Any]]:
        while True:
            response = await reader.get(f"/api/generation-logs/{log_id}/exchanges")
            assert response.status_code == 200
            if response.json():
                return response.json()
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(read_until_committed(), timeout=5)


def _execute_run(client: TestClient) -> None:
    """Claim and execute one queued run using the transport_client's session factory."""
    from server.generate.run import claim_next_run, execute_run

    sessions = client.app.state.test_async_session_local
    config = client.app.dependency_overrides[get_config]()
    app_state = client.app.state

    async def _run() -> None:
        claimed = await claim_next_run(sessions, host_id="test-host")
        if claimed is not None:
            await execute_run(
                claimed, app_state=app_state, config=config,
                session_factory=sessions, host_id="test-host",
            )

    asyncio.run(_run())


def test_completed_planner_exchange_survives_later_generation_failure(planner_case: Any) -> None:
    client, probe, payload = planner_case
    probe.fail_generation = True
    probe.release.set()
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 202
    log_id = response.json()["run_id"]
    _execute_run(client)
    exchanges = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert exchanges.status_code == 200
    rows = exchanges.json()
    # Exactly 3 rows: planner success (order 1) + 2 generator failures (orders 2-3).
    # sub_question_count=3 but text generators fail before any sub_generators run.
    assert len(rows) == 3, (
        f"expected 3 rows, got {len(rows)}: {[(r['agent'], r['exchange_order']) for r in rows]}"
    )
    assert rows[0]["agent"] == "planner"
    assert rows[0]["exchange_order"] == 1
    assert "error" not in (rows[0]["response_body"] or {}), (
        "planner success row must not have error"
    )
    assert rows[0]["response_body"]["reasoning"] == "planning evidence"
    assert rows[1]["agent"] == "generator"
    assert rows[1]["exchange_order"] == 2
    assert "error" in (rows[1]["response_body"] or {}), (
        "generator failure row must carry response_body['error']"
    )
    assert rows[1]["prompt_tokens"] is None
    assert rows[2]["agent"] == "generator"
    assert rows[2]["exchange_order"] == 3
    assert "error" in (rows[2]["response_body"] or {}), (
        "generator failure row must carry response_body['error']"
    )
    assert rows[2]["prompt_tokens"] is None
    history = client.get("/api/history").json()
    detail = client.get(f"/api/history/{history['items'][0]['id']}").json()
    assert detail["status"] == "failed"
    assert detail["generation_log_id"] == log_id


def test_failed_planner_falls_back_to_generation_without_fabricating_exchange(
    planner_case: Any,
) -> None:
    client, probe, payload = planner_case
    probe.fail_planning = True
    probe.release.set()
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 202
    log_id = response.json()["run_id"]
    _execute_run(client)
    assert probe.plan_calls  # planner was invoked
    exchanges = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert exchanges.status_code == 200
    rows = exchanges.json()
    # Exactly 9 rows: 1 planner failure (order 1) + 2 questions × (1 generator +
    # 3 sub_generator#N) = 8 generation successes (orders 2-9).
    assert len(rows) == 9, (
        f"expected 9 rows, got {len(rows)}: {[(r['agent'], r['exchange_order']) for r in rows]}"
    )
    # Row 0: planner failure recorded via llm_failure event (#945)
    assert rows[0]["agent"] == "planner"
    assert rows[0]["exchange_order"] == 1
    assert "error" in (rows[0]["response_body"] or {}), (
        "planner failure row must carry response_body['error']"
    )
    assert rows[0]["prompt_tokens"] is None
    # Remaining 8 rows: all generation successes (no "error" key)
    gen_rows = rows[1:]
    assert len(gen_rows) == 8
    generator_rows = [r for r in gen_rows if r["agent"] == "generator"]
    subgen_rows = [r for r in gen_rows if r["agent"].startswith("sub_generator")]
    assert len(generator_rows) == 2, f"expected 2 generator rows, got {len(generator_rows)}"
    assert len(subgen_rows) == 6, f"expected 6 sub_generator rows, got {len(subgen_rows)}"
    for r in gen_rows:
        assert "error" not in (r["response_body"] or {}), (
            f"generation row must not have error: agent={r['agent']}"
        )


def test_disabled_recording_keeps_planner_activity_and_results(planner_case: Any) -> None:
    client, probe, payload = planner_case
    client.app.dependency_overrides[get_config]().llm_exchange_retention_days = 0
    probe.release.set()
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 202
    log_id = response.json()["run_id"]
    _execute_run(client)
    assert probe.plan_calls  # planner was invoked despite recording being disabled
    exchanges = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert exchanges.status_code == 200
    assert exchanges.json() == []


def test_skipped_planning_does_not_fabricate_planner_events_or_exchanges(planner_case: Any) -> None:
    client, probe, payload = planner_case
    client.app.dependency_overrides[get_config]().creative_planning = False
    probe.release.set()  # unblock any lingering waits
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 202
    log_id = response.json()["run_id"]
    _execute_run(client)
    assert probe.plan_calls == []
    exchanges = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert exchanges.status_code == 200
    rows = exchanges.json()
    assert rows
    assert all(row["agent"] != "planner" for row in rows)


def test_planner_recording_failure_does_not_interrupt_generation(planner_case: Any) -> None:
    client, probe, payload = planner_case

    async def reject_exchange_writes() -> None:
        async with client.app.state.test_async_session_local() as session:
            await session.execute(text(
                "CREATE TRIGGER reject_exchange BEFORE INSERT ON llm_exchanges "
                "BEGIN SELECT RAISE(FAIL, 'fixture exchange write failure'); END"
            ))
            await session.commit()

    asyncio.run(reject_exchange_writes())
    probe.release.set()
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 202
    log_id = response.json()["run_id"]
    _execute_run(client)
    exchanges = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert exchanges.status_code == 200
    assert exchanges.json() == []
    history = client.get("/api/history").json()
    detail = client.get(f"/api/history/{history['items'][0]['id']}").json()
    assert detail["status"] == "completed"
    assert detail["generation_log_id"] is None


def test_closing_planner_iterator_returns_before_provider_and_preserves_late_exchange(
    planner_case: Any,
) -> None:
    client, probe, payload = planner_case
    config = client.app.dependency_overrides[get_config]()
    user_id = uuid.UUID(client.get("/auth/me").json()["id"])
    log_id = uuid.uuid4()

    async def exercise() -> None:
        async with client.app.state.test_async_session_local() as session:
            session.add(GenerationLog(
                id=log_id, user_id=user_id, params_json=payload, status="started",
            ))
            await session.commit()
        stream = generate_question_stream(
            GenerateParams.model_validate(payload), config, client.app.state,
            generation_log_id=log_id, session_factory=client.app.state.test_async_session_local,
        )
        try:
            while True:
                event = await asyncio.wait_for(anext(stream), timeout=5)
                if event["event"] == "llm_thinking":
                    break
            assert not probe.release.is_set()
            await asyncio.wait_for(stream.aclose(), timeout=2)
            assert probe.execute_calls == []
        finally:
            probe.release.set()
            await stream.aclose()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver",
            headers=client.headers,
        ) as reader:
            rows = await recorded_planner(reader, str(log_id))
            assert [row["agent"] for row in rows] == ["planner"]
            assert rows[0]["response_body"]["reasoning"] == "planning evidence"
        assert probe.execute_calls == []

    asyncio.run(exercise())
