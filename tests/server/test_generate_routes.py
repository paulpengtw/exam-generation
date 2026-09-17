"""Tests for generation route request forwarding."""

from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import json
import logging
import threading
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from src.common.resolver import resolve


def _complete_query_params(payload: dict[str, Any]) -> dict[str, Any]:
    """Encode a resolver-complete payload for the GET route's wire shape."""
    completed = resolve(payload).payload
    rows = completed.get("per_question_params")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("subquestion_configs"), list):
                row["subquestion_configs"] = json.dumps(
                    row["subquestion_configs"], ensure_ascii=False
                )
        completed["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    configs = completed.get("subquestion_configs")
    if isinstance(configs, list):
        completed["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)
    return completed


def _resolved_generate_params(payload: dict[str, Any]):
    """Build the service seam's complete model, matching the gated route."""
    from server.generate.models import GenerateParams

    return GenerateParams.model_validate(_complete_query_params(payload))


def test_generate_route_rejects_unresolved_top_level_field() -> None:
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
                params={
                    "subject": "math",
                    "seed": 41,
                    "grade": 8,
                    "context": "個人",
                    "set_type": "單一題",
                    "q_type": "選擇題",
                    "style": "text_only",
                    "math_thinking": "形成",
                    "learning_content": "A-7-7",
                    "learning_performance": "s-IV-12",
                    "core_competency": "數-J-A2",
                },
            )
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"field": "題目內容類型", "code": "unresolved"}
    ]


def test_generate_route_rejects_unresolved_per_question_field() -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")
    rows = [
        {
            "grade": 8,
            "context": ["個人"],
            "set_type": "單一題",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "math_thinking": ["形成"],
            "learning_performance": ["s-IV-12"],
            "core_competency": ["數-J-A2"],
            "content_type": "純文字",
        },
        {
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
        },
    ]
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/generate",
                params={
                    "subject": "math",
                    "seed": 41,
                    "count": 2,
                    "per_question_params": json.dumps(rows, ensure_ascii=False),
                },
            )
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"field": "per_question_params[0].學習內容", "code": "unresolved"}
    ]


def test_generate_route_rejects_unresolved_subquestion_field() -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")
    configs = [
        {
            "reporting_scale": "1",
            "learning_content": ["INa-Ⅳ-1"],
            "learning_performance": ["ti-Ⅳ-1"],
        },
        {
            "question_type": "Simple multiple-choice",
            "reporting_scale": "2",
            "learning_content": ["INa-Ⅳ-1"],
            "learning_performance": ["ti-Ⅳ-1"],
        },
        {
            "question_type": "Simple multiple-choice",
            "reporting_scale": "3",
            "learning_content": ["INa-Ⅳ-1"],
            "learning_performance": ["ti-Ⅳ-1"],
        },
    ]
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/generate",
                params={
                    "subject": "natural_sciences",
                    "seed": 41,
                    "grade": 8,
                    "context": "Personal",
                    "sub_context": "Maintenance of health",
                    "set_type": "題組題",
                    "science_competency": "能力一：以科學的角度解釋現象",
                    "learning_content": "INa-Ⅳ-1",
                    "learning_performance": "ti-Ⅳ-1",
                    "content_type": "純文字",
                    "sub_question_count": 3,
                    "subquestion_configs": json.dumps(configs, ensure_ascii=False),
                },
            )
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"field": "subquestion_configs[0].question_type", "code": "unresolved"}
    ]


def test_preview_route_rejects_unresolved_top_level_field() -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x")
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/generate/preview",
                params={
                    "subject": "math",
                    "seed": 41,
                    "grade": 8,
                    "context": "個人",
                    "set_type": "單一題",
                    "q_type": "選擇題",
                    "style": "text_only",
                    "math_thinking": "形成",
                    "learning_content": "A-7-7",
                    "learning_performance": "s-IV-12",
                    "core_competency": "數-J-A2",
                },
            )
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"field": "題目內容類型", "code": "unresolved"}
    ]


def test_preview_route_includes_social_text_instruction_in_text_prompt() -> None:
    instruction = "請聚焦地方自治中的證據比較"
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_config] = lambda: ServerConfig(
        api_key="x", gemini_api_key="x"
    )
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/generate/preview",
                params=_complete_query_params(
                    {
                        "subject": "social_studies",
                        "seed": 41,
                        "text_instruction": instruction,
                    }
                ),
            )
    finally:
        limiter.reset()

    assert response.status_code == 200, response.text
    text_prompt = next(
        item["user_prompt"]
        for item in response.json()["prompts"]
        if "subquestion_index" not in item
    )
    assert "## 文本出題指示" in text_prompt
    assert instruction in text_prompt


