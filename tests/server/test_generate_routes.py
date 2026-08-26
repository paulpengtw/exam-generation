"""Tests for generation route request forwarding."""

from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import logging
import threading
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationLog, GenerationRecord, User
from server.rate_limit import limiter


def test_generate_route_returns_422_for_empty_enum_value() -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x")
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/generate?subject=natural_sciences&context=")
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert "context" in response.text


def test_generate_route_rejects_malformed_per_question_params() -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/generate",
                params={"per_question_params": "{not-json"},
            )
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert "per_question_params" in response.text
    assert "valid JSON" in response.text


@pytest.mark.parametrize("count", [11, 100000])
def test_generate_route_rejects_count_above_ten(count: int) -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x")
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/generate", params={"count": count})
    finally:
        limiter.reset()

    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["query", "count"]
    assert error["type"] == "less_than_equal"


def test_generate_route_accepts_count_of_ten() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret", gemini_api_key="x")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured = {}

    async def fake_stream(params, *_args, **_kwargs):
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
                "/api/generate?count=10",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["params"].count == 10


def test_generate_route_forwards_social_studies_options(caplog) -> None:
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
        image_api_key="sk-test-key",
    )
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured = {}

    async def fake_stream(params, *_args, **_kwargs):
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
            gen_routes.logger.addHandler(caplog.handler)
            try:
                with caplog.at_level(logging.INFO, logger="server.generate.routes"):
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
                        "&drawn=learning_content"
                        f"&subquestion_configs={sq_configs}",
                        headers={"Authorization": f"Bearer {token}"},
                    )
            finally:
                gen_routes.logger.removeHandler(caplog.handler)
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
    assert captured["params"].drawn == ["learning_content"]
    assert "question_word_limit" in captured["params"].subquestion_configs
    assert "question_type" in captured["params"].subquestion_configs
    assert "instruction" in captured["params"].subquestion_configs
    request_log = next(
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("generate request")
    )
    assert "params=" in request_log
    assert "social_studies" in request_log
    assert "u@example.com" not in request_log


def test_subquestion_config_decoder_ignores_malformed_json() -> None:
    from server.generate.service import _decode_subquestion_configs

    raw_configs = (
        '[{"question_word_limit": 80, "question_type": "選擇題", "instruction": "聚焦資料判讀"}]'
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

    config = ServerConfig(api_key="x", jwt_secret="test-secret", gemini_api_key="x")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured = {}

    async def fake_stream(params, *_args, **_kwargs):
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
    import dataclasses
    from types import SimpleNamespace

    from server.generate.models import GenerateParams
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
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
            題目=["題目"],
            正確解題分析=["解析"],
        )
        question.圖片 = f"{question_id}.png"
        (tmp_path / question.圖片).write_bytes(b"draft-png")
        kwargs["on_question_update"](question, "draft")
        return question

    def fake_do_generate(rng_params, overrides, **kwargs):
        return fake_generate_with_corrections(params=rng_params, **kwargs)

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    async def collect_events():
        events = []
        async for event in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": fake_spec},
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    updates = [event for event in events if event["event"] == "question_update"]
    results = [event for event in events if event["event"] == "result"]

    assert len(updates) == 1
    assert updates[0]["data"]["index"] == 0
    assert updates[0]["data"]["phase"] == "draft"
    assert updates[0]["data"]["question"]["image_base64"] == "ZHJhZnQtcG5n"
    assert len(results) == 1
    assert results[0]["data"]["image_base64"] == "ZHJhZnQtcG5n"


