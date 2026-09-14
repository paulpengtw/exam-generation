"""Split CLI/server tier defaults and preserve override contracts (issue #759)."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.config
import src.config
from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter
from src.config import Config
from src.llm_client import LLMClient
from tests.server.generate_test_utils import complete_math_query_params

_EXPECTED_DEFAULTS = {
    "model_plan": "claude-opus-4-6",
    "model_execute": "gemini-3.1-pro-preview",
    "model_verify": "claude-opus-4-6",
    "model_correct": "",
    "effort_plan": "high",
    "effort_execute": "high",
    "effort_verify": "high",
    "effort_correct": "",
}
_EXPECTED_ROSTER = (
    "gemini-3.1-pro-preview",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-opus-5",
    "claude-fable-5",
    "claude-sonnet-5",
)


@pytest.mark.parametrize("reader", [Config, ServerConfig])
def test_unset_environment_uses_split_tier_defaults(reader, tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        cfg = reader.from_env(env_file=tmp_path / ".env.missing")
    assert {name: getattr(cfg, name) for name in _EXPECTED_DEFAULTS} == _EXPECTED_DEFAULTS


@pytest.mark.parametrize("reader", [Config, ServerConfig])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_plan", "claude-opus-5"),
        ("model_execute", "claude-sonnet-4-6"),
        ("model_verify", "gemini-3.1-pro-preview"),
        ("model_correct", "claude-sonnet-4-6"),
        ("effort_plan", "low"),
        ("effort_execute", "medium"),
        ("effort_verify", "low"),
        ("effort_correct", "medium"),
    ],
)
def test_explicit_env_override_wins(reader, field: str, value: str, tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {f"LLM_{field.upper()}": value}, clear=True):
        cfg = reader.from_env(env_file=tmp_path / ".env.missing")
    assert getattr(cfg, field) == value


@pytest.mark.parametrize("reader", [Config, ServerConfig])
def test_empty_verify_env_inherits_execute_at_call_time(reader, tmp_path: Path) -> None:
    env = {
        "LLM_API_KEY": "x",
        "LLM_MODEL_EXECUTE": "claude-sonnet-4-6",
        "LLM_EFFORT_EXECUTE": "low",
        "LLM_MODEL_VERIFY": "",
        "LLM_EFFORT_VERIFY": "",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = reader.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.model_verify == cfg.effort_verify == ""
    # No calls are needed: exercise the real call-time tier resolvers with a fake API.
    client = LLMClient(cfg)
    client.client = SimpleNamespace(messages=mock.Mock())
    assert client._model_for_purpose("verify") == "claude-sonnet-4-6"
    assert client._effort_for_purpose("verify") == "low"

    client.config = dataclasses.replace(
        cfg, model_execute="gemini-3.1-pro-preview", effort_execute="medium"
    )
    assert client.config.model_verify == client.config.effort_verify == ""
    assert client._model_for_purpose("verify") == "gemini-3.1-pro-preview"
    assert client._effort_for_purpose("verify") == "medium"
    assert client._model_for_purpose("correct") == "gemini-3.1-pro-preview"
    assert client._effort_for_purpose("correct") == "medium"


@pytest.mark.parametrize("reader", [Config, ServerConfig])
@pytest.mark.parametrize("field", _EXPECTED_DEFAULTS)
def test_dataclass_defaults_match_shared_constants(reader, field: str) -> None:
    assert getattr(reader(), field) == getattr(src.config, f"DEFAULT_{field.upper()}")


def test_builtin_roster_order_and_membership() -> None:
    assert server.config._DEFAULT_MODELS_ALLOWED == _EXPECTED_ROSTER


def test_models_endpoint_reports_full_defaults_and_effort_rosters(tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    app = create_app()
    app.dependency_overrides[get_config] = lambda: cfg
    with TestClient(app) as client:
        response = client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    assert body["defaults"] == {
        "plan": "claude-opus-4-6",
        "execute": "gemini-3.1-pro-preview",
        "verify": "claude-opus-4-6",
        "correct": "",
        "effort_plan": "high",
        "effort_execute": "high",
        "effort_verify": "high",
        "effort_correct": "",
    }
    assert body["allowed"] == list(_EXPECTED_ROSTER)
    assert body["effort"]["claude-opus-4-6"] == ["low", "medium", "high", "max"]
    assert body["effort"]["gemini-3.1-pro-preview"] == ["low", "medium", "high"]
    assert body["effort"]["claude-sonnet-4-6"] == ["low", "medium", "high", "max"]
    assert body["effort"]["claude-opus-5"] == ["low", "medium", "high", "xhigh", "max"]


def _make_authed_app(cfg: ServerConfig) -> tuple:
    """Use real JWT authentication and an in-memory database, as in #379."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with session_factory() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())
    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: cfg
    limiter.reset()
    token = create_jwt(user_id, "u@example.com", config=cfg)
    return app, token, engine


