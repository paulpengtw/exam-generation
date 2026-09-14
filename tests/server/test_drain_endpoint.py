"""Slice 2: /internal/drain endpoint tests."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.drain import DrainTelemetry
from server.generate.subjects import SubjectSpec
from server.models import Base, User
from server.rate_limit import limiter

# ---------------------------------------------------------------------------
# Minimal fake spec for content-free assertions
# ---------------------------------------------------------------------------


class _FQ:
    id: str

    def __init__(self, id: str) -> None:
        self.id = id

    def model_dump(self, **kw):
        return {"id": self.id}


def _fast_spec() -> SubjectSpec:
    from pydantic import BaseModel

    class _FQP(BaseModel):
        id: str
        圖片: str | None = None

    def coerce_overrides(p, a):
        return {}

    def plan_all_batch_briefs(*a, **kw):
        return []

    def params_from_resolved_payload(payload, overrides):
        return SimpleNamespace()

    def do_generate(rng_params, overrides, **kw):
        return _FQP(id=kw["question_id"])

    def extract_prior_scope(q):
        return None

    def plan_core_questions(client, topic, **kw):  # pragma: no cover
        return []

    def load_planner_stage(cfg, grade):  # pragma: no cover
        return "第四學習階段"

    def build_schemas(cfg, grade):  # pragma: no cover
        return {}

    return SubjectSpec(
        key="fake",
        question_id_prefix="fake_",
        exam_question_cls=_FQP,
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        params_from_resolved_payload=params_from_resolved_payload,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        patch_metadata=None,
        plan_core_questions=plan_core_questions,
        load_planner_stage=load_planner_stage,
        build_schemas=build_schemas,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_app(tmp_path, token: str = ""):
    """Create test app with an in-memory DB and drain token."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.get_event_loop().run_until_complete(_create_tables())

    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        output_dir=tmp_path,
        data_dir=Path("data"),
        drain_telemetry_token=token,
        creative_planning=False,
    )

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="t@test.com"
    )
    app.dependency_overrides[get_async_session] = lambda: session_factory()
    limiter.reset()

    drain = DrainTelemetry()
    app.state.drain_telemetry = drain
    app.state.renderer_pool = None

    return app, drain


# ---------------------------------------------------------------------------
# (a) Disabled → 404
# ---------------------------------------------------------------------------


def test_drain_disabled_returns_404(tmp_path):
    """When DRAIN_TELEMETRY_TOKEN is empty, /internal/drain returns 404."""
    app, _ = _make_app(tmp_path, token="")
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.get("/internal/drain", headers={"X-Drain-Token": "anything"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# (b) Wrong token → 403
# ---------------------------------------------------------------------------


def test_drain_wrong_token_returns_403(tmp_path):
    """Wrong X-Drain-Token header returns 403."""
    app, _ = _make_app(tmp_path, token="correct-secret")
    with TestClient(app) as client:
        r = client.get("/internal/drain", headers={"X-Drain-Token": "wrong"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# (c) Correct token → snapshot JSON
# ---------------------------------------------------------------------------


def test_drain_correct_token_returns_snapshot(tmp_path):
    """Correct token returns a valid snapshot with identity and counters."""
    app, drain = _make_app(tmp_path, token="my-secret")
    with TestClient(app) as client:
        r = client.get("/internal/drain", headers={"X-Drain-Token": "my-secret"})
    assert r.status_code == 200
    data = r.json()
    # Identity fields
    assert "instance_id" in data
    assert "hostname" in data
    assert "pid" in data
    assert "started_at" in data
    assert "supported_stream_versions" in data
    assert 1 in data["supported_stream_versions"]
    # Counter fields
    assert "active_runs" in data
    assert "active_workers" in data
    assert "open_streams" in data
    assert "pending_deliveries" in data
    assert "pending_persistence" in data
    assert "renderer_leases_held" in data
    assert "quiescent" in data
    assert "captured_at" in data


# ---------------------------------------------------------------------------
# (d) Content-free: no question text, prompts, or user identity in response
# ---------------------------------------------------------------------------


def test_drain_no_content_leak(tmp_path):
    """The drain response must not contain question text, prompts, or user info."""
    app, drain = _make_app(tmp_path, token="secret-token")

    # Simulate an active run by incrementing counters
    drain._inc("_active_runs")
    drain._inc("_active_workers")

    with TestClient(app) as client:
        r = client.get("/internal/drain", headers={"X-Drain-Token": "secret-token"})

    assert r.status_code == 200
    body = r.text.lower()

    # None of these content markers should appear
    for marker in ["question", "prompt", "user_id", "email", "params", "subject_filter"]:
        assert marker not in body, f"Forbidden marker '{marker}' found in drain response"

    # Cleanup
    drain._dec("_active_runs")
    drain._dec("_active_workers")
