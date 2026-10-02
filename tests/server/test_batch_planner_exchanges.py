"""Batch planner activity and exchange persistence (issue #801)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.marshalling import SSEEventName
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.models import Base, GenerationLog, User


class _AppState:
    renderer_pool = None


class _BarrierStream:
    def __init__(
        self,
        *,
        release,
        thinking_seen,
        content: str,
        thinking_delay_seconds: float = 0,
    ):
        self._release = release
        self._thinking_seen = thinking_seen
        self._content = content
        self._thinking_delay_seconds = thinking_delay_seconds

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        time.sleep(self._thinking_delay_seconds)
        yield SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="thinking_delta", thinking="planner reasoning"),
        )
        self._thinking_seen.set()
        assert self._release.wait(timeout=5), "test did not release planner response"
        yield SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text=self._content),
        )

    def get_final_message(self):
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )


def _params() -> GenerateParams:
    payload = json.loads(
        (Path(__file__).parents[1] / "fixtures/transport-social-batch.json").read_text()
    )
    payload["count"] = 1
    payload["per_question_params"] = json.dumps(
        json.loads(payload["per_question_params"])[:1], ensure_ascii=False
    )
    payload["model_plan"] = "claude-opus-4-6"
    payload["effort_plan"] = "max"
    return GenerateParams.model_validate(payload)


def test_planner_streams_thinking_and_persists_before_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The real SS planner must stream activity before its provider responds."""
    release = threading.Event()
    thinking_seen = threading.Event()
    plan_response = json.dumps([{
        "selected_context": "教育",
        "題材_angle": "以校園公共決策連結證據判讀",
        "framing_hooks": ["會議紀錄"],
    }], ensure_ascii=False)

    # The SDK boundary is the only stub: LLMClient, the SS planner, and the
    # generation service remain real.
    from anthropic.resources.messages import Messages
    from openai.resources.chat.completions import Completions

    anthropic_calls: list[dict] = []

    def anthropic_stream(_self, **kwargs):
        anthropic_calls.append(kwargs)
        assert kwargs["model"] == "claude-opus-4-6"
        return _BarrierStream(
            release=release,
            thinking_seen=thinking_seen,
            content=plan_response,
            # Keep this above the former per-event 2 s deadline.  The test
            # must tolerate a busy suite delaying planner activity without
            # cancelling the async generator that it is trying to inspect.
            thinking_delay_seconds=2.1,
        )

    def openai_stream(_self, **kwargs):
        content = json.dumps({
            "核心問題": "如何比較校園公共決策中的證據？",
            "文本": "校園會議紀錄呈現不同意見。",
            "subquestions": [{
                "序號": 1,
                "出題概念": "辨識證據",
                "題型": "選擇題",
                "題目": "哪一項是直接證據？",
                "答案": "A",
                "答案解析": "會議紀錄是直接資料。",
            }],
        }, ensure_ascii=False)
        return iter([SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=content))],
            usage=None,
        )])

    monkeypatch.setattr(Messages, "stream", anthropic_stream)
    monkeypatch.setattr(Completions, "create", openai_stream)

    async def exercise() -> tuple[list[dict], list[dict]]:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'planner.db'}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        user_id = uuid.uuid4()
        log_id = uuid.uuid4()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(User(id=user_id, email="planner@example.com"))
            session.add(GenerationLog(
                id=log_id, user_id=user_id, params_json={}, status="started",
            ))
            await session.commit()

        config = ServerConfig(
            api_key="test",
            openai_api_key="test",
            output_dir=tmp_path,
            model_plan="claude-sonnet-4-6",
            model_execute="gpt-4.1",
            creative_planning=True,
            llm_stream=True,
            llm_exchange_retention_days=30,
            jwt_secret="planner-test-secret",
        )
        app = create_app()
        app.dependency_overrides[get_config] = lambda: config

        async def session_dependency():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_async_session] = session_dependency
        token = create_jwt(user_id, "planner@example.com", config=config)
        stream = generate_question_stream(
            _params(), config, _AppState(), generation_log_id=log_id,
            session_factory=sessions,
        )
        events: list[dict] = []
        try:
            # Bound the semantic milestone rather than every scheduling gap.
            # A per-event wait_for cancels the stream when a loaded runner takes
            # more than two seconds to deliver any one interim event.
            async with asyncio.timeout(10):
                while True:
                    event = await anext(stream)
                    events.append(event)
                    if event["event"] == SSEEventName.LLM_THINKING:
                        break
            assert events[0]["event"] == SSEEventName.STARTED
            assert thinking_seen.is_set()
            assert not release.is_set()
            release.set()
            events.extend([event async for event in stream])

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver",
                headers={"Authorization": f"Bearer {token}"},
            ) as reader:
                response = await reader.get(f"/api/generation-logs/{log_id}/exchanges")
            assert response.status_code == 200, response.text
            return events, response.json()
        finally:
            release.set()
            await stream.aclose()
            await engine.dispose()

    events, rows = asyncio.run(exercise())
    assert any(event["event"] == SSEEventName.RESULT for event in events)
    assert not any(event["event"] == SSEEventName.ERROR for event in events)
    assert any(
        event["event"] == SSEEventName.LLM_RESPONSE
        and event.get("payload", event.get("data", {})).get("purpose") == "plan_context_angles"
        for event in events
    )
    assert rows
    assert rows[0]["agent"] == "planner"
    assert any(row["agent"] == "generator" for row in rows[1:])
    assert any(row["agent"].startswith("sub_generator#") for row in rows[1:])
    assert rows[0]["purpose"] == "plan_context_angles"
    assert rows[0]["model_used"] == "claude-opus-4-6"
    assert rows[0]["response_body"]["reasoning"] == "planner reasoning"
    assert rows[0]["request_body"]["params"]["thinking"] == {"type": "adaptive"}
    assert rows[0]["request_body"]["params"]["extra_body"]["output_config"]["effort"] == "max"
    assert anthropic_calls[0]["thinking"] == {"type": "adaptive"}
    assert anthropic_calls[0]["extra_body"]["output_config"]["effort"] == "max"
    assert [row["exchange_order"] for row in rows] == list(range(1, len(rows) + 1))