def test_generate_route_accepts_difficulty_query_param() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret", gemini_api_key="x")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
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
            ok = client.get(
                "/api/generate?subject=math&difficulty=hard",
                headers={"Authorization": f"Bearer {token}"},
            )
            bad = client.get(
                "/api/generate?subject=math&difficulty=insane",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert ok.status_code == 200
    assert captured["params"].difficulty == "hard"
    assert bad.status_code == 422


def test_generate_params_difficulty_defaults_to_none():
    from server.generate.models import GenerateParams

    assert GenerateParams(subject="math").difficulty is None


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

    config = ServerConfig(api_key="x", jwt_secret="test-secret", gemini_api_key="x")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
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


def test_generate_stream_writes_llm_exchange_rows(tmp_path) -> None:
    import dataclasses
    from types import SimpleNamespace

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from server.generate.models import GenerateParams
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from server.models import Base, LLMExchange
    from src.social_studies.schemas import ExamQuestion

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    log_id = uuid.uuid4()
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_exchange_retention_days=30,
    )
    params = GenerateParams(subject="social_studies", count=1, skip_verify=True)

    def fake_generate_with_corrections(**kwargs):
        question_id = kwargs["question_id"]
        sampled = kwargs["params"]
        obs = kwargs["client"].get_observer()
        # Simulate two LLM calls (generator + verifier) coming through the observer.
        obs(
            {
                "type": "llm_request",
                "agent": "generator",
                "purpose": "generate",
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
                "params": {"max_tokens": 8192, "temperature": 0.7},
            }
        )
        obs(
            {
                "type": "llm_response",
                "agent": "generator",
                "purpose": "generate",
                "model": "claude-sonnet-4-6",
                "content": "ok",
                "reasoning": None,
                "usage": {"input": 10, "output": 5, "cache_read": 0, "cache_creation": 0},
            }
        )
        obs(
            {
                "type": "llm_request",
                "agent": "verifier",
                "purpose": "verify",
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "verify"}],
                "params": {"max_tokens": 8192, "temperature": 0.7},
            }
        )
        obs(
            {
                "type": "llm_response",
                "agent": "verifier",
                "purpose": "verify",
                "model": "claude-sonnet-4-6",
                "content": '{"passed": true}',
                "reasoning": None,
                "usage": {"input": 7, "output": 2, "cache_read": 0, "cache_creation": 0},
            }
        )
        return ExamQuestion(
            id=question_id,
            核心問題="c",
            文本="p",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            題目=["q"],
            正確解題分析=["a"],
        )

    def fake_do_generate(rng_params, overrides, **kwargs):
        return fake_generate_with_corrections(params=rng_params, **kwargs)

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    async def _drive() -> None:
        async for _ in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            generation_log_id=log_id,
            subjects={"social_studies": fake_spec},
            session_factory=SessionLocal,
        ):
            pass

    asyncio.run(_drive())

    async def _read() -> list[LLMExchange]:
        async with SessionLocal() as s:
            result = await s.execute(
                select(LLMExchange)
                .where(LLMExchange.generation_log_id == log_id)
                .order_by(LLMExchange.exchange_order)
            )
            return list(result.scalars().all())

    rows = asyncio.run(_read())
    asyncio.run(engine.dispose())

    assert [r.agent for r in rows] == ["generator", "verifier"]
    assert [r.exchange_order for r in rows] == [1, 2]
    assert rows[0].purpose == "generate"
    assert rows[0].prompt_tokens == 10
    assert rows[0].completion_tokens == 5
    assert rows[1].purpose == "verify"
    assert rows[1].model_used == "claude-sonnet-4-6"


def test_generate_stream_shares_recorder_across_batch_workers(tmp_path) -> None:
    """params.count > 1 must share one ExchangeRecorder so exchange_order

    stays unique/contiguous across the whole generation_log, instead of each
    worker restarting its own itertools.count(1) and colliding.
    """
    import dataclasses
    from types import SimpleNamespace

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from server.generate.models import GenerateParams
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from server.models import Base, LLMExchange
    from src.social_studies.schemas import ExamQuestion

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    log_id = uuid.uuid4()
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_exchange_retention_days=30,
    )
    params = GenerateParams(subject="social_studies", count=2, skip_verify=True)

    def fake_generate_with_corrections(**kwargs):
        question_id = kwargs["question_id"]
        sampled = kwargs["params"]
        obs = kwargs["client"].get_observer()
        # Simulate two LLM calls (generator + verifier) per question.
        obs(
            {
                "type": "llm_request",
                "agent": "generator",
                "purpose": "generate",
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
                "params": {"max_tokens": 8192, "temperature": 0.7},
            }
        )
        obs(
            {
                "type": "llm_response",
                "agent": "generator",
                "purpose": "generate",
                "model": "claude-sonnet-4-6",
                "content": "ok",
                "reasoning": None,
                "usage": {"input": 10, "output": 5, "cache_read": 0, "cache_creation": 0},
            }
        )
        obs(
            {
                "type": "llm_request",
                "agent": "verifier",
                "purpose": "verify",
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "verify"}],
                "params": {"max_tokens": 8192, "temperature": 0.7},
            }
        )
        obs(
            {
                "type": "llm_response",
                "agent": "verifier",
                "purpose": "verify",
                "model": "claude-sonnet-4-6",
                "content": '{"passed": true}',
                "reasoning": None,
                "usage": {"input": 7, "output": 2, "cache_read": 0, "cache_creation": 0},
            }
        )
        return ExamQuestion(
            id=question_id,
            核心問題="c",
            文本="p",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            題目=["q"],
            正確解題分析=["a"],
        )

    def fake_do_generate(rng_params, overrides, **kwargs):
        return fake_generate_with_corrections(params=rng_params, **kwargs)

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    async def _drive() -> None:
        async for _ in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            generation_log_id=log_id,
            subjects={"social_studies": fake_spec},
            session_factory=SessionLocal,
        ):
            pass

    asyncio.run(_drive())

    async def _read() -> list[LLMExchange]:
        async with SessionLocal() as s:
            result = await s.execute(
                select(LLMExchange)
                .where(LLMExchange.generation_log_id == log_id)
                .order_by(LLMExchange.exchange_order)
            )
            return list(result.scalars().all())

    rows = asyncio.run(_read())
    asyncio.run(engine.dispose())

    # Two questions x two exchanges each = 4 rows total.
    assert len(rows) == 4
    orders = sorted(r.exchange_order for r in rows)
    assert orders == [1, 2, 3, 4]
    assert len(set(orders)) == len(orders)