@pytest.mark.parametrize("subject", ["math"])
def test_generate_route_rejects_text_instruction_for_unwired_subjects(subject: str) -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(
        api_key="x", gemini_api_key="x"
    )
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/generate",
                params=_complete_query_params(
                    {
                        "subject": subject,
                        "seed": 41,
                        "text_instruction": "請聚焦證據比較",
                    }
                ),
            )
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert "text_instruction" in response.text


def test_generate_route_reports_incompatible_parent_with_resolver_shape() -> None:
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
                params={
                    "subject": "natural_sciences",
                    "seed": 1,
                    "grade": 8,
                    "context": "Global",
                    "sub_context": "Maintenance of health",
                    "set_type": "單一題",
                    "q_type": "Simple multiple-choice",
                    "science_competency": "能力一：以科學的角度解釋現象",
                    "learning_content": "INa-Ⅳ-1",
                    "learning_performance": "ti-Ⅳ-1",
                    "content_type": "純文字",
                },
            )
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "field": "sub_context",
            "code": "incompatible_parent",
            "parent": "Personal",
        }
    ]


@pytest.mark.parametrize("route", ["/api/generate", "/api/generate/preview"])
def test_generate_and_preview_reject_the_empty_narrowed_civic_domain(route: str) -> None:
    """#835 production reproduction: preview and generation reject the same

    impossible 學習內容 combination /resolve rejects (issue #834's
    production repro, now caught before any downstream call).
    """
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
                route,
                params={
                    "subject": "social_studies",
                    "seed": 1,
                    "grade": 8,
                    "context": "個人",
                    "set_type": "題組題",
                    "subject_filter": "公民與社會",
                    "learning_content": ["公Aa-Ⅳ-1", "公Ab-Ⅳ-1"],
                },
            )
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"field": "learning_content", "code": "no_admitting_parent", "parent": "內容領域"}
    ]


