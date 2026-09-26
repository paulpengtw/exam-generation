"""Tests for POST /api/plan-core-questions endpoint."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter


class _FailingSession:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def execute(self, _statement: Any) -> None:
        raise self._error


def _make_app_and_token():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        gemini_api_key="x",
        llm_models_allowed=(
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "claude-haiku-4-6",
        ),
    )
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    token = create_jwt(user_id, "u@example.com", config=config)
    return app, token, engine


_SENTINEL_USER_ID = "user-id-sentinel-789"


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TimeoutError("database unavailable"), id="TimeoutError"),
        pytest.param(ConnectionRefusedError("database unavailable"), id="ConnectionRefusedError"),
        pytest.param(
            OperationalError(
                "SELECT users.id FROM users WHERE users.id = :user_id",
                (_SENTINEL_USER_ID,),
                RuntimeError("database unavailable"),
            ),
            id="OperationalError",
        ),
    ],
)
def test_plan_core_questions_database_outage_returns_retryable_503(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: BaseException,
) -> None:
    app, token, engine = _make_app_and_token()
    planner_calls: list[None] = []

    def fake_plan_core_questions(*_args: Any, **_kwargs: Any) -> list[str]:
        planner_calls.append(None)
        return ["不應該產生"]

    monkeypatch.setattr("src.planner.plan_core_questions", fake_plan_core_questions)

    async def unavailable_session() -> AsyncGenerator[_FailingSession, None]:
        yield _FailingSession(error)

    app.dependency_overrides[get_async_session] = unavailable_session
    caplog.set_level(logging.WARNING, logger="server.auth.dependencies")
    auth_logger = logging.getLogger("server.auth.dependencies")
    auth_logger.addHandler(caplog.handler)
    try:
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/plan-core-questions",
                    json={"topic": "統計", "subject": "math"},
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            auth_logger.removeHandler(caplog.handler)
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database temporarily unavailable; please retry.",
        "code": "DATABASE_UNAVAILABLE",
    }
    assert response.headers["Retry-After"] == "5"
    assert planner_calls == []

    warnings = [
        record
        for record in caplog.records
        if record.name == "server.auth.dependencies" and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    record = warnings[0]
    assert record.exc_info is None
    assert record.error_type == type(error).__name__
    assert record.error_module == type(error).__module__
    rendered_message = caplog.handler.format(record)
    record_attributes = "\n".join(repr(value) for value in vars(record).values())
    assert _SENTINEL_USER_ID not in rendered_message
    assert "SELECT" not in rendered_message
    assert _SENTINEL_USER_ID not in record_attributes
    assert "SELECT" not in record_attributes


def test_plan_core_questions_database_recovery_reuses_same_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, token, engine = _make_app_and_token()
    healthy_session = app.dependency_overrides[get_async_session]

    def fake_plan_core_questions(*_args: Any, **_kwargs: Any) -> list[str]:
        return ["核心問題一", "核心問題二", "核心問題三"]

    monkeypatch.setattr("src.planner.plan_core_questions", fake_plan_core_questions)

    async def unavailable_session() -> AsyncGenerator[_FailingSession, None]:
        yield _FailingSession(TimeoutError)

    app.dependency_overrides[get_async_session] = unavailable_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            failed = client.post(
                "/api/plan-core-questions",
                json={"topic": "統計", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
            app.dependency_overrides[get_async_session] = healthy_session
            recovered = client.post(
                "/api/plan-core-questions",
                json={"topic": "統計", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert failed.status_code == 503
    assert recovered.status_code == 200
    assert recovered.json() == {
        "candidates": ["核心問題一", "核心問題二", "核心問題三"],
    }


def test_plan_core_questions_does_not_block_other_async_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, token, engine = _make_app_and_token()
    planner_started = threading.Event()
    planner_release = threading.Event()
    planner_released = threading.Event()
    planner_timed_out = threading.Event()

    def blocking_plan_core_questions(*_args: Any, **_kwargs: Any) -> list[str]:
        planner_started.set()
        if planner_release.wait(timeout=5):
            planner_released.set()
        else:
            planner_timed_out.set()
        return ["核心問題一", "核心問題二", "核心問題三"]

    monkeypatch.setattr("src.planner.plan_core_questions", blocking_plan_core_questions)

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
        ) as client:
            planner_task = asyncio.create_task(
                client.post(
                    "/api/plan-core-questions",
                    json={"topic": "統計", "subject": "math"},
                )
            )
            assert await asyncio.to_thread(planner_started.wait, 5)
            health_task = asyncio.create_task(client.get("/health"))
            try:
                health_response = await asyncio.wait_for(health_task, timeout=1)
            finally:
                planner_release.set()
            planner_response = await asyncio.wait_for(planner_task, timeout=5)
        return planner_response, health_response

    try:
        planner_response, health_response = asyncio.run(exercise())
    finally:
        planner_release.set()
        limiter.reset()
        asyncio.run(engine.dispose())

    assert health_response.status_code == 200
    assert planner_response.status_code == 200
    assert planner_response.json() == {
        "candidates": ["核心問題一", "核心問題二", "核心問題三"],
    }
    assert planner_released.is_set()
    assert not planner_timed_out.is_set()


@pytest.mark.parametrize("subject", ["math", "social_studies", "natural_sciences"])
def test_planning_preserves_short_text_in_numbered_provider_response(monkeypatch, subject):
    """Three supplied questions must not become two because one is short."""
    app, token, engine = _make_app_and_token()
    prompts = []

    def provider_response(self, system, user, *, purpose):
        prompts.append(user)
        return "1. 如何測量每天用水量？\n2. 如何比較不同節水方式？\n3.為何？"

    monkeypatch.setattr("src.llm_client.LLMClient.plan", provider_response)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "節水", "subject": subject},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200, response.json()
    assert response.json()["candidates"] == [
        "如何測量每天用水量？", "如何比較不同節水方式？", "為何？",
    ]
    assert len(prompts) == 1


@pytest.mark.parametrize("first_response", [
    None,
    '["如何測量用水？", "如何比較節水方式？", "  "]',
    '["如何測量用水？", "如何比較節水方式？", 42]',
    '["如何測量用水？", "如何比較節水方式？", {"question": "為何？"}]',
    '["如何測量用水？", "如何比較節水方式？", " 如何測量用水？ "]',
    "這是一段說明文字而已\n目前還沒有產生問題\n請稍後再試一次看看",
])
def test_planning_retries_unusable_candidates_instead_of_claiming_success(
    monkeypatch, first_response,
):
    app, token, engine = _make_app_and_token()
    prompts = []

    def provider_response(self, system, user, *, purpose):
        prompts.append(user)
        if len(prompts) == 1:
            return first_response
        return '["如何測量用水？", "如何比較節水方式？", "為何節水？"]'

    monkeypatch.setattr("src.llm_client.LLMClient.plan", provider_response)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "節水", "subject": "natural_sciences"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert response.json()["candidates"] == ["如何測量用水？", "如何比較節水方式？", "為何節水？"]
    assert len(prompts) == 2


@pytest.mark.parametrize("subject", ["math", "social_studies", "natural_sciences"])
@pytest.mark.parametrize("corrected", [True, False], ids=["recovered", "exhausted"])
def test_planning_targets_short_response_correction_within_two_calls(
    monkeypatch, subject, corrected,
):
    app, token, engine = _make_app_and_token()
    prompts = []
    candidates = ["如何測量用水？", "如何比較節水方式？", "為何節水？"]

    def provider_response(self, system, user, *, purpose):
        prompts.append(user)
        return json.dumps(candidates if corrected and len(prompts) == 2 else candidates[:2])

    monkeypatch.setattr("src.llm_client.LLMClient.plan", provider_response)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "節水", "subject": subject},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert len(prompts) == 2
    assert "階段=candidate_validation" in prompts[1]
    assert "實際可用=2" in prompts[1]
    assert "預期=3" in prompts[1]
    assert "非空白" in prompts[1] and "互不重複" in prompts[1]
    assert candidates[0] not in prompts[1]
    assert response.status_code == (200 if corrected else 502)
    if corrected:
        assert response.json()["candidates"] == candidates
    else:
        assert response.json() == {"detail": "Planner upstream returned malformed candidates"}


def test_plan_core_questions_math_happy_path(monkeypatch) -> None:
    app, token, engine = _make_app_and_token()


    def fake_plan_core_questions(client, topic, **kwargs):
        return ["核心問題一", "核心問題二", "核心問題三"]

    monkeypatch.setattr(
        "src.planner.plan_core_questions",
        fake_plan_core_questions,
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "微積分", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    data = response.json()
    assert data["candidates"] == ["核心問題一", "核心問題二", "核心問題三"]


def test_plan_core_questions_math_malformed_then_retry(monkeypatch) -> None:
    """Planner raises ValueError once (retry appends reminder), succeeds on second call."""
    app, token, engine = _make_app_and_token()

    call_count = 0
    import src.llm_client as llm_module

    def fake_plan(self, system, user, *, purpose):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First attempt: bad output that fails parsing
            return "這不是 JSON"
        # Second attempt should have reminder appended to user prompt
        assert "注意：請務必輸出剛好" in user
        return '["核心問題一", "核心問題二", "核心問題三"]'

    monkeypatch.setattr(llm_module.LLMClient, "plan", fake_plan)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "統計", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert response.json()["candidates"] == ["核心問題一", "核心問題二", "核心問題三"]
    assert call_count == 2


def test_plan_core_questions_math_both_attempts_fail_returns_502(monkeypatch) -> None:
    """When both retry attempts return malformed output, endpoint returns 502."""
    app, token, engine = _make_app_and_token()

    import src.llm_client as llm_module

    def fake_plan(self, system, user, *, purpose):
        return "not valid json at all"

    monkeypatch.setattr(llm_module.LLMClient, "plan", fake_plan)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "幾何", "subject": "math"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 502
    assert "malformed" in response.json()["detail"].lower()


def test_plan_core_questions_defaults_to_social_studies(monkeypatch) -> None:
    """subject defaults to social_studies when not specified."""
    app, token, engine = _make_app_and_token()

    captured = {}

    def fake_ss_plan(client, topic, **kwargs):
        captured["subject"] = "social_studies"
        captured["topic"] = topic
        return ["問題一", "問題二", "問題三"]

    monkeypatch.setattr(
        "src.social_studies.planner.plan_core_questions",
        fake_ss_plan,
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "民主政治"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured.get("subject") == "social_studies"
    assert captured.get("topic") == "民主政治"


def test_plan_core_questions_natural_sciences(monkeypatch) -> None:
    app, token, engine = _make_app_and_token()

    captured = {}

    def fake_ns_plan(client, topic, **kwargs):
        captured["topic"] = topic
        captured["learning_stage"] = kwargs["learning_stage"]
        captured["grade"] = kwargs["grade"]
        return ["科學問題一", "科學問題二", "科學問題三"]

    monkeypatch.setattr(
        "src.natural_sciences.planner.plan_core_questions",
        fake_ns_plan,
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "糧食安全", "subject": "natural_sciences", "grade": 8},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert response.json()["candidates"] == ["科學問題一", "科學問題二", "科學問題三"]
    assert captured == {
        "topic": "糧食安全",
        "learning_stage": "第四學習階段",
        "grade": 8,
    }


def test_plan_core_questions_forwards_model_plan_override(monkeypatch) -> None:
    """When model_plan is submitted, the LLMClient used by the planner sees it."""
    app, token, engine = _make_app_and_token()

    captured: dict = {}

    def fake_math_plan(client, topic, **kwargs):
        captured["model_plan"] = client.config.model_plan
        captured["model_execute"] = client.config.model_execute
        return ["核心問題一", "核心問題二", "核心問題三"]

    monkeypatch.setattr("src.planner.plan_core_questions", fake_math_plan)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={
                    "topic": "統計",
                    "subject": "math",
                    "model_plan": "claude-haiku-4-5",
                    "model_execute": "claude-haiku-4-6",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    # Distinct from SrcConfig.from_env() defaults (opus-4-6 / sonnet-4-6) so this
    # actually discriminates override-applied from override-ignored.
    assert captured["model_plan"] == "claude-haiku-4-5"
    assert captured["model_execute"] == "claude-haiku-4-6"


def test_plan_core_questions_absent_override_keeps_defaults(monkeypatch) -> None:
    app, token, engine = _make_app_and_token()

    captured: dict = {}

    def fake_ss_plan(client, topic, **kwargs):
        captured["model_plan"] = client.config.model_plan
        captured["model_execute"] = client.config.model_execute
        return ["問題一", "問題二", "問題三"]

    monkeypatch.setattr("src.social_studies.planner.plan_core_questions", fake_ss_plan)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "民主政治"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    # Defaults from SrcConfig.from_env() — not user-supplied.
    assert captured["model_plan"] == "claude-opus-4-6"
    assert captured["model_execute"] == "gemini-3.1-pro-preview"