def test_generate_stream_shares_figure_policy_recorder_across_batch_workers(
    tmp_path,
) -> None:
    """A batch's GenerationLog must retain policy events from every worker."""
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from server.generate.models import GenerateParams
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from src.common.figure_policy_trail import FigurePolicySpecEntry
    from src.social_studies.schemas import ExamQuestion

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    user_id = uuid.uuid4()
    log_id = uuid.uuid4()

    async def _seed_log() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="figure-batch@example.com"))
            session.add(
                GenerationLog(
                    id=log_id,
                    user_id=user_id,
                    params_json={"subject": "social_studies", "count": 2},
                    status="started",
                )
            )
            await session.commit()

    asyncio.run(_seed_log())

    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = GenerateParams(subject="social_studies", count=2, skip_verify=True)
    emitted_events: list[dict] = []

    def fake_do_generate(rng_params, _overrides, **kwargs):
        question_id = kwargs["question_id"]
        kwargs["on_figure_policy_entry"](
            FigurePolicySpecEntry(
                question_id=question_id,
                label="題幹",
                effective_figure_kind="地圖",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return ExamQuestion(
            id=question_id,
            核心問題="核心問題",
            文本="文本",
            subquestions=[],
            情境=[c.value for c in rng_params.情境],
            題型種類=rng_params.題型種類.value,
            題型=rng_params.題型[0].value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    async def _drive() -> None:
        async for event in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            generation_log_id=log_id,
            subjects={"social_studies": fake_spec},
            session_factory=SessionLocal,
        ):
            emitted_events.append(event)

    asyncio.run(_drive())

    async def _read_log() -> GenerationLog:
        async with SessionLocal() as session:
            row = await session.get(GenerationLog, log_id)
            assert row is not None
            return row

    log = asyncio.run(_read_log())
    asyncio.run(engine.dispose())

    assert log.figure_policy_trail_json is not None
    assert len(log.figure_policy_trail_json) == 2
    assert len({entry["question_id"] for entry in log.figure_policy_trail_json}) == 2
    policy_events = [event for event in emitted_events if event["event"] == "trail"]
    assert len(policy_events) == 2
    assert all(event["data"]["code"] == "figure_policy" for event in policy_events)


def test_generate_route_defers_failed_policy_tombstone_until_workers_finish(tmp_path) -> None:
    """A failed tombstone includes policy events emitted by slower sibling workers."""
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from src.common.figure_policy_trail import FigurePolicySpecEntry
    from src.social_studies.schemas import ExamQuestion

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
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="figure-failure@example.com"))
            await session.commit()

    asyncio.run(add_user())

    failure_started = threading.Event()

    def fake_do_generate(rng_params, _overrides, **kwargs):
        question_id = kwargs["question_id"]
        kwargs["on_figure_policy_entry"](
            FigurePolicySpecEntry(
                question_id=question_id,
                label="題幹",
                effective_figure_kind="地圖",
                timestamp=datetime.now(timezone.utc),
            )
        )
        if question_id.endswith("_001"):
            failure_started.set()
            raise RuntimeError("scripted policy failure")

        assert failure_started.wait(timeout=5)
        time.sleep(0.25)
        kwargs["on_figure_policy_entry"](
            FigurePolicySpecEntry(
                question_id=question_id,
                label="小題 1",
                effective_figure_kind="統計圖",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return ExamQuestion(
            id=question_id,
            核心問題="核心問題",
            文本="文本",
            subquestions=[],
            情境=[c.value for c in rng_params.情境],
            題型種類=rng_params.題型種類.value,
            題型=rng_params.題型[0].value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    async def injected_stream(params, config_arg, app_state, **kwargs):
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        asyncio.get_running_loop().set_default_executor(executor)
        try:
            async for event in generate_question_stream(
                params,
                config_arg,
                app_state,
                subjects={"social_studies": fake_spec},
                **kwargs,
            ):
                yield event
        finally:
            executor.shutdown(wait=True)

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    from server.generate import routes as gen_routes

    original_stream = gen_routes.generate_question_stream
    original_session_factory = gen_routes.AsyncSessionLocal
    gen_routes.generate_question_stream = injected_stream  # type: ignore[assignment]
    gen_routes.AsyncSessionLocal = SessionLocal  # type: ignore[assignment]
    try:
        token = create_jwt(user_id, "figure-failure@example.com", config=config)
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=social_studies&count=2&skip_verify=true",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original_stream  # type: ignore[assignment]
        gen_routes.AsyncSessionLocal = original_session_factory  # type: ignore[assignment]
        limiter.reset()

    assert response.status_code == 200

    async def read_records() -> list[GenerationRecord]:
        async with SessionLocal() as session:
            return list((await session.execute(select(GenerationRecord))).scalars().all())

    rows = asyncio.run(read_records())
    asyncio.run(engine.dispose())

    failed = next(row for row in rows if row.status == "failed")
    assert failed.figure_policy_trail_json is not None
    assert len(failed.figure_policy_trail_json) == 3
    assert len({entry["question_id"] for entry in failed.figure_policy_trail_json}) == 2
    assert {entry["label"] for entry in failed.figure_policy_trail_json} == {"題幹", "小題 1"}


def test_generate_stream_skips_recording_when_retention_zero(tmp_path) -> None:
    import dataclasses
    from types import SimpleNamespace

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from server.generate.models import GenerateParams
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from server.models import Base, LLMExchange
    from src.social_studies.schemas import ExamQuestion

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    log_id = uuid.uuid4()
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_exchange_retention_days=0,
    )
    params = GenerateParams(subject="social_studies", count=1, skip_verify=True)

    def fake_generate_with_corrections(**kwargs):
        obs = kwargs["client"].get_observer()
        # Recorder must not be attached; if it were, this would insert.
        if obs is not None:
            obs(
                {
                    "type": "llm_request",
                    "agent": "generator",
                    "purpose": "generate",
                    "model": "m",
                    "messages": [],
                    "params": {},
                }
            )
            obs(
                {
                    "type": "llm_response",
                    "agent": "generator",
                    "purpose": "generate",
                    "model": "m",
                    "content": "x",
                    "reasoning": None,
                    "usage": {},
                }
            )
        sampled = kwargs["params"]
        return ExamQuestion(
            id=kwargs["question_id"],
            核心問題="c",
            文本="p",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            題目=["q"],
            正確解題分析=["a"],
        )

    def fake_do_generate(rng_params, overrides, **kwargs):
        return fake_generate_with_corrections(params=rng_params, **kwargs)

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    async def _drive() -> None:
        async for _ in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            generation_log_id=log_id,
            subjects={"social_studies": fake_spec},
            session_factory=SessionLocal,
        ):
            pass

    asyncio.run(_drive())

    async def _read_count() -> int:
        async with SessionLocal() as s:
            result = await s.execute(select(LLMExchange))
            return len(list(result.scalars().all()))

    count = asyncio.run(_read_count())
    asyncio.run(engine.dispose())
    assert count == 0


def test_generate_route_rejects_unknown_subject_422() -> None:
    """Unknown subject returns 422 before any DB write (no generation_log row)."""
    from sqlalchemy import select

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

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    try:
        token = create_jwt(user_id, "u@example.com", config=config)
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=typo",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        # Error must name the offending value and list allowed subjects.
        assert "typo" in detail
        assert "math" in detail

        # No generation_log row must have been written.
        async def count_logs() -> int:
            async with SessionLocal() as s:
                result = await s.execute(select(GenerationLog))
                return len(list(result.scalars().all()))

        log_count = asyncio.run(count_logs())
        assert log_count == 0, "generation_log row must not be created for an unknown subject"
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_generate_route_valid_subjects_still_accepted() -> None:
    """math, social_studies, and natural_sciences are all accepted (no regression)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret", gemini_api_key="x")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    async def fake_stream(params, *_args, **_kwargs):
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
            for subject in ("math", "social_studies", "natural_sciences"):
                r = client.get(
                    f"/api/generate?subject={subject}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, f"expected 200 for subject={subject!r}"
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Issue #153 — structured SSE error events (no tracebacks to browser)
# ---------------------------------------------------------------------------


def test_build_sse_error_returns_structured_payload() -> None:
    """build_sse_error must return a dict with stable 'code' and 'message' keys."""
    from server.generate.models import build_sse_error

    payload = build_sse_error("generation_failed", "Question generation failed (ValueError)")
    assert payload["code"] == "generation_failed"
    assert payload["message"] == "Question generation failed (ValueError)"
    assert "Traceback" not in payload["message"]
    assert '  File "' not in payload["message"]


def test_service_worker_error_event_is_structured(tmp_path) -> None:
    """The per-question worker exception path must emit a structured error dict."""
    import dataclasses
    from types import SimpleNamespace

    from server.generate.models import GenerateParams
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS

    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = GenerateParams(subject="social_studies", count=1, skip_verify=True)

    def fake_do_generate(rng_params, overrides, **kwargs):
        raise RuntimeError("boom")

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    async def collect_events():
        events = []
        async for event in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": fake_spec},
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1, f"expected 1 error event, got: {error_events}"
    data = error_events[0]["data"]
    # data must be a dict with code and message
    assert isinstance(data, dict), f"expected dict, got {type(data)}: {data!r}"
    assert data["code"] == "generation_failed"
    assert "message" in data
    assert "Traceback (most recent call last)" not in data["message"]
    assert '  File "' not in data["message"]


def test_route_outer_error_event_is_structured() -> None:
    """The outer event_generator exception path must emit a structured error dict."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret", gemini_api_key="x")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    async def exploding_stream(params, *_args, **_kwargs):
        raise RuntimeError("outer stream boom")
        yield  # make it a generator

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = exploding_stream  # type: ignore[assignment]
    try:
        token = create_jwt(user_id, "u@example.com", config=config)
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    # Parse the SSE stream body to find the error event
    body = response.text
    error_data: str | None = None
    for line in body.splitlines():
        if line.startswith("data:") and "stream_failed" in line:
            error_data = line[len("data:") :].strip()
            break
    assert error_data is not None, f"No stream_failed error event found in: {body!r}"
    import json as _json

    parsed = _json.loads(error_data)
    assert parsed["code"] == "stream_failed"
    assert "Traceback (most recent call last)" not in parsed["message"]
    assert '  File "' not in parsed["message"]