@pytest.fixture
def authed_client() -> Iterator[tuple[TestClient, ServerConfig]]:
    # Keep route-side Config.from_env() independent of local .env files, too.
    with (
        mock.patch.dict(os.environ, {}, clear=True),
        mock.patch("src.config.load_dotenv"),
        mock.patch(
            "src.social_studies.planner.plan_core_questions",
            return_value=["問題一", "問題二", "問題三"],
        ),
    ):
        cfg = ServerConfig(
            api_key="x",
            gemini_api_key="x",
            jwt_secret="test-secret",
            llm_models_allowed=server.config._DEFAULT_MODELS_ALLOWED,
        )
        app, token, engine = _make_authed_app(cfg)
        try:
            with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
                yield client, cfg
        finally:
            limiter.reset()
            asyncio.run(engine.dispose())


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"model_plan": "claude-opus-5", "effort_plan": "max"},
        {"model_execute": "claude-sonnet-4-6"},
    ],
)
def test_plan_request_defaults_and_overrides_reach_planner(authed_client, monkeypatch, overrides):
    client, _ = authed_client
    captured = {}

    def fake_plan(llm_client, topic, **kwargs):
        captured.update(dataclasses.asdict(llm_client.config))
        return ["問題一", "問題二", "問題三"]

    monkeypatch.setattr("src.social_studies.planner.plan_core_questions", fake_plan)
    response = client.post("/api/plan-core-questions", json={"topic": "民主政治", **overrides})
    assert response.status_code == 200
    assert {name: captured[name] for name in _EXPECTED_DEFAULTS} == {
        **_EXPECTED_DEFAULTS, **overrides
    }


@pytest.mark.parametrize("effort", ["xhigh", "max"])
def test_default_execute_model_rejects_unsupported_effort(authed_client, effort: str) -> None:
    client, _ = authed_client
    response = client.get(
        "/api/generate/preview",
        params=complete_math_query_params(effort_execute=effort),
    )
    assert response.status_code == 422
    assert "effort_execute" in response.json()["detail"]
    assert "gemini-3.1-pro-preview" in response.json()["detail"]


def test_default_plan_model_rejects_xhigh(authed_client) -> None:
    client, _ = authed_client
    response = client.post(
        "/api/plan-core-questions", json={"topic": "民主政治", "effort_plan": "xhigh"}
    )
    assert response.status_code == 422
    assert "effort_plan" in response.json()["detail"]
    assert "claude-opus-4-6" in response.json()["detail"]


@pytest.mark.parametrize(
    ("key_attr", "field", "model", "env_name"),
    [
        ("gemini_api_key", "model_execute", "gemini-3.1-pro-preview", "GEMINI_API_KEY"),
        ("api_key", "model_plan", "claude-opus-4-6", "LLM_API_KEY"),
    ],
)
def test_default_tiers_require_both_provider_keys(authed_client, key_attr, field, model, env_name):
    client, cfg = authed_client
    setattr(cfg, key_attr, "")
    response = client.post("/api/plan-core-questions", json={"topic": "民主政治"})
    assert response.status_code == 422
    assert response.json()["detail"] == (
        f"{field}: model '{model}' requires {env_name} to be set on the server"
    )
