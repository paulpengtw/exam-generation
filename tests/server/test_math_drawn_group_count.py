"""HTTP coverage for math's sampled 題組題 subquestion count."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter
from src.schemas import ExamQuestion, SubQuestion
from tests.server.generate_test_utils import complete_math_query_params


def _result_payload(response_text: str) -> dict:
    for block in response_text.split("\n\n"):
        lines = block.splitlines()
        if "event: result" not in lines:
            continue
        data_line = next(
            line for line in lines
            if line.startswith("data: ") and line != "data: "
        )
        payload = json.loads(data_line.removeprefix("data: "))
        assert isinstance(payload, dict)
        return payload
    raise AssertionError(f"response did not contain a result event: {response_text}")


def test_resolved_math_http_generation_preserves_group_count(tmp_path: Path) -> None:
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
        gemini_api_key="x",
        jwt_secret="test-secret",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    captured_params = []
    captured_items = []

    def fake_math_generate(**kwargs):
        params = kwargs["params"]
        captured_params.append(params)
        is_group = params.題型種類.value == "題組題"
        subquestions = [
            SubQuestion(
                序號=index,
                年級=params.grade,
                題型=params.題型.value,
                題目=f"第{index}小題",
            )
            for index in range(1, (params.sub_question_count or 0) + 1)
        ]
        item = ExamQuestion(
            id=kwargs["question_id"],
            情境=[context.value for context in params.情境],
            題型種類=params.題型種類.value,
            題型=params.題型.value,
            數學思考=[thinking.value for thinking in params.數學思考],
            學習內容=params.學習內容,
            題目=[] if is_group else ["若 x=2，求 3x。"],
            正確解題分析=[] if is_group else ["3×2=6。"],
            subquestions=subquestions,
        )
        captured_items.append(item)
        return item

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    try:
        token = create_jwt(user_id, "u@example.com", config=config)
        with patch(
            "server.generate.subjects._math_generate_with_corrections",
            side_effect=fake_math_generate,
        ):
            with TestClient(app) as client:
                result_payloads = []
                for seed, set_type in ((3, "題組題"), (0, "單一題")):
                    response = client.get(
                        "/api/generate",
                        params=complete_math_query_params(
                            seed=seed, set_type=set_type
                        ),
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    assert response.status_code == 200
                    result_payloads.append(_result_payload(response.text))
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert len(captured_params) == 2
    assert len(captured_items) == 2
    assert len(result_payloads) == 2

    resolved_types = {params.題型種類.value for params in captured_params}
    assert resolved_types == {"單一題", "題組題"}

    for params, item, payload in zip(captured_params, captured_items, result_payloads):
        if params.題型種類.value == "題組題":
            assert type(params.sub_question_count) is int
            assert 3 <= params.sub_question_count <= 7
        assert not (
            item.題型種類.value == "題組題" and not item.subquestions
        )
        assert not (
            payload.get("題型種類") == "題組題" and not payload.get("subquestions")
        )
