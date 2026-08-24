"""Route-level tests for the model_verify / model_correct per-request overrides (#375).

Mirrors the style of test_model_selection_routes.py and test_model_selection_service.py.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.models import GenerateParams
from server.generate.service import _build_run_context, generate_question_stream
from server.generate.subjects import SUBJECTS
from server.models import Base, User
from server.rate_limit import limiter
from src.social_studies.schemas import ExamQuestion


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------


def _make_app_and_token(allowed: tuple[str, ...] = ()):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    if not allowed:
        allowed = ("claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-6")
    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        gemini_api_key="x",
        llm_models_allowed=allowed,
    )
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
    token = create_jwt(user_id, "u@example.com", config=config)
    return app, token, engine, config


def _fake_ss_spec(captured: dict):
    """Return a copy of the SS SubjectSpec with do_generate replaced by a capturer."""
    def fake_do_generate(rng_params, overrides, **kwargs):
        captured.setdefault("config_list", []).append(kwargs.get("config"))
        sampled = rng_params
        return ExamQuestion(
            id=kwargs.get("question_id", "q"),
            核心問題="q",
            文本="t",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    return dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)


# ---------------------------------------------------------------------------
# Slice 1: Off-roster model_verify → 422 naming model_verify
# ---------------------------------------------------------------------------


def test_generate_route_rejects_off_roster_model_verify_with_422() -> None:
    """An off-roster model_verify param must be rejected 422 naming 'model_verify'."""
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6", "claude-opus-4-6")
    )

    called = {"count": 0}

    async def fake_stream(params, *_args, **_kwargs):
        called["count"] += 1
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math&model_verify=gpt-4o",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "gpt-4o" in detail
    assert "model_verify" in detail
    assert called["count"] == 0


# ---------------------------------------------------------------------------
# Slice 2: Off-roster model_correct → 422 naming model_correct
# ---------------------------------------------------------------------------


def test_generate_route_rejects_off_roster_model_correct_with_422() -> None:
    """An off-roster model_correct param must be rejected 422 naming 'model_correct'."""
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6", "claude-opus-4-6")
    )

    called = {"count": 0}

    async def fake_stream(params, *_args, **_kwargs):
        called["count"] += 1
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math&model_correct=gpt-4o",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "gpt-4o" in detail
    assert "model_correct" in detail
    assert called["count"] == 0


# ---------------------------------------------------------------------------
# Slice 3: Provider key missing for effective tier model → 422
# ---------------------------------------------------------------------------


def test_generate_route_rejects_verify_model_with_missing_provider_key() -> None:
    """When model_verify resolves to a gemini model but GEMINI_API_KEY is unset → 422.

    The effective_verify_model = model_verify or config.model_verify or effective_execute_model.
    """
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6", "gemini-3.1-pro-preview")
    )
    # Override config so GEMINI_API_KEY is empty
    no_gemini_config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        gemini_api_key="",   # <-- key unset
        llm_models_allowed=("claude-sonnet-4-6", "gemini-3.1-pro-preview"),
    )
    app.dependency_overrides[get_config] = lambda: no_gemini_config

    called = {"count": 0}

    async def fake_stream(params, *_args, **_kwargs):
        called["count"] += 1
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math&model_verify=gemini-3.1-pro-preview",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "GEMINI_API_KEY" in detail
    assert called["count"] == 0


# ---------------------------------------------------------------------------
# Slice 4: Omitted tier params → fallback chain unchanged
# ---------------------------------------------------------------------------


def test_generate_route_absent_tier_params_do_not_change_existing_behavior() -> None:
    """When model_verify and model_correct are omitted, requests are unchanged."""
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token()

    captured: dict = {}

    async def fake_stream(params, *_args, **_kwargs):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
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
    assert captured["params"].model_verify is None
    assert captured["params"].model_correct is None


# ---------------------------------------------------------------------------
# Slice 5: Chaining pin — model_execute overridden per-request; model_verify
#          omitted → effective_verify_model chains off the overridden execute model.
#
# Bug this catches: if effective_verify_model resolved to config.model_execute
# instead of effective_execute_model, the per-request override would be silently lost.
# ---------------------------------------------------------------------------


def test_effective_verify_model_chains_off_overridden_execute_model(tmp_path: Path) -> None:
    """Chaining pin: model_execute override in request → verify model resolves to that model.

    Per-resolution order:
      effective_execute_model = model_execute or config.model_execute
      effective_verify_model  = model_verify or config.model_verify or effective_execute_model

    When model_verify is absent and config.model_verify is empty,
    effective_verify_model must be effective_execute_model (the per-request override),
    NOT config.model_execute (the env-time default).
    """
    config = ServerConfig(
        api_key="x",
        model_execute="claude-sonnet-4-6",   # env default
        model_verify="",                      # no tier override
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_models_allowed=("claude-sonnet-4-6", "claude-opus-4-6"),
    )
    # Request overrides execute but not verify
    params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
        model_execute="claude-opus-4-6",   # per-request override
        model_verify=None,                  # omitted — should chain to overridden execute
    )

    captured: dict = {}

    def fake_do_generate(rng_params, overrides, **kwargs):
        captured["config"] = kwargs.get("config")
        sampled = rng_params
        return ExamQuestion(
            id=kwargs.get("question_id", "q"),
            核心問題="q",
            文本="t",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    fake_spec = dataclasses.replace(
        SUBJECTS["social_studies"], do_generate=fake_do_generate
    )

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

    asyncio.run(collect_events())

    # The baked client_config should carry:
    #   model_execute = "claude-opus-4-6"  (per-request override)
    #   model_verify  = ""                  (empty → chains to execute at call time)
    #
    # Verify the chain: model_execute was overridden; model_verify stays empty
    # so _model_for_purpose("verify") will fall through to the effective execute model.
    assert captured["config"] is not None
    assert captured["config"].model_execute == "claude-opus-4-6"
    # model_verify should remain "" (service merges params.model_verify or config.model_verify)
    assert captured["config"].model_verify == ""

    # Now directly test that _model_for_purpose chains correctly using the baked config
    from src.llm_client import LLMClient
    client = LLMClient(captured["config"])
    # verify purpose: model_verify="" → falls through to effective execute model
    assert client._model_for_purpose("verify") == "claude-opus-4-6"
    assert client._model_for_purpose("correct") == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Slice 6: POST body fields accepted and validated identically (preview route)
# ---------------------------------------------------------------------------


def test_preview_route_rejects_off_roster_model_verify_with_422() -> None:
    """The prompt-preview route must also validate model_verify from POST body."""
    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6", "claude-opus-4-6")
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate/preview?subject=math&model_verify=gpt-4o",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "gpt-4o" in detail
    assert "model_verify" in detail


def test_preview_route_rejects_off_roster_model_correct_with_422() -> None:
    """The prompt-preview route must also validate model_correct from query params."""
    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-sonnet-4-6", "claude-opus-4-6")
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate/preview?subject=math&model_correct=gpt-4o",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "gpt-4o" in detail
    assert "model_correct" in detail


# ---------------------------------------------------------------------------
# Slice 7a: Service seam — baked client_config carries all three distinct models
# ---------------------------------------------------------------------------


def test_build_run_context_bakes_three_distinct_tier_models(tmp_path: Path) -> None:
    """_build_run_context must bake model_execute, model_verify, model_correct
    separately when all three are provided via per-request params.
    """
    import asyncio
    config = ServerConfig(
        api_key="x",
        model_execute="claude-sonnet-4-6",
        model_verify="",
        model_correct="",
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_models_allowed=("claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-6"),
    )
    params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
        model_execute="claude-opus-4-6",
        model_verify="claude-haiku-4-6",
        model_correct="claude-sonnet-4-6",
    )

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    spec = SUBJECTS["social_studies"]
    ctx = _build_run_context(
        params, config,
        SimpleNamespace(html_renderer=None, renderer_pool=None),
        spec=spec,
        session_factory=None,
        generation_log_id=None,
        loop=loop,
        queue=queue,
        html_renderer=None,
    )
    loop.close()

    assert ctx.client_config.model_execute == "claude-opus-4-6"
    assert ctx.client_config.model_verify == "claude-haiku-4-6"
    assert ctx.client_config.model_correct == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Slice 7b: LLMClient._model_for_purpose maps each purpose to the expected model
# ---------------------------------------------------------------------------


def test_llm_client_model_for_purpose_honours_tier_models(tmp_path: Path) -> None:
    """When all three tier models are configured, _model_for_purpose routes correctly."""
    from src.llm_client import LLMClient
    from server.config import ServerConfig

    config = ServerConfig(
        api_key="x",
        model_execute="claude-sonnet-4-6",
        model_verify="claude-opus-4-6",
        model_correct="claude-haiku-4-6",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    client = LLMClient(config)

    # generate purpose → execute model
    assert client._model_for_purpose("generate") == "claude-sonnet-4-6"
    # verify purpose → model_verify
    assert client._model_for_purpose("verify") == "claude-opus-4-6"
    # correct purpose → model_correct
    assert client._model_for_purpose("correct") == "claude-haiku-4-6"


# ---------------------------------------------------------------------------
# Slice 8: Exchange-level assertion — diverged tier models land in LLMExchange.model_used
# ---------------------------------------------------------------------------


def test_diverged_tier_models_persisted_in_llm_exchange_model_used(tmp_path: Path) -> None:
    """Exchange-level: diverged tier models must appear in persisted LLMExchange.model_used.

    Closes the gap left by Slice 7a/7b which assert at the _build_run_context /
    _model_for_purpose seam but never prove the resolved model reaches the DB row.

    Approach: drive generate_question_stream with a do_generate that holds a real
    LLMClient (passed in by the service, observer already wired to ExchangeRecorder)
    and makes three calls through the *real* _model_for_purpose — one per purpose.
    The Anthropic transport is stubbed so no real network calls occur.  Model
    strings in emitted llm_response events come from _model_for_purpose resolution,
    not from literals in this test.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from server.models import LLMExchange
    from src.llm_client import LLMClient

    # Three genuinely distinct roster models — all accepted by both the Anthropic
    # provider (claude-*) and by the effort guard (the inherited effort_execute="medium"
    # is valid for all three: claude-sonnet-4-6 and claude-opus-4-6 are in
    # FOUR_EFFORT_LEVELS while claude-fable-5 is in FIVE_EFFORT_LEVELS, and "medium"
    # appears in both).
    MODEL_EXECUTE = "claude-sonnet-4-6"
    MODEL_VERIFY = "claude-opus-4-6"
    MODEL_CORRECT = "claude-fable-5"

    # ── in-memory SQLite DB ──────────────────────────────────────────────────
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    log_id = uuid.uuid4()

    # ── config ──────────────────────────────────────────────────────────────
    # llm_stream=False → non-streaming path → client.client.messages.create()
    # creative_planning=False → skip planning LLM calls in plan_all_batch_briefs
    config = ServerConfig(
        api_key="x",
        model_execute=MODEL_EXECUTE,
        model_verify=MODEL_VERIFY,
        model_correct=MODEL_CORRECT,
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_exchange_retention_days=30,
        llm_stream=False,
        creative_planning=False,
        llm_models_allowed=(MODEL_EXECUTE, MODEL_VERIFY, MODEL_CORRECT),
    )
    params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
    )

    # ── fake Anthropic transport ─────────────────────────────────────────────
    class _FakeMessages:
        """Stub for LLMClient.client.messages — handles .create() without a network call."""

        def create(self, **kwargs):  # noqa: ANN001, ANN202
            content_block = SimpleNamespace(text='{"ok": true}')
            usage = SimpleNamespace(
                input_tokens=1,
                output_tokens=1,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            )
            return SimpleNamespace(
                content=[content_block],
                stop_reason="end_turn",
                usage=usage,
            )

    # ── fake do_generate ────────────────────────────────────────────────────
    def fake_do_generate(rng_params, overrides, **kwargs):
        """Drive the real LLMClient — observer already wired to ExchangeRecorder.

        Stubs the Anthropic transport then makes one call per purpose so that
        the model field on each emitted llm_response event is produced by
        _model_for_purpose (the real resolution), not by a literal in the test.
        """
        client: LLMClient = kwargs["client"]
        # Replace the live Anthropic client with a stub (observer is already set).
        client.client = SimpleNamespace(messages=_FakeMessages())

        # Three real calls — model resolved by _model_for_purpose per purpose.
        client.generate("system prompt", "user prompt", purpose="generate")
        client.generate("system prompt", "user prompt", purpose="verify")
        client.generate("system prompt", "user prompt", purpose="correct")

        sampled = rng_params
        return ExamQuestion(
            id=kwargs.get("question_id", "q"),
            核心問題="test",
            文本="test text",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            題目=["test question"],
            正確解題分析=["test answer"],
        )

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    # ── drive the service ────────────────────────────────────────────────────
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

    # ── read back rows ───────────────────────────────────────────────────────
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

    # ── assert: resolution → recording end-to-end ───────────────────────────
    assert [(r.purpose, r.model_used) for r in rows] == [
        ("generate", MODEL_EXECUTE),
        ("verify", MODEL_VERIFY),
        ("correct", MODEL_CORRECT),
    ]
