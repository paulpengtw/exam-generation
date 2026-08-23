"""Tests for /api/history endpoints."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
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
                    params_json={
                        "subject": "social_studies",
                        **(
                            {"predrawn_fields": '["learning_content"]'}
                            if i == 0
                            else {}
                        ),
                    },
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


def _add_aborted_row(SessionLocal, user_id: uuid.UUID) -> str:
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
                status="aborted",
                error=None,
            ))
            await s.commit()

    asyncio.run(insert())
    return str(record_id)


def test_aborted_history_payload_has_status_note_params_and_no_download(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, user_a, _ub = _setup(tmp_path)
    record_id = _add_aborted_row(SessionLocal, user_a)
    try:
        with TestClient(app) as client:
            list_response = client.get(
                "/api/history?limit=10",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert list_response.status_code == 200
            item = next(
                item for item in list_response.json()["items"]
                if item["id"] == record_id
            )
            assert item["status"] == "aborted"
            assert item["preview"] == "aborted"
            assert item["error"] is None
            assert item["verified"] is False

            detail_response = client.get(
                f"/api/history/{record_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert detail["status"] == "aborted"
            assert detail["params_json"] == {
                "subject": "social_studies",
                "topic": "climate",
            }
            assert detail["question_json"] is None

            download_response = client.get(
                f"/api/history/{record_id}/download",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert download_response.status_code == 404
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


def test_detail_resolves_a_chain_to_the_latest_record(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, user_a, _ub = _setup(tmp_path)

    async def add_chain() -> tuple[uuid.UUID, uuid.UUID]:
        async with SessionLocal() as s:
            parent = (
                await s.execute(
                    __import__("sqlalchemy").select(GenerationRecord).where(
                        GenerationRecord.user_id == user_a,
                        GenerationRecord.question_id == "ss_a_0",
                    )
                )
            ).scalar_one()
            child_id = uuid.uuid4()
            grandchild_id = uuid.uuid4()
            s.add(
                GenerationRecord(
                    id=child_id,
                    user_id=user_a,
                    parent_record_id=parent.id,
                    subject="social_studies",
                    question_id="ss_a_0_v2",
                    params_json={"subject": "social_studies"},
                    question_json={"id": "ss_a_0_v2", "核心問題": "中間版本"},
                    image_files=[],
                )
            )
            s.add(
                GenerationRecord(
                    id=grandchild_id,
                    user_id=user_a,
                    parent_record_id=child_id,
                    subject="social_studies",
                    question_id="ss_a_0_v3",
                    params_json={"subject": "social_studies"},
                    question_json={"id": "ss_a_0_v3", "核心問題": "最新版本"},
                    image_files=[],
                )
            )
            await s.commit()
            return parent.id, grandchild_id

    parent_id, latest_id = asyncio.run(add_chain())
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/history/{parent_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(latest_id)
        assert body["question_id"] == "ss_a_0_v3"
        assert body["question_json"]["核心問題"] == "最新版本"
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_detail_resolves_the_newest_terminal_branch(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, user_a, _ub = _setup(tmp_path)

    async def add_branching_chain() -> tuple[uuid.UUID, uuid.UUID]:
        async with SessionLocal() as s:
            parent = (
                await s.execute(
                    __import__("sqlalchemy").select(GenerationRecord).where(
                        GenerationRecord.user_id == user_a,
                        GenerationRecord.question_id == "ss_a_0",
                    )
                )
            ).scalar_one()
            branch_a_id = uuid.uuid4()
            branch_b_id = uuid.uuid4()
            latest_id = uuid.uuid4()
            s.add_all(
                [
                    GenerationRecord(
                        id=branch_a_id,
                        user_id=user_a,
                        parent_record_id=parent.id,
                        subject="social_studies",
                        question_id="ss_a_0_branch_a",
                        params_json={"subject": "social_studies"},
                        question_json={"id": "ss_a_0_branch_a", "核心問題": "分支 A"},
                        image_files=[],
                        created_at=datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc),
                    ),
                    GenerationRecord(
                        id=branch_b_id,
                        user_id=user_a,
                        parent_record_id=parent.id,
                        subject="social_studies",
                        question_id="ss_a_0_branch_b",
                        params_json={"subject": "social_studies"},
                        question_json={"id": "ss_a_0_branch_b", "核心問題": "分支 B"},
                        image_files=[],
                        created_at=datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc),
                    ),
                    GenerationRecord(
                        id=latest_id,
                        user_id=user_a,
                        parent_record_id=branch_a_id,
                        subject="social_studies",
                        question_id="ss_a_0_branch_a_v2",
                        params_json={"subject": "social_studies"},
                        question_json={"id": "ss_a_0_branch_a_v2", "核心問題": "分支 A 最新"},
                        image_files=[],
                        created_at=datetime(2026, 8, 24, 2, 0, tzinfo=timezone.utc),
                    ),
                ]
            )
            await s.commit()
            return parent.id, latest_id

    parent_id, latest_id = asyncio.run(add_branching_chain())
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/history/{parent_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(latest_id)
        assert body["question_id"] == "ss_a_0_branch_a_v2"
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


def test_download_includes_saved_request_params_with_predraw_provenance(tmp_path) -> None:
    app, _config, engine, _sm, token, _ua, _ub = _setup(tmp_path)
    try:
        with TestClient(app) as client:
            list_r = client.get(
                "/api/history",
                headers={"Authorization": f"Bearer {token}"},
            )
            record_id = next(
                item["id"]
                for item in list_r.json()["items"]
                if item["question_id"] == "ss_a_0"
            )
            response = client.get(
                f"/api/history/{record_id}/download",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["params_json"]["predrawn_fields"] == '["learning_content"]'
        assert body["id"] == "ss_a_0"
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())
