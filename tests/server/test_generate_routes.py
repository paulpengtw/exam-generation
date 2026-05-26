"""Tests for generation route request forwarding."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

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
                "&learning_performance=%E7%A4%BE2a-%E2%85%A3-1",
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
