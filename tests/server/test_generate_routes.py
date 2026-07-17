"""Tests for generation route request forwarding."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter


def test_generate_route_forwards_social_studies_options() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured = {}

    async def fake_stream(params, *_args):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        token = create_jwt(user_id, "u@example.com", config=config)
        sq_configs = quote(
            '[{"question_word_limit":80,"option_word_limit":30,'
            '"content_type":"純文字","image_generation_mode":"html",'
            '"question_type":"選擇題","instruction":"聚焦資料判讀"}]',
        )
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?"
                "subject=social_studies"
                "&image_generation_mode=gpt_image"
                "&topic=%E6%B0%A3%E5%80%99%E8%AE%8A%E9%81%B7"
                "&content_type=timeline"
                "&passage=%E7%B4%A0%E6%9D%90"
                "&options=A&options=B"
                "&learning_performance=%E7%A4%BE1b-%E2%85%A3-1"
                "&learning_performance=%E7%A4%BE2a-%E2%85%A3-1"
                "&sub_question_count=3"
                f"&subquestion_configs={sq_configs}",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["params"].subject == "social_studies"
    assert captured["params"].image_generation_mode == "gpt_image"
    assert captured["params"].topic == "氣候變遷"
    assert captured["params"].content_type == "timeline"
    assert captured["params"].passage == "素材"
    assert captured["params"].options == ["A", "B"]
    assert captured["params"].learning_performance == ["社1b-Ⅳ-1", "社2a-Ⅳ-1"]
    assert captured["params"].sub_question_count == 3
    assert "question_word_limit" in captured["params"].subquestion_configs
    assert "question_type" in captured["params"].subquestion_configs
    assert "instruction" in captured["params"].subquestion_configs


def test_subquestion_config_decoder_ignores_malformed_json() -> None:
    from server.generate.service import _decode_subquestion_configs

    raw_configs = (
        '[{"question_word_limit": 80, "question_type": "選擇題", '
        '"instruction": "聚焦資料判讀"}]'
    )
    assert _decode_subquestion_configs(raw_configs) == [
        {
            "question_word_limit": 80,
            "question_type": "選擇題",
            "instruction": "聚焦資料判讀",
        },
    ]
    assert _decode_subquestion_configs("{not-json") is None


def test_generate_route_forwards_natural_sciences_options() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured = {}

    async def fake_stream(params, *_args):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        token = create_jwt(user_id, "u@example.com", config=config)
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?"
                "subject=natural_sciences"
                "&context=Global"
                "&sub_context=Food+security"
                "&science_competency=%E8%83%BD%E5%8A%9B%E4%B8%80%EF%BC%9A%E4%BB%A5%E7%A7%91%E5%AD%B8%E7%9A%84%E8%A7%92%E5%BA%A6%E8%A7%A3%E9%87%8B%E7%8F%BE%E8%B1%A1"
                "&q_type=Constructed+response"
                "&content_type=graphs%2Fcharts%2Ftables"
                "&learning_performance=tr-%E2%85%A3-1",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["params"].subject == "natural_sciences"
    assert captured["params"].context == ["Global"]
    assert captured["params"].sub_context == "Food security"
    assert captured["params"].science_competency == ["能力一：以科學的角度解釋現象"]
    assert captured["params"].q_type == ["Constructed response"]
    assert captured["params"].content_type == "graphs/charts/tables"
    assert captured["params"].learning_performance == ["tr-Ⅳ-1"]


def test_generate_stream_emits_question_update_with_image_base64(tmp_path) -> None:
    from types import SimpleNamespace

    from server.generate import service
    from server.generate.models import GenerateParams
    from src.social_studies.schemas import ExamQuestion

    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = GenerateParams(subject="social_studies", count=1, skip_verify=True)

    def fake_generate_with_corrections(**kwargs):
        question_id = kwargs["question_id"]
        sampled = kwargs["params"]
        question = ExamQuestion(
            id=question_id,
            核心問題="核心問題",
            文本="題組文本",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            閱讀歷程=[p.value for p in sampled.閱讀歷程],
            文本形式=sampled.文本形式.value,
            題目=["題目"],
            正確解題分析=["解析"],
        )
        question.圖片 = f"{question_id}.png"
        (tmp_path / question.圖片).write_bytes(b"draft-png")
        kwargs["on_question_update"](question, "draft")
        return question

    async def collect_events():
        events = []
        async for event in service.generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
        ):
            events.append(event)
        return events

    original = service.ss_generate_with_corrections
    service.ss_generate_with_corrections = fake_generate_with_corrections  # type: ignore[assignment]
    try:
        events = asyncio.run(collect_events())
    finally:
        service.ss_generate_with_corrections = original  # type: ignore[assignment]

    updates = [event for event in events if event["event"] == "question_update"]
    results = [event for event in events if event["event"] == "result"]

    assert len(updates) == 1
    assert updates[0]["data"]["index"] == 0
    assert updates[0]["data"]["phase"] == "draft"
    assert updates[0]["data"]["question"]["image_base64"] == "ZHJhZnQtcG5n"
    assert len(results) == 1
    assert results[0]["data"]["image_base64"] == "ZHJhZnQtcG5n"


def test_generate_route_defaults_coverage_mode_to_balanced() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured: dict = {}

    async def fake_stream(params, *_args):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        token = create_jwt(user_id, "u@example.com", config=config)
        with TestClient(app) as client:
            # No coverage_mode in the query → defaults to "balanced".
            r_default = client.get(
                "/api/generate?subject=social_studies&count=3",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r_default.status_code == 200
            assert captured["params"].coverage_mode == "balanced"

            # Explicit random passes through.
            r_random = client.get(
                "/api/generate?subject=social_studies&count=3&coverage_mode=random",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r_random.status_code == 200
            assert captured["params"].coverage_mode == "random"

            # Unknown value → 422 from Query Literal validation.
            r_bad = client.get(
                "/api/generate?subject=social_studies&count=3&coverage_mode=chaotic",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r_bad.status_code == 422
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())