def _accept_narrowed_payload_via_route(
    route: str, partial: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    """Resolve *partial*, submit it to *route*, and re-resolve the result.

    Shared by the #834/#836 "preview and generation accept the narrowed
    payload" reproductions below: builds a throwaway in-memory DB + app with
    ``generate_question_stream``/``build_prompt_previews`` faked out (no LLM
    call), submits the resolver-completed payload as a GET request, and
    returns ``(route_status_code, re_resolved_json)`` so callers can assert
    both the route accepted it and re-resolving is a no-op.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    user = User(id=uuid.uuid4(), email="narrowed-accept@example.com")

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(user)
            await session.commit()

    asyncio.run(add_user())

    config = ServerConfig(api_key="x", jwt_secret="test-secret", gemini_api_key="x")
    from server.generate import routes as gen_routes

    async def fake_stream(params, *_args, **_kwargs):
        yield {"event": "done", "data": ""}

    def fake_previews(params, *_args, **_kwargs):
        return []

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    original_stream = gen_routes.generate_question_stream
    original_previews = gen_routes.build_prompt_previews
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    gen_routes.build_prompt_previews = fake_previews  # type: ignore[assignment]
    limiter.reset()

    try:
        query = _complete_query_params(partial)
        with TestClient(app) as client:
            response = client.get(route, params=query)
            re_resolved = client.post("/api/generate/resolve", json=query)
    finally:
        gen_routes.generate_question_stream = original_stream  # type: ignore[assignment]
        gen_routes.build_prompt_previews = original_previews  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    return response.status_code, re_resolved.json()


@pytest.mark.parametrize("route", ["/api/generate", "/api/generate/preview"])
@pytest.mark.parametrize(
    "partial",
    [
        pytest.param(
            {
                "subject": "social_studies",
                "seed": 1,
                "grade": 7,
                "context": ["個人"],
                "set_type": "題組題",
                "content_type": "純文字",
                "target_surface": "紙本",
                "core_competency": ["社-J-A1"],
                "subject_filter": ["公民與社會"],
                "learning_content": ["公Bn-Ⅳ-3"],
            },
            id="single-subject-blank-domain-narrowed",
        ),
        pytest.param(
            {
                "subject": "social_studies",
                "seed": 1,
                "grade": 7,
                "context": ["個人"],
                "set_type": "題組題",
                "content_type": "純文字",
                "target_surface": "紙本",
                "core_competency": ["社-J-A1"],
                "subject_filter": ["公民與社會", "地理"],
                "learning_content": ["公Bj-Ⅳ-1"],
            },
            id="multi-subject-narrowed-to-single-candidate",
        ),
    ],
)
def test_generate_and_preview_accept_the_834_narrowed_reproductions(
    route: str, partial: dict[str, Any]
) -> None:
    """#834 production reproduction (its own acceptance bullets): preview

    and generation accept the same 科目/內容領域-narrowed payload /resolve
    completes, and re-resolving the completed payload draws nothing new.
    """
    status_code, re_resolved = _accept_narrowed_payload_via_route(route, partial)

    assert status_code == 200
    assert re_resolved["drawn"] == []
    assert re_resolved["cleared"] == []


@pytest.mark.parametrize("route", ["/api/generate", "/api/generate/preview"])
def test_generate_and_preview_accept_the_row_pinned_civic_content(route: str) -> None:
    """#836 acceptance bullet 1: preview and generation accept a payload

    narrowed by a 各小題配置 row's own 學習內容 pin (not just a question-level
    pin), and re-resolving the completed payload draws nothing new.
    """
    partial = {
        "subject": "social_studies",
        "seed": 3,
        "grade": 8,
        "context": ["個人"],
        "set_type": "題組題",
        "content_type": "純文字",
        "target_surface": "紙本",
        "core_competency": ["社-J-A1"],
        "sub_question_count": 3,
        "subquestion_configs": [{}, {"learning_content": ["公Aa-Ⅳ-1"]}, {}],
    }

    status_code, re_resolved = _accept_narrowed_payload_via_route(route, partial)

    assert status_code == 200
    assert re_resolved["payload"]["subject_filter"][0] in {"公民與社會", "跨科"}
    assert re_resolved["payload"]["content_domain"] == "Civic Roles and Identities"
    assert re_resolved["drawn"] == []
    assert re_resolved["cleared"] == []


def test_resolved_payload_passes_generate_and_preview_unchanged() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    user = User(id=uuid.uuid4(), email="resolved@example.com")

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(user)
            await session.commit()

    asyncio.run(add_user())

    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        gemini_api_key="x",
    )
    from server.generate import routes as gen_routes
    from server.generate.models import GenerateParams

    captured: dict[str, GenerateParams] = {}

    async def fake_stream(params, *_args, **_kwargs):
        captured["generate"] = params
        yield {"event": "done", "data": ""}

    def fake_previews(params, *_args, **_kwargs):
        captured["preview"] = params
        return []

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    original_stream = gen_routes.generate_question_stream
    original_previews = gen_routes.build_prompt_previews
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    gen_routes.build_prompt_previews = fake_previews  # type: ignore[assignment]
    limiter.reset()
    try:
        partial = {
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
            "count": 1,
            "skip_verify": True,
        }
        with TestClient(app) as client:
            resolved_response = client.post("/api/generate/resolve", json=partial)
            assert resolved_response.status_code == 200
            submitted = GenerateParams.model_validate(resolved_response.json()["payload"])
            wire_payload = {
                key: value
                for key, value in submitted.model_dump(mode="json").items()
                if value is not None
            }

            generate_response = client.get("/api/generate", params=wire_payload)
            preview_response = client.get("/api/generate/preview", params=wire_payload)
    finally:
        gen_routes.generate_question_stream = original_stream  # type: ignore[assignment]
        gen_routes.build_prompt_previews = original_previews  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert generate_response.status_code == 200, generate_response.text
    assert preview_response.status_code == 200, preview_response.text
    expected = submitted.model_dump(mode="json")
    assert captured["generate"].model_dump(mode="json") == expected
    assert captured["preview"].model_dump(mode="json") == expected


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
                "/api/generate",
                params=_complete_query_params({"subject": "math", "count": 10, "seed": 41}),
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
        query = _complete_query_params(
            {
                "subject": "social_studies",
                "seed": 41,
                "image_generation_mode": "gpt_image",
                "topic": "氣候變遷",
                "content_type": "timeline",
                "passage": "素材",
                "options": ["A", "B"],
                "subject_filter": ["歷史"],
                "learning_content": ["歷Ka-Ⅳ-1"],
                "learning_performance": ["社1b-Ⅳ-1", "社2a-Ⅳ-1"],
                "sub_question_count": 3,
                "drawn": ["learning_content"],
                "subquestion_configs": [
                    {
                        "question_word_limit": 80,
                        "option_word_limit": 30,
                        "content_type": "純文字",
                        "image_generation_mode": "html",
                        "question_type": "選擇題",
                        "instruction": "聚焦資料判讀",
                    }
                ],
            }
        )
        with TestClient(app) as client:
            gen_routes.logger.addHandler(caplog.handler)
            try:
                with caplog.at_level(logging.INFO, logger="server.generate.routes"):
                    response = client.get(
                        "/api/generate",
                        params=query,
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
    assert captured["params"].drawn == ["學習內容"]
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
                "/api/generate",
                params=_complete_query_params(
                    {
                        "subject": "natural_sciences",
                        "seed": 41,
                        "context": ["Global"],
                        "sub_context": "Food security",
                        "science_competency": ["能力一：以科學的角度解釋現象"],
                        "q_type": ["Constructed response"],
                        "content_type": "graphs/charts/tables",
                        "learning_content": ["INa-Ⅳ-1"],
                        "learning_performance": ["tr-Ⅳ-1"],
                    }
                ),
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

    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from src.social_studies.schemas import ExamQuestion

    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = _resolved_generate_params(
        {"subject": "social_studies", "count": 1, "seed": 41, "skip_verify": True}
    )

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
                "/api/generate",
                params=_complete_query_params(
                    {"subject": "math", "seed": 41, "difficulty": "hard"}
                ),
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
                "/api/generate",
                params=_complete_query_params(
                    {"subject": "social_studies", "count": 3, "seed": 41}
                ),
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r_default.status_code == 200
            assert captured["params"].coverage_mode == "balanced"

            # Explicit random passes through.
            r_random = client.get(
                "/api/generate",
                params=_complete_query_params(
                    {
                        "subject": "social_studies",
                        "count": 3,
                        "seed": 41,
                        "coverage_mode": "random",
                    }
                ),
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
    params = _resolved_generate_params(
        {"subject": "social_studies", "count": 1, "seed": 41, "skip_verify": True}
    )

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
    params = _resolved_generate_params(
        {"subject": "social_studies", "count": 2, "seed": 41, "skip_verify": True}
    )

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
    params = _resolved_generate_params(
        {"subject": "social_studies", "count": 2, "seed": 41, "skip_verify": True}
    )
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
        gemini_api_key="x",
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
                "/api/generate",
                params=_complete_query_params(
                    {
                        "subject": "social_studies",
                        "count": 2,
                        "seed": 41,
                        "skip_verify": True,
                    }
                ),
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
    params = _resolved_generate_params(
        {"subject": "social_studies", "count": 1, "seed": 41, "skip_verify": True}
    )

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
                    "/api/generate",
                    params=_complete_query_params({"subject": subject, "seed": 41}),
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

    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS

    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = _resolved_generate_params(
        {"subject": "social_studies", "count": 1, "seed": 41, "skip_verify": True}
    )

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
                "/api/generate",
                params=_complete_query_params({"subject": "math", "seed": 41}),
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
        api_key="x", jwt_secret="test-secret", output_dir=tmp_path, data_dir=Path("data"),
        gemini_api_key="x",
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
                "/api/generate",
                params=_complete_query_params(
                    {
                        "subject": "social_studies",
                        "count": 2,
                        "seed": 41,
                        "skip_verify": True,
                    }
                ),
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
                "/api/generate",
                params=_complete_query_params(
                    {"subject": "natural_sciences", "seed": 41, "reporting_scale": "4"}
                ),
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
                        "/api/generate",
                        params=_complete_query_params({"subject": "math", "seed": 41}),
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


# Issue #644 — per-小題 text_word_limit must be rejected at the HTTP boundary
def test_ss_generate_route_rejects_per_subquestion_text_word_limit() -> None:
    """A per-小題 config row with text_word_limit must produce HTTP 422 for SS.

    Uses a fully-resolved payload (via _complete_query_params) so the
    completeness gate passes and the 422 is attributable exclusively to the
    removed text_word_limit key check in _ss_validate_params (#644).
    """
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")

    # Start from a fully-resolved SS payload so the completeness gate passes.
    params = _complete_query_params({"subject": "social_studies", "seed": 41})
    # Inject text_word_limit into the first subquestion_configs slot after resolution.
    configs = json.loads(params.get("subquestion_configs") or "[]")
    if configs:
        configs[0]["text_word_limit"] = 200
    params["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)

    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/generate", params=params)
    finally:
        limiter.reset()

    assert response.status_code == 422
    # The detail must name the offending path — proving the check in
    # _ss_validate_params fired, not the completeness gate.
    assert "subquestion_configs[0].text_word_limit" in json.dumps(
        response.json(), ensure_ascii=False
    )


def test_ns_generate_route_rejects_per_subquestion_text_word_limit() -> None:
    """A per-小題 config row with text_word_limit must produce HTTP 422 for NS.

    Uses a fully-resolved payload (via _complete_query_params) so the
    completeness gate passes and the 422 is attributable exclusively to the
    removed text_word_limit key check in _ns_validate_params (#644).
    """
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")

    # Start from a fully-resolved NS payload so the completeness gate passes.
    params = _complete_query_params({"subject": "natural_sciences", "seed": 41})
    # Inject text_word_limit into the first subquestion_configs slot after resolution.
    configs = json.loads(params.get("subquestion_configs") or "[]")
    if configs:
        configs[0]["text_word_limit"] = 200
    params["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)

    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/generate", params=params)
    finally:
        limiter.reset()

    assert response.status_code == 422
    # The detail must name the offending path — proving the check in
    # _ns_validate_params fired, not the completeness gate.
    assert "subquestion_configs[0].text_word_limit" in json.dumps(
        response.json(), ensure_ascii=False
    )


# Issue #686 — unknown 各小題配置 keys rejected at HTTP boundary (generic)
def test_ss_generate_route_rejects_unknown_subquestion_config_key() -> None:
    """Any unknown key in a per-小題 config row must produce HTTP 422 for SS (#686)."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")

    params = _complete_query_params({"subject": "social_studies", "seed": 41})
    configs = json.loads(params.get("subquestion_configs") or "[]")
    if configs:
        configs[0]["bogus_key"] = "should_not_be_here"
    params["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)

    limiter.reset()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/generate", params=params)
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert "subquestion_configs[0].bogus_key" in json.dumps(
        response.json(), ensure_ascii=False
    )


def test_ns_generate_route_rejects_unknown_subquestion_config_key() -> None:
    """Any unknown key in a per-小題 config row must produce HTTP 422 for NS (#686)."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")

    params = _complete_query_params({"subject": "natural_sciences", "seed": 41})
    configs = json.loads(params.get("subquestion_configs") or "[]")
    if configs:
        configs[0]["bogus_key"] = "should_not_be_here"
    params["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)

    limiter.reset()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/generate", params=params)
    finally:
        limiter.reset()

    assert response.status_code == 422
    assert "subquestion_configs[0].bogus_key" in json.dumps(
        response.json(), ensure_ascii=False
    )


def test_generate_route_rejects_multiple_unknown_subquestion_config_keys_in_one_response() -> None:
    """Two unknown keys in different config rows both appear in the single 422 (#686)."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")

    params = _complete_query_params({"subject": "social_studies", "seed": 41})
    configs = json.loads(params.get("subquestion_configs") or "[]")
    row_a, row_b = (0, 2) if len(configs) >= 3 else (0, 1) if len(configs) >= 2 else (0, 0)
    if configs:
        configs[row_a]["bogus_key_alpha"] = "bad"
    if len(configs) > row_b and row_b != row_a:
        configs[row_b]["bogus_key_beta"] = "also_bad"
    params["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)

    limiter.reset()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/generate", params=params)
    finally:
        limiter.reset()

    assert response.status_code == 422
    detail_str = json.dumps(response.json(), ensure_ascii=False)
    assert f"subquestion_configs[{row_a}].bogus_key_alpha" in detail_str
    if len(configs) > row_b and row_b != row_a:
        assert f"subquestion_configs[{row_b}].bogus_key_beta" in detail_str


def test_ss_known_subquestion_config_keys_are_not_rejected() -> None:
    """Known per-小題 config keys must not trigger validation errors for SS (#686).

    Uses GenerateParams.model_validate (no LLM provider needed).
    """
    from server.generate.models import GenerateParams

    params = GenerateParams.model_validate(
        _complete_query_params({"subject": "social_studies", "seed": 41})
    )
    assert params.subject == "social_studies"


def test_ns_known_subquestion_config_keys_are_not_rejected() -> None:
    """Known per-小題 config keys must not trigger validation errors for NS (#686).

    Uses GenerateParams.model_validate (no LLM provider needed).
    """
    from server.generate.models import GenerateParams

    params = GenerateParams.model_validate(
        _complete_query_params({"subject": "natural_sciences", "seed": 41})
    )
    assert params.subject == "natural_sciences"
