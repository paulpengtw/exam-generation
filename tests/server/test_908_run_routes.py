"""Issue #908 – detached generation HTTP surface.

``POST /api/generate`` records 受理 and returns 202 with the run identity and
manifest; protocol version 2 or an absent version gets 426.  ``GET
/api/runs/{id}`` is owner-only.  An observer that leaves mid-run does not
affect the run: it keeps executing on the host loop and its results are
readable afterwards.
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.run import run_host_loop
from server.generate.subjects import SUBJECTS
from server.models import Base, GenerationLog, User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params

_MATH: dict[str, Any] = {
    "subject": "math",
    "seed": 41,
    "grade": 8,
    "context": ["個人"],
    "set_type": "單一題",
    "q_type": ["選擇題"],
    "style": ["text_only"],
    "math_thinking": ["形成"],
    "learning_content": ["A-7-7"],
    "learning_performance": ["s-IV-12"],
    "core_competency": ["數-J-A2"],
    "content_type": "純文字",
    "skip_verify": True,
    "count": 2,
}


def _body(**overrides: Any) -> dict[str, Any]:
    """A resolver-complete JSON body; ``stream_version`` only when given."""
    payload = complete_math_query_params(**{k: v for k, v in _MATH.items() if k != "subject"})
    payload.pop("stream_version", None)
    payload.update(overrides)
    return payload


class _Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.db_url = f"sqlite+aiosqlite:///{tmp_path / 'routes.db'}"
        self.config = ServerConfig(
            api_key="x",
            jwt_secret="test-secret",
            gemini_api_key="x",
            output_dir=tmp_path / "out",
            data_dir=Path("data"),
        )
        self.owner = uuid.uuid4()
        self.other = uuid.uuid4()

        async def _init() -> None:
            engine = create_async_engine(self.db_url)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with sessions() as session:
                session.add_all([
                    User(id=self.owner, email="owner@example.com"),
                    User(id=self.other, email="other@example.com"),
                ])
                await session.commit()
            await engine.dispose()

        asyncio.run(_init())

    def app(self) -> Any:
        engine = create_async_engine(self.db_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async def override_session() -> AsyncGenerator[AsyncSession, None]:
            async with sessions() as session:
                yield session

        app = create_app()
        app.dependency_overrides[get_async_session] = override_session
        app.dependency_overrides[get_config] = lambda: self.config
        limiter.reset()
        return app

    def headers(self, user_id: uuid.UUID) -> dict[str, str]:
        email = "owner@example.com" if user_id == self.owner else "other@example.com"
        return {"Authorization": f"Bearer {create_jwt(user_id, email, config=self.config)}"}

    def count_runs(self) -> int:
        async def _count() -> int:
            engine = create_async_engine(self.db_url)
            try:
                async with engine.connect() as conn:
                    return (
                        await conn.execute(select(func.count()).select_from(GenerationLog))
                    ).scalar_one()
            finally:
                await engine.dispose()

        return asyncio.run(_count())


@pytest.fixture()
def harness(tmp_path: Path) -> _Harness:
    return _Harness(tmp_path)


@pytest.mark.parametrize("version", [None, 2, 4])
def test_submit_without_protocol_3_is_426_and_creates_nothing(
    harness: _Harness, version: int | None
) -> None:
    body = _body() if version is None else _body(stream_version=version)
    with TestClient(harness.app()) as client:
        response = client.post(
            "/api/generate", json=body, headers=harness.headers(harness.owner)
        )
    assert response.status_code == 426
    assert response.json()["code"] == "CLIENT_UPDATE_REQUIRED"
    assert response.json()["supported_stream_versions"] == [3]
    assert isinstance(response.json()["detail"], str) and response.json()["detail"]
    assert harness.count_runs() == 0


def test_submit_returns_202_with_run_identity_and_manifest(harness: _Harness) -> None:
    with TestClient(harness.app()) as client:
        response = client.post(
            "/api/generate",
            json=_body(stream_version=3),
            headers=harness.headers(harness.owner),
        )
        assert response.status_code == 202
        accepted = response.json()
        assert accepted["protocol_version"] == 3
        assert accepted["total"] == 2
        run_id = accepted["run_id"]
        assert accepted["questions"] == [
            {"index": 0, "question_id": f"q_{run_id}_001"},
            {"index": 1, "question_id": f"q_{run_id}_002"},
        ]

        read = client.get(f"/api/runs/{run_id}", headers=harness.headers(harness.owner))
        assert read.status_code == 200
        assert read.json()["status"] == "queued"
        assert [q["processing"] for q in read.json()["questions"]] == ["waiting", "waiting"]


def test_run_read_is_refused_to_another_user(harness: _Harness) -> None:
    with TestClient(harness.app()) as client:
        run_id = client.post(
            "/api/generate",
            json=_body(stream_version=3),
            headers=harness.headers(harness.owner),
        ).json()["run_id"]
        refused = client.get(f"/api/runs/{run_id}", headers=harness.headers(harness.other))
        missing = client.get(
            f"/api/runs/{uuid.uuid4()}", headers=harness.headers(harness.owner)
        )
        anonymous = client.get(f"/api/runs/{run_id}")
    assert refused.status_code == 404
    assert "questions" not in refused.json()
    assert missing.status_code == 404
    assert anonymous.status_code == 401


def test_query_spelling_is_the_same_non_streaming_acceptance(harness: _Harness) -> None:
    with TestClient(harness.app()) as client:
        response = client.get(
            "/api/generate",
            params=_body(stream_version=3),
            headers=harness.headers(harness.owner),
        )
    assert response.status_code == 202
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["protocol_version"] == 3
    assert harness.count_runs() == 1


def test_observer_leaving_mid_run_does_not_affect_the_run(harness: _Harness) -> None:
    """Submit, watch once while B generates, leave, and find the run finished."""
    from src.schemas import ExamQuestion

    release = threading.Event()

    def do_generate(rng_params: Any, overrides: Any, **kwargs: Any) -> Any:
        qid = kwargs["question_id"]
        if qid.endswith("_002"):
            assert release.wait(timeout=20)
        return ExamQuestion(
            id=qid,
            情境=["個人"],
            題型種類="單一題",
            題型="選擇題",
            數學思考=["形成"],
            學習內容=[{"編碼": "A-7-7", "說明": "lc"}],
            題目=[f"stem {qid}"],
            正確解題分析=["answer"],
        )

    class _Client:
        def __init__(self, config: Any) -> None:
            pass

        def set_observer(self, cb: Any) -> None:
            pass

        def clear_observer(self) -> None:
            pass

    stop = asyncio.Event()
    host_loop: dict[str, Any] = {}

    def _host() -> None:
        async def _run() -> None:
            host_loop["loop"] = asyncio.get_running_loop()
            engine = create_async_engine(harness.db_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            app_state = MagicMock()
            app_state.renderer_pool = None
            try:
                await run_host_loop(
                    stop,
                    app_state=app_state,
                    config=harness.config,
                    session_factory=sessions,
                    client_factory=_Client,
                    subjects={
                        "math": dataclasses.replace(SUBJECTS["math"], do_generate=do_generate)
                    },
                    idle_interval=0.05,
                )
            finally:
                await engine.dispose()

        with patch("server.observability.record_generation_outcome"):
            asyncio.run(_run())

    host_thread = threading.Thread(target=_host, daemon=True)
    host_thread.start()
    try:
        # The observer submits, watches until A has ended, then leaves.
        with TestClient(harness.app()) as client:
            run_id = client.post(
                "/api/generate",
                json=_body(stream_version=3),
                headers=harness.headers(harness.owner),
            ).json()["run_id"]
            for _ in range(200):
                seen = client.get(
                    f"/api/runs/{run_id}", headers=harness.headers(harness.owner)
                ).json()
                if seen["questions"][0]["processing"] == "ended":
                    break
                time.sleep(0.05)
            assert seen["questions"][0]["termination_reason"] == "normal"
            assert seen["questions"][1]["termination_reason"] is None

        # Nobody is watching now; B finishes.
        release.set()

        with TestClient(harness.app()) as client:
            for _ in range(200):
                final = client.get(
                    f"/api/runs/{run_id}", headers=harness.headers(harness.owner)
                ).json()
                if final["status"] == "completed":
                    break
                time.sleep(0.05)
        assert final["status"] == "completed"
        assert [q["termination_reason"] for q in final["questions"]] == ["normal", "normal"]
        assert final["questions"][1]["result"]["question"]["id"] == f"q_{run_id}_002"
    finally:
        release.set()
        if "loop" in host_loop:
            host_loop["loop"].call_soon_threadsafe(stop.set)
        host_thread.join(timeout=20)
