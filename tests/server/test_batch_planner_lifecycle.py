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
from server.generate import routes as generate_routes
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.models import GenerationLog
from tests.server.test_generate_body_transport import transport_client  # noqa: F401
from tests.server.test_generation_log_discovery import live_generation, stream_events


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
    payload.update(model_plan="claude-opus-4-6", effort_plan="max")
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


def test_disconnect_during_planning_returns_before_provider_and_preserves_late_exchange(
    planner_case: Any,
) -> None:
    client, probe, payload = planner_case

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver",
            headers=client.headers,
        ) as reader:
            before_tasks = asyncio.all_tasks()
            async with live_generation(client, payload) as (events, disconnect, task):
                try:
                    _, started = await asyncio.wait_for(events.get(), timeout=5)
                    log_id = started["generation_log_id"]
                    while True:
                        name, data = await asyncio.wait_for(events.get(), timeout=5)
                        if name == "llm_thinking":
                            assert data["agent"] == "planner"
                            break
                    assert not probe.release.is_set()
                    disconnect.set()
                    await asyncio.wait_for(asyncio.shield(task), timeout=2)
                    assert probe.execute_calls == []
                finally:
                    probe.release.set()
            rows = await recorded_planner(reader, log_id)
            assert [row["agent"] for row in rows] == ["planner"]
            assert rows[0]["response_body"]["reasoning"] == "planning evidence"
            history = (await reader.get("/api/history")).json()
            detail = (await reader.get(f"/api/history/{history['items'][0]['id']}")).json()
            assert detail["status"] == "aborted"
            assert detail["generation_log_id"] == log_id
            # sse-starlette starts one application-lifetime shutdown watcher.
            # Everything else created by this request must finish on closure.
            pending = {
                task for task in asyncio.all_tasks() - before_tasks
                if task.get_coro().__qualname__ != "_shutdown_watcher"
            }
            if pending:
                await asyncio.wait_for(asyncio.gather(*pending), timeout=2)
            assert probe.execute_calls == []

    asyncio.run(exercise())


def test_completed_planner_exchange_survives_later_generation_failure(planner_case: Any) -> None:
    client, probe, payload = planner_case
    probe.fail_generation = True
    probe.release.set()
    events = stream_events(client.post("/api/generate", json=payload))
    assert any(name == "error" for name, _ in events)
    assert not any(name == "result" for name, _ in events)
    log_id = events[0][1]["generation_log_id"]
    response = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert response.status_code == 200
    rows = response.json()
    assert [row["agent"] for row in rows] == ["planner"]
    assert rows[0]["response_body"]["reasoning"] == "planning evidence"
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
    events = stream_events(client.post("/api/generate", json=payload))
    assert any(name == "result" for name, _ in events)
    assert not any(name == "error" for name, _ in events)
    assert any(name == "llm_thinking" and data["agent"] == "planner" for name, data in events)
    log_id = events[0][1]["generation_log_id"]
    response = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert all(row["agent"] != "planner" for row in rows)
    assert any(row["agent"] == "generator" for row in rows)


def test_disabled_recording_keeps_planner_activity_and_results(planner_case: Any) -> None:
    client, probe, payload = planner_case
    client.app.dependency_overrides[get_config]().llm_exchange_retention_days = 0
    probe.release.set()
    events = stream_events(client.post("/api/generate", json=payload))
    assert any(name == "result" for name, _ in events)
    assert not any(name == "error" for name, _ in events)
    assert any(name == "llm_thinking" and data["agent"] == "planner" for name, data in events)
    log_id = events[0][1]["generation_log_id"]
    response = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert response.status_code == 200
    assert response.json() == []


def test_skipped_planning_does_not_fabricate_planner_events_or_exchanges(planner_case: Any) -> None:
    client, probe, payload = planner_case
    client.app.dependency_overrides[get_config]().creative_planning = False
    events = stream_events(client.post("/api/generate", json=payload))
    assert any(name == "result" for name, _ in events)
    assert not any(name == "error" for name, _ in events)
    assert probe.plan_calls == []
    assert not any(
        name.startswith("llm_") and data["agent"] == "planner" for name, data in events
    )
    log_id = events[0][1]["generation_log_id"]
    response = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert all(row["agent"] != "planner" for row in rows)


def test_planner_recording_failure_does_not_interrupt_generation(planner_case: Any) -> None:
    client, probe, payload = planner_case

    async def reject_exchange_writes() -> None:
        async with generate_routes.AsyncSessionLocal() as session:
            await session.execute(text(
                "CREATE TRIGGER reject_exchange BEFORE INSERT ON llm_exchanges "
                "BEGIN SELECT RAISE(FAIL, 'fixture exchange write failure'); END"
            ))
            await session.commit()

    asyncio.run(reject_exchange_writes())
    probe.release.set()
    events = stream_events(client.post("/api/generate", json=payload))
    assert any(name == "result" for name, _ in events)
    assert not any(name == "error" for name, _ in events)
    assert any(name == "llm_response" and data["agent"] == "planner" for name, data in events)
    log_id = events[0][1]["generation_log_id"]
    response = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert response.status_code == 200
    assert response.json() == []
    history = client.get("/api/history").json()
    detail = client.get(f"/api/history/{history['items'][0]['id']}").json()
    assert detail["status"] == "completed"
    assert detail["generation_log_id"] == log_id


def test_closing_planner_iterator_returns_before_provider_and_preserves_late_exchange(
    planner_case: Any,
) -> None:
    client, probe, payload = planner_case
    config = client.app.dependency_overrides[get_config]()
    user_id = uuid.UUID(client.get("/auth/me").json()["id"])
    log_id = uuid.uuid4()

    async def exercise() -> None:
        async with generate_routes.AsyncSessionLocal() as session:
            session.add(GenerationLog(
                id=log_id, user_id=user_id, params_json=payload, status="started",
            ))
            await session.commit()
        stream = generate_question_stream(
            GenerateParams.model_validate(payload), config, client.app.state,
            generation_log_id=log_id, session_factory=generate_routes.AsyncSessionLocal,
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