def test_generate_route_persists_one_failed_record_after_prior_success(tmp_path) -> None:
    """A dead run leaves one tombstone beside each successful result emitted first."""
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from src.social_studies.schemas import ExamQuestion

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
        api_key="x", jwt_secret="test-secret", output_dir=tmp_path, data_dir=Path("data")
    )
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    calls = 0

    def fake_do_generate(sampled_params, _overrides, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("scripted LLM failure")
        return ExamQuestion(
            id=kwargs["question_id"],
            核心問題="先完成的核心問題",
            文本="先完成的文本",
            subquestions=[],
            情境=[c.value for c in sampled_params.情境],
            題型種類=sampled_params.題型種類.value,
            題型=sampled_params.題型[0].value,
            題目=["先完成的題目"],
            正確解題分析=["解析"],
        )

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    async def injected_stream(params, config_arg, app_state, **kwargs):
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        asyncio.get_running_loop().set_default_executor(executor)
        try:
            async for event in generate_question_stream(
                params,
                config_arg,
                app_state,
                subjects={"social_studies": fake_spec},
                **kwargs,
            ):
                yield event
        finally:
            executor.shutdown(wait=True)

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    from server.generate import routes as gen_routes

    original = gen_routes.generate_question_stream
    original_session_factory = gen_routes.AsyncSessionLocal
    gen_routes.generate_question_stream = injected_stream  # type: ignore[assignment]
    gen_routes.AsyncSessionLocal = SessionLocal  # type: ignore[assignment]
    try:
        token = create_jwt(user_id, "u@example.com", config=config)
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=social_studies&count=2&skip_verify=true",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        gen_routes.AsyncSessionLocal = original_session_factory  # type: ignore[assignment]
        limiter.reset()

    assert response.status_code == 200
    assert "generation_failed" in response.text

    async def read_records() -> list[GenerationRecord]:
        async with SessionLocal() as session:
            return (
                (await session.execute(
                    select(GenerationRecord).order_by(GenerationRecord.created_at.asc())
                ))
                .scalars()
                .all()
            )

    rows = asyncio.run(read_records())
    assert len(rows) == 2
    assert [row.status for row in rows].count("completed") == 1
    assert [row.status for row in rows].count("failed") == 1
    failed = next(row for row in rows if row.status == "failed")
    assert failed.error == "Question generation failed (RuntimeError)"
    assert failed.params_json["count"] == 2
    assert failed.question_json is None
    asyncio.run(engine.dispose())


def test_generate_route_forwards_reporting_scale_to_natural_sciences() -> None:
    """Slice 5: GET /generate?reporting_scale=4 → params.reporting_scale == '4'."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret", gemini_api_key="x")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured = {}

    async def fake_stream(params, *_args, **_kwargs):
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
                "/api/generate?subject=natural_sciences&reporting_scale=4",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["params"].reporting_scale == "4"


# ---------------------------------------------------------------------------
# Issue #317 — WARNING-level log on 422 validation rejection (no user content)
# ---------------------------------------------------------------------------


def test_generate_422_emits_warning_free_of_user_content(caplog) -> None:
    """A Pydantic-validation 422 emits exactly one WARNING with no user-supplied content.

    Acceptance criteria (issue #317):
    - Exactly one WARNING is emitted from server.generate.routes.
    - The warning does not contain user-supplied values (asserted with a sentinel string).
    - The 422 response body seen by the client is unchanged.
    """
    from server.generate import routes as gen_routes

    SENTINEL = "DISTINCTIVE_MARKER_ISSUE_317_MUST_NOT_APPEAR_IN_LOGS"

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")
    limiter.reset()

    try:
        gen_routes.logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger="server.generate.routes"):
                with TestClient(app, raise_server_exceptions=False) as client:
                    # Malformed JSON with embedded sentinel so any echo would be detectable.
                    response = client.get(
                        "/api/generate",
                        params={"per_question_params": f"{{{SENTINEL}"},
                    )
        finally:
            gen_routes.logger.removeHandler(caplog.handler)
    finally:
        limiter.reset()

    # 422 response body is unchanged — Pydantic detail still present.
    assert response.status_code == 422
    assert "per_question_params" in response.text

    # Exactly one WARNING must be emitted from the route logger.
    route_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "server.generate.routes"
    ]
    assert len(route_warnings) == 1, (
        f"expected 1 WARNING, got {len(route_warnings)}: "
        f"{[r.getMessage() for r in route_warnings]}"
    )

    # The warning must not echo the user-supplied sentinel value.
    assert SENTINEL not in route_warnings[0].getMessage(), (
        f"user-supplied sentinel found in warning: {route_warnings[0].getMessage()!r}"
    )


def test_generate_valid_request_emits_no_validation_warning(caplog) -> None:
    """A valid generate request must not trigger the validation WARNING."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret", gemini_api_key="x")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    async def fake_stream(params, *_args, **_kwargs):
        yield {"event": "done", "data": ""}

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        token = create_jwt(user_id, "u@example.com", config=config)
        gen_routes.logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger="server.generate.routes"):
                with TestClient(app) as client:
                    response = client.get(
                        "/api/generate?subject=math",
                        headers={"Authorization": f"Bearer {token}"},
                    )
        finally:
            gen_routes.logger.removeHandler(caplog.handler)
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200

    # No validation WARNING must be emitted for a valid request.
    route_validation_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and r.name == "server.generate.routes"
        and "validation_error" in r.getMessage()
    ]
    assert len(route_validation_warnings) == 0, (
        f"unexpected validation warning on valid request: "
        f"{[r.getMessage() for r in route_validation_warnings]}"
    )
