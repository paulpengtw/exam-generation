"""Tests for /api/history endpoints."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationRecord, User
from server.rate_limit import limiter


def _setup(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as s:
            yield s

    config = ServerConfig(
        api_key="x", jwt_secret="test-secret", output_dir=tmp_path, data_dir=Path("data")
    )

    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    async def add_users_and_rows():
        async with SessionLocal() as s:
            s.add(User(id=user_a, email="a@example.com"))
            s.add(User(id=user_b, email="b@example.com"))
            await s.flush()
            for i in range(3):
                s.add(GenerationRecord(
                    user_id=user_a,
                    subject="social_studies",
                    question_id=f"ss_a_{i}",
                    params_json={"subject": "social_studies"},
                    question_json={"id": f"ss_a_{i}", "核心問題": f"核心 {i}"},
                    image_files=[],
                ))
            s.add(GenerationRecord(
                user_id=user_b,
                subject="math",
                question_id="q_b_0",
                params_json={"subject": "math"},
                question_json={"id": "q_b_0", "題目": ["題目 0"]},
                image_files=[],
            ))
            await s.commit()
    asyncio.run(add_users_and_rows())

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    token_a = create_jwt(user_a, "a@example.com", config=config)
    return app, config, engine, SessionLocal, token_a, user_a, user_b


def test_list_history_returns_owner_rows_newest_first(tmp_path) -> None:
    app, _config, engine, _sm, token, _ua, _ub = _setup(tmp_path)
    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/history?limit=10",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert isinstance(body["items"], list)
            assert body["total"] == 3
            question_ids = [item["question_id"] for item in body["items"]]
            assert question_ids == ["ss_a_2", "ss_a_1", "ss_a_0"]
            assert all(item["subject"] == "social_studies" for item in body["items"])
            assert "preview" in body["items"][0]
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_list_history_filters_by_subject(tmp_path) -> None:
    app, _config, engine, _sm, token, _ua, _ub = _setup(tmp_path)
    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/history?subject=math",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            assert r.json()["total"] == 0
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def _add_failed_row(SessionLocal, user_id: uuid.UUID) -> str:
    record_id = uuid.uuid4()

    async def insert() -> None:
        async with SessionLocal() as s:
            s.add(GenerationRecord(
                id=record_id,
                user_id=user_id,
                subject="social_studies",
                question_id="",
                params_json={"subject": "social_studies", "topic": "climate"},
                question_json=None,
                image_files=[],
                status="failed",
                error="Question generation failed (RuntimeError)",
            ))
            await s.commit()

    asyncio.run(insert())
    return str(record_id)


def test_list_history_marks_failed_row_and_uses_error_preview(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, user_a, _ub = _setup(tmp_path)
    _add_failed_row(SessionLocal, user_a)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/history?limit=10",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        failed = next(item for item in response.json()["items"] if item["status"] == "failed")
        assert failed["preview"] == "Question generation failed (RuntimeError)"
        assert failed["error"] == "Question generation failed (RuntimeError)"
        assert failed["verified"] is False
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_failed_history_detail_returns_params_and_no_question(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, user_a, _ub = _setup(tmp_path)
    record_id = _add_failed_row(SessionLocal, user_a)
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/history/{record_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["params_json"] == {"subject": "social_studies", "topic": "climate"}
        assert body["error"] == "Question generation failed (RuntimeError)"
        assert body["question_json"] is None
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_failed_history_download_is_not_available(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, user_a, _ub = _setup(tmp_path)
    record_id = _add_failed_row(SessionLocal, user_a)
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/history/{record_id}/download",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 404
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_detail_returns_owned_record_and_embeds_image_when_present(tmp_path) -> None:
    app, config, engine, SessionLocal, token, user_a, _ub = _setup(tmp_path)
    (config.output_dir / "ss_a_0.png").write_bytes(b"png-bytes")

    async def stamp_image():
        async with SessionLocal() as s:
            rows = (await s.execute(
                __import__("sqlalchemy").select(GenerationRecord).where(
                    GenerationRecord.question_id == "ss_a_0"
                )
            )).scalars().all()
            rows[0].image_files = ["ss_a_0.png"]
            rows[0].question_json = {"id": "ss_a_0", "圖片": "ss_a_0.png"}
            await s.commit()
    asyncio.run(stamp_image())

    try:
        with TestClient(app) as client:
            list_r = client.get(
                "/api/history?limit=10",
                headers={"Authorization": f"Bearer {token}"},
            )
            record_id = [
                item for item in list_r.json()["items"]
                if item["question_id"] == "ss_a_0"
            ][0]["id"]

            r = client.get(
                f"/api/history/{record_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["question_json"]["image_base64"] == "cG5nLWJ5dGVz"
            assert body["params_json"]["subject"] == "social_studies"
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_detail_degrades_when_image_file_missing(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, _ua, _ub = _setup(tmp_path)

    async def stamp_missing_image():
        async with SessionLocal() as s:
            rows = (await s.execute(
                __import__("sqlalchemy").select(GenerationRecord).where(
                    GenerationRecord.question_id == "ss_a_0"
                )
            )).scalars().all()
            rows[0].image_files = ["missing.png"]
            rows[0].question_json = {"id": "ss_a_0", "圖片": "missing.png"}
            await s.commit()
    asyncio.run(stamp_missing_image())

    try:
        with TestClient(app) as client:
            list_r = client.get(
                "/api/history",
                headers={"Authorization": f"Bearer {token}"},
            )
            record_id = [
                item for item in list_r.json()["items"]
                if item["question_id"] == "ss_a_0"
            ][0]["id"]

            r = client.get(
                f"/api/history/{record_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert "image_base64" not in body["question_json"]
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_detail_returns_404_for_other_users_record(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, _ua, user_b = _setup(tmp_path)

    async def get_b_id():
        async with SessionLocal() as s:
            rows = (await s.execute(
                __import__("sqlalchemy").select(GenerationRecord).where(
                    GenerationRecord.user_id == user_b
                )
            )).scalars().all()
            return rows[0].id
    record_id = asyncio.run(get_b_id())

    try:
        with TestClient(app) as client:
            r = client.get(
                f"/api/history/{record_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 404
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_download_returns_attachment_with_content_disposition(tmp_path) -> None:
    app, _config, engine, _sm, token, _ua, _ub = _setup(tmp_path)
    try:
        with TestClient(app) as client:
            list_r = client.get(
                "/api/history",
                headers={"Authorization": f"Bearer {token}"},
            )
            record_id = list_r.json()["items"][0]["id"]
            r = client.get(
                f"/api/history/{record_id}/download",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("application/json")
            disp = r.headers["content-disposition"]
            assert "attachment" in disp
            assert ".json" in disp
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())
