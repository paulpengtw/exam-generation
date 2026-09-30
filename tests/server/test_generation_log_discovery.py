"""Generation-log discovery through generation, History and authenticated readback."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from server.app import prune_expired_llm_exchanges
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.db import get_async_session
from server.generate import routes as generate_routes
from server.models import GenerationLog, GenerationRecord, LLMExchange, User
from src.data_loader import (
    get_grade_content,
    load_curriculum,
    load_intro_text,
    load_performance_standards,
)
from tests.server.generate_test_utils import complete_math_query_params
from tests.server.test_generate_body_transport import transport_client  # noqa: F401

SSEEvent = tuple[str, dict[str, Any]]
LiveStream = tuple[asyncio.Queue[SSEEvent], asyncio.Event, asyncio.Task[None]]


def question_response(_self: Any, **kwargs: Any) -> Iterator[Any]:
    """Only the external SDK is replaced; the generation pipeline remains real."""
    content = json.dumps({
        "題目": ["1 + 1 = ?", "A. 2", "B. 3"],
        "正確解題分析": ["1 + 1 = 2，答案為 A。"],
    }, ensure_ascii=False)
    return iter([SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=content),
    )])])


def stream_events(response: Any) -> list[SSEEvent]:
    events = []
    for frame in response.text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(":", 1) for line in frame.splitlines() if ":" in line)
        if "event" in fields:
            data = json.loads(fields.get("data", "").strip() or "{}")
            events.append((fields["event"].strip(), data))
    return events


@pytest.fixture
def math_client(request: pytest.FixtureRequest) -> TestClient:
    client = request.getfixturevalue("transport_client")
    state = client.app.state
    state.curriculum = load_curriculum(Path("data/curriculum/學習內容.json"))
    state.performance = load_performance_standards(Path("data/curriculum/學習表現.json"))
    state.intro_text = load_intro_text(Path('Introduction to "學習表現" and "學習階段".md'))
    state.grade_content = {grade: get_grade_content(state.curriculum, grade) for grade in (7, 8, 9)}
    return client


@asynccontextmanager
async def live_generation(
    client: TestClient, payload: dict[str, Any], method: str = "POST",
) -> AsyncIterator[LiveStream]:
    """Drive the real ASGI request without buffering its streaming response."""
    events: asyncio.Queue[SSEEvent] = asyncio.Queue()
    disconnected = asyncio.Event()
    request_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": json.dumps(payload).encode()
                    if method == "POST" else b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            assert message["status"] == 200
        elif message["type"] == "http.response.body":
            response = SimpleNamespace(text=message.get("body", b"").decode())
            for event in stream_events(response):
                events.put_nowait(event)

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1", "method": method, "scheme": "http",
        "path": "/api/generate", "raw_path": b"/api/generate", "root_path": "",
        "query_string": urlencode(payload, doseq=True).encode() if method == "GET" else b"",
        "headers": [(b"content-type", b"application/json"),
                    (b"authorization", client.headers["Authorization"].encode())],
        "client": ("127.0.0.1", 12345), "server": ("testserver", 80),
    }
    task = asyncio.create_task(client.app(scope, receive, send))
    try:
        yield events, disconnected, task
    finally:
        disconnected.set()
        await asyncio.wait_for(task, timeout=10)


def test_started_and_history_advertise_the_same_readable_generation_log(
    math_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openai.resources.chat.completions.Completions.create", question_response)
    response = math_client.post(
        "/api/generate", json=complete_math_query_params(skip_verify=True),
    )
    assert response.status_code == 200
    events = stream_events(response)
    assert events[0][0] == "started"
    log_id = events[0][1]["payload"]["generation_log_id"]
    assert str(uuid.UUID(log_id)) == log_id
    assert any(name == "result" for name, _ in events), events

    history = math_client.get("/api/history").json()
    detail = math_client.get(f"/api/history/{history['items'][0]['id']}").json()
    assert detail["generation_log_id"] == log_id
    exchanges = math_client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert exchanges.status_code == 200
    assert [(row["agent"], row["exchange_order"]) for row in exchanges.json()] == [("generator", 1)]


@pytest.mark.parametrize("method", ["POST", "GET"])
def test_advertised_log_is_readable_before_results_and_survives_disconnect(
    math_client: TestClient, monkeypatch: pytest.MonkeyPatch, method: str,
) -> None:
    release = threading.Event()
    calls = []

    def provider_response(_self: Any, **kwargs: Any) -> Iterator[Any]:
        calls.append(kwargs)
        if len(calls) == 1:
            return question_response(_self, **kwargs)
        assert release.wait(timeout=10), "test did not release verification response"
        content = json.dumps({"passed": True, "answer_match": True, "details": "correct",
                              "my_answer": "A", "provided_answer": "A"})
        return iter([SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=content),
        )])])

    monkeypatch.setattr("openai.resources.chat.completions.Completions.create", provider_response)

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=math_client.app), base_url="http://testserver",
            headers={"Authorization": math_client.headers["Authorization"]},
        ) as reader:
            async with live_generation(
                math_client, complete_math_query_params(model_verify="gpt-4.1"), method,
            ) as (events, disconnected, task):
                try:
                    name, started = await asyncio.wait_for(events.get(), timeout=5)
                    assert name == "started"
                    log_id = started["payload"]["generation_log_id"]
                    seen = []
                    while True:
                        name, data = await asyncio.wait_for(events.get(), timeout=5)
                        seen.append(name)
                        agent = data.get("payload", data).get("agent")
                        if name == "llm_request" and agent == "verifier":
                            break
                    assert "result" not in seen
                    assert not release.is_set()
                    assert (await reader.get("/api/history")).json()["total"] == 0
                    before = await reader.get(f"/api/generation-logs/{log_id}/exchanges")
                    assert before.status_code == 200
                    assert [row["agent"] for row in before.json()] == ["generator"]
                    disconnected.set()
                finally:
                    release.set()
                await asyncio.wait_for(task, timeout=10)

            after = await reader.get(f"/api/generation-logs/{log_id}/exchanges")
            assert after.json()[0] == before.json()[0]
            history = (await reader.get("/api/history")).json()
            details = [(await reader.get(f"/api/history/{item['id']}")).json()
                       for item in history["items"]]
            assert details and all(detail["generation_log_id"] == log_id for detail in details)
            assert any(detail["status"] == "aborted" for detail in details)

    asyncio.run(exercise())


def test_log_is_advertised_before_the_first_provider_response(
    math_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()

    def held_response(_self: Any, **kwargs: Any) -> Iterator[Any]:
        assert release.wait(timeout=10), "test did not release generation response"
        return question_response(_self, **kwargs)

    monkeypatch.setattr("openai.resources.chat.completions.Completions.create", held_response)

    async def exercise() -> None:
        async with live_generation(
            math_client, complete_math_query_params(skip_verify=True),
        ) as (events, _disconnected, _task):
            try:
                name, started = await asyncio.wait_for(events.get(), timeout=5)
                assert name == "started"
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=math_client.app),
                    base_url="http://testserver", headers=math_client.headers,
                ) as reader:
                    response = await reader.get(
                        f"/api/generation-logs/{started['payload']['generation_log_id']}/exchanges",
                    )
                    assert response.status_code == 200
                    assert response.json() == []
                    assert not release.is_set()
            finally:
                release.set()

    asyncio.run(exercise())


def test_failed_generation_keeps_its_advertised_log_and_completed_exchange(
    math_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def failing_verification(_self: Any, **kwargs: Any) -> Iterator[Any]:
        calls.append(kwargs)
        if len(calls) == 1:
            return question_response(_self, **kwargs)
        raise RuntimeError("fixture verification failure")

    monkeypatch.setattr(
        "openai.resources.chat.completions.Completions.create", failing_verification,
    )
    response = math_client.post(
        "/api/generate", json=complete_math_query_params(model_verify="gpt-4.1"),
    )
    events = stream_events(response)
    log_id = events[0][1]["payload"]["generation_log_id"]
    assert "error" in [name for name, _ in events]
    history = math_client.get("/api/history").json()
    detail = math_client.get(f"/api/history/{history['items'][0]['id']}").json()
    assert detail["status"] == "failed"
    assert detail["generation_log_id"] == log_id
    exchanges = math_client.get(f"/api/generation-logs/{log_id}/exchanges").json()
    # The generator exchange must be present; verifier or other failure rows
    # may also appear (verifier failure now captured as llm_failure exchange).
    assert any(row["agent"] == "generator" for row in exchanges)


@pytest.mark.parametrize("status", ["completed", "failed", "aborted"])
def test_legacy_history_without_linked_log_is_readable_with_null_id(
    math_client: TestClient, status: str,
) -> None:
    user_id = uuid.UUID(math_client.get("/auth/me").json()["id"])
    record_id = uuid.uuid4()

    async def seed() -> None:
        async for session in math_client.app.dependency_overrides[get_async_session]():
            session.add(GenerationRecord(
                id=record_id, user_id=user_id, subject="math", question_id="legacy",
                status=status, params_json={}, question_json={"id": "legacy"},
            ))
            await session.commit()

    asyncio.run(seed())
    response = math_client.get(f"/api/history/{record_id}")
    assert response.status_code == 200
    assert response.json()["generation_log_id"] is None
    assert response.json()["status"] == status


def test_advertising_log_id_preserves_authentication_and_existence_hiding(
    math_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openai.resources.chat.completions.Completions.create", question_response)
    response = math_client.post(
        "/api/generate", json=complete_math_query_params(skip_verify=True),
    )
    log_id = stream_events(response)[0][1]["payload"]["generation_log_id"]
    other_id = uuid.uuid4()

    async def seed() -> None:
        async for session in math_client.app.dependency_overrides[get_async_session]():
            session.add(User(id=other_id, email="other-log-reader@example.com"))
            await session.commit()

    asyncio.run(seed())
    config = math_client.app.dependency_overrides[get_config]()
    other_token = create_jwt(other_id, "other-log-reader@example.com", config=config)
    headers = {"Authorization": f"Bearer {other_token}"}
    url = f"/api/generation-logs/{log_id}/exchanges"
    assert math_client.get(url, headers={"Authorization": ""}).status_code == 401
    hidden = math_client.get(url, headers=headers)
    missing = math_client.get(f"/api/generation-logs/{uuid.uuid4()}/exchanges", headers=headers)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_history_advertises_the_log_of_the_returned_latest_version(
    math_client: TestClient,
) -> None:
    user_id = uuid.UUID(math_client.get("/auth/me").json()["id"])
    parent_id, child_id, parent_log_id, child_log_id = [uuid.uuid4() for _ in range(4)]

    async def seed() -> None:
        async for session in math_client.app.dependency_overrides[get_async_session]():
            for log_id in (parent_log_id, child_log_id):
                session.add(GenerationLog(id=log_id, user_id=user_id, params_json={}))
            session.add(GenerationRecord(
                id=parent_id, user_id=user_id, subject="math", question_id="parent",
                generation_log_id=parent_log_id, params_json={}, question_json={"id": "parent"},
            ))
            await session.flush()
            session.add(GenerationRecord(
                id=child_id, user_id=user_id, subject="math", question_id="child",
                parent_record_id=parent_id, generation_log_id=child_log_id,
                params_json={}, question_json={"id": "child"},
            ))
            session.add(LLMExchange(
                generation_log_id=child_log_id,
                exchange_order=1,
                agent="corrector",
                purpose="correct",
                request_body=None,
                response_body={"content": "child"},
                model_used="gpt-4.1",
            ))
            await session.commit()

    asyncio.run(seed())
    detail = math_client.get(f"/api/history/{parent_id}").json()
    assert detail["id"] == str(child_id)
    assert detail["generation_log_id"] == str(child_log_id)


async def _seed_log_and_record(
    client: TestClient,
    *,
    user_id: uuid.UUID,
    record_id: uuid.UUID,
    log_id: uuid.UUID,
    question_id: str,
    exchange: LLMExchange | None = None,
    parent_record_id: uuid.UUID | None = None,
) -> None:
    """Seed only the rows needed by a public history readback scenario."""
    async for session in client.app.dependency_overrides[get_async_session]():
        session.add(GenerationLog(id=log_id, user_id=user_id, params_json={}))
        session.add(GenerationRecord(
            id=record_id,
            user_id=user_id,
            parent_record_id=parent_record_id,
            subject="math",
            question_id=question_id,
            generation_log_id=log_id,
            params_json={"subject": "math"},
            question_json={"id": question_id},
            image_files=[],
        ))
        if exchange is not None:
            session.add(exchange)
        await session.commit()


def test_history_detail_advertises_available_exchange_evidence(
    math_client: TestClient,
) -> None:
    user_id = uuid.UUID(math_client.get("/auth/me").json()["id"])
    record_id = uuid.uuid4()
    log_id = uuid.uuid4()
    exchange = LLMExchange(
        generation_log_id=log_id,
        exchange_order=1,
        agent="generator",
        purpose="generate",
        request_body={"messages": []},
        response_body={"content": "evidence"},
        model_used="gpt-4.1",
    )
    asyncio.run(_seed_log_and_record(
        math_client,
        user_id=user_id,
        record_id=record_id,
        log_id=log_id,
        question_id="evidence-available",
        exchange=exchange,
    ))

    detail = math_client.get(f"/api/history/{record_id}")
    assert detail.status_code == 200
    assert detail.json()["generation_log_id"] == str(log_id)

    exchanges = math_client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert exchanges.status_code == 200
    assert exchanges.json()[0]["response_body"] == {"content": "evidence"}


def test_history_detail_reports_no_evidence_when_exchanges_were_never_persisted(
    math_client: TestClient,
) -> None:
    user_id = uuid.UUID(math_client.get("/auth/me").json()["id"])
    record_id = uuid.uuid4()
    log_id = uuid.uuid4()
    asyncio.run(_seed_log_and_record(
        math_client,
        user_id=user_id,
        record_id=record_id,
        log_id=log_id,
        question_id="evidence-never-recorded",
    ))

    detail = math_client.get(f"/api/history/{record_id}")
    assert detail.status_code == 200
    assert detail.json()["generation_log_id"] is None


def test_history_detail_reports_no_evidence_after_exchange_retention_pruning(
    math_client: TestClient,
) -> None:
    user_id = uuid.UUID(math_client.get("/auth/me").json()["id"])
    record_id = uuid.uuid4()
    log_id = uuid.uuid4()
    old_exchange = LLMExchange(
        generation_log_id=log_id,
        exchange_order=1,
        agent="generator",
        purpose="generate",
        request_body={"messages": []},
        response_body={"content": "expired"},
        model_used="gpt-4.1",
        created_at=datetime.now(timezone.utc) - timedelta(days=45),
    )
    asyncio.run(_seed_log_and_record(
        math_client,
        user_id=user_id,
        record_id=record_id,
        log_id=log_id,
        question_id="evidence-pruned",
        exchange=old_exchange,
    ))

    config = math_client.app.dependency_overrides[get_config]()
    asyncio.run(prune_expired_llm_exchanges(
        config,
        session_maker=generate_routes.AsyncSessionLocal,
    ))

    detail = math_client.get(f"/api/history/{record_id}")
    assert detail.status_code == 200
    assert detail.json()["generation_log_id"] is None


def test_history_detail_keeps_exchange_evidence_owner_scoped(
    math_client: TestClient,
) -> None:
    owner_id = uuid.UUID(math_client.get("/auth/me").json()["id"])
    record_id = uuid.uuid4()
    log_id = uuid.uuid4()
    asyncio.run(_seed_log_and_record(
        math_client,
        user_id=owner_id,
        record_id=record_id,
        log_id=log_id,
        question_id="evidence-owner-only",
        exchange=LLMExchange(
            generation_log_id=log_id,
            exchange_order=1,
            agent="generator",
            purpose="generate",
            request_body=None,
            response_body=None,
            model_used="gpt-4.1",
        ),
    ))
    other_id = uuid.uuid4()

    async def add_other_user() -> None:
        async for session in math_client.app.dependency_overrides[get_async_session]():
            session.add(User(id=other_id, email="evidence-other@example.com"))
            await session.commit()

    asyncio.run(add_other_user())
    config = math_client.app.dependency_overrides[get_config]()
    other_token = create_jwt(other_id, "evidence-other@example.com", config=config)
    headers = {"Authorization": f"Bearer {other_token}"}

    detail = math_client.get(f"/api/history/{record_id}", headers=headers)
    exchange_read = math_client.get(
        f"/api/generation-logs/{log_id}/exchanges",
        headers=headers,
    )
    assert detail.status_code == 404
    assert exchange_read.status_code == 404


def test_history_detail_uses_the_returned_descendant_log_with_exchange_evidence(
    math_client: TestClient,
) -> None:
    user_id = uuid.UUID(math_client.get("/auth/me").json()["id"])
    parent_id = uuid.uuid4()
    parent_log_id = uuid.uuid4()
    child_id = uuid.uuid4()
    child_log_id = uuid.uuid4()
    asyncio.run(_seed_log_and_record(
        math_client,
        user_id=user_id,
        record_id=parent_id,
        log_id=parent_log_id,
        question_id="evidence-parent",
        exchange=LLMExchange(
            generation_log_id=parent_log_id,
            exchange_order=1,
            agent="generator",
            purpose="generate",
            request_body=None,
            response_body={"content": "parent"},
            model_used="gpt-4.1",
        ),
    ))
    asyncio.run(_seed_log_and_record(
        math_client,
        user_id=user_id,
        record_id=child_id,
        log_id=child_log_id,
        question_id="evidence-child",
        parent_record_id=parent_id,
        exchange=LLMExchange(
            generation_log_id=child_log_id,
            exchange_order=1,
            agent="corrector",
            purpose="correct",
            request_body=None,
            response_body={"content": "child"},
            model_used="gpt-4.1",
        ),
    ))

    detail = math_client.get(f"/api/history/{parent_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == str(child_id)
    assert detail.json()["generation_log_id"] == str(child_log_id)

    exchanges = math_client.get(f"/api/generation-logs/{child_log_id}/exchanges")
    assert exchanges.status_code == 200
    assert [row["purpose"] for row in exchanges.json()] == ["correct"]
