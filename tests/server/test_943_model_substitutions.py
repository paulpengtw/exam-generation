"""Tests for model_substitutions helper and params_json build sites (issue #943).

Tasks covered:
  3.3 – model_substitutions(params, config) computes per-tier substitution info
  3.4 – the key is added to params_json only when non-empty
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.generate.model_substitutions import model_substitutions
from server.generate.models import GenerateParams
from server.models import Base, GenerationLog, User
from src.config import FABLE_DOWNGRADE_TARGET, Config

# ---------------------------------------------------------------------------
# Unit tests for model_substitutions helper
# ---------------------------------------------------------------------------

def make_config(
    *,
    fable_downgrade: bool = True,
    model_execute: str = "gemini-3.1-pro-preview",
    model_verify: str = "claude-opus-4-6",
    model_plan: str = "claude-opus-4-6",
    model_correct: str = "",
) -> Config:
    return Config(
        api_key="x",
        fable_downgrade=fable_downgrade,
        model_execute=model_execute,
        model_verify=model_verify,
        model_plan=model_plan,
        model_correct=model_correct,
    )


class TestModelSubstitutions:
    def test_no_substitution_when_switch_off(self) -> None:
        config = make_config(fable_downgrade=False)
        params = GenerateParams(model_execute="claude-fable-5")
        result = model_substitutions(params, config)
        assert result == {}

    def test_per_request_fable_execute_substituted(self) -> None:
        """Per-request execute=fable → execute is substituted.
        verify and correct inherit execute so they are also substituted.
        plan is separate (not fable) → not substituted.
        """
        config = make_config(fable_downgrade=True, model_verify="", model_correct="")
        params = GenerateParams(model_execute="claude-fable-5")
        result = model_substitutions(params, config)
        assert "execute" in result
        assert result["execute"]["requested"] == "claude-fable-5"
        assert result["execute"]["ran"] == FABLE_DOWNGRADE_TARGET
        # plan is not fable
        assert "plan" not in result

    def test_per_request_fable_verify_substituted_only(self) -> None:
        """Only verify is fable (execute is not) → only verify substituted."""
        config = make_config(fable_downgrade=True)
        params = GenerateParams(model_verify="claude-fable-5")
        result = model_substitutions(params, config)
        assert "verify" in result
        assert result["verify"]["requested"] == "claude-fable-5"
        assert "execute" not in result

    def test_per_request_fable_plan_substituted(self) -> None:
        config = make_config(fable_downgrade=True)
        params = GenerateParams(model_plan="claude-fable-5")
        result = model_substitutions(params, config)
        assert "plan" in result
        assert result["plan"]["requested"] == "claude-fable-5"

    def test_per_request_fable_correct_substituted_only(self) -> None:
        config = make_config(fable_downgrade=True)
        params = GenerateParams(model_correct="claude-fable-5")
        result = model_substitutions(params, config)
        assert "correct" in result
        assert result["correct"]["requested"] == "claude-fable-5"
        assert "execute" not in result

    def test_env_configured_fable_execute_substituted(self) -> None:
        """A Fable model set via env (in config, not per-request) is also reported."""
        config = make_config(
            fable_downgrade=True,
            model_execute="claude-fable-5",
            model_verify="claude-opus-4-6",
            model_correct="claude-opus-4-6",  # explicit non-empty → won't inherit
        )
        params = GenerateParams()  # no per-request overrides
        result = model_substitutions(params, config)
        assert "execute" in result
        assert result["execute"]["requested"] == "claude-fable-5"
        # verify/correct are explicitly set to opus, not fable
        assert "verify" not in result
        assert "correct" not in result

    def test_env_configured_fable_verify_substituted(self) -> None:
        """A Fable model in config.model_verify is reported for verify tier."""
        config = make_config(
            fable_downgrade=True,
            model_verify="claude-fable-5",
        )
        params = GenerateParams()
        result = model_substitutions(params, config)
        assert "verify" in result
        assert result["verify"]["requested"] == "claude-fable-5"
        assert "execute" not in result

    def test_inherited_verify_from_fable_execute(self) -> None:
        """When execute is Fable and verify inherits execute, verify is also reported."""
        config = make_config(
            fable_downgrade=True,
            model_execute="claude-fable-5",
            model_verify="",   # inherits execute
            model_correct="claude-opus-4-6",
        )
        params = GenerateParams()
        result = model_substitutions(params, config)
        # execute is substituted; verify inherits execute → also substituted
        assert "execute" in result
        assert "verify" in result
        assert result["execute"]["requested"] == "claude-fable-5"
        assert result["verify"]["requested"] == "claude-fable-5"

    def test_inherited_correct_from_fable_execute(self) -> None:
        """When execute is Fable and correct inherits execute, correct is also reported."""
        config = make_config(
            fable_downgrade=True,
            model_execute="claude-fable-5",
            model_verify="claude-opus-4-6",
            model_correct="",  # inherits execute
        )
        params = GenerateParams()
        result = model_substitutions(params, config)
        assert "execute" in result
        assert "correct" in result
        assert result["correct"]["requested"] == "claude-fable-5"

    def test_empty_result_for_no_fable_models(self) -> None:
        config = make_config(fable_downgrade=True)
        params = GenerateParams()  # all defaults → no Fable models
        result = model_substitutions(params, config)
        assert result == {}

    def test_multiple_fable_tiers_explicit(self) -> None:
        """Explicit fable on both execute and verify → two entries."""
        config = make_config(
            fable_downgrade=True,
            model_verify="",  # will inherit execute
        )
        params = GenerateParams(
            model_execute="claude-fable-5",
            model_verify="claude-fable-5",
        )
        result = model_substitutions(params, config)
        assert "execute" in result
        assert "verify" in result

    def test_switch_off_no_output_even_with_fable_config(self) -> None:
        """With switch off, Fable models produce no substitution output."""
        config = make_config(
            fable_downgrade=False,
            model_execute="claude-fable-5",
        )
        params = GenerateParams()
        result = model_substitutions(params, config)
        assert result == {}


# ---------------------------------------------------------------------------
# Integration test: params_json build site (simulated as in routes._generate)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session_local():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return SessionLocal


class TestParamsJsonBuildSite:
    """The model_substitutions key is written to params_json only when non-empty."""

    def test_fable_request_stores_model_substitutions(
        self, db_session_local: Any
    ) -> None:
        SessionLocal = db_session_local
        loop = asyncio.new_event_loop()

        user_id = uuid.uuid4()
        config = make_config(
            fable_downgrade=True,
            model_execute="gemini-3.1-pro-preview",
            model_verify="claude-opus-4-6",
            model_correct="claude-opus-4-6",
        )

        params = GenerateParams(model_execute="claude-fable-5")
        subs = model_substitutions(params, config)
        assert subs != {}, "Expected substitutions to be non-empty"

        params_dict = params.model_dump(mode="json")
        # Strip server-derived field first (mirrors production code in routes.py).
        params_dict.pop("model_substitutions", None)
        if subs:
            params_dict["model_substitutions"] = subs

        async def _store() -> dict[str, Any]:
            async with SessionLocal() as session:
                session.add(User(id=user_id, email=f"{user_id}@example.com"))
                await session.flush()
                log = GenerationLog(
                    user_id=user_id,
                    params_json=params_dict,
                    status="completed",
                )
                session.add(log)
                await session.commit()
                await session.refresh(log)
                return log.params_json  # type: ignore[return-value]

        stored = loop.run_until_complete(_store())
        loop.close()
        assert "model_substitutions" in stored
        assert stored["model_substitutions"]["execute"]["requested"] == "claude-fable-5"
        assert stored["model_substitutions"]["execute"]["ran"] == FABLE_DOWNGRADE_TARGET

    def test_non_fable_request_stores_no_model_substitutions(
        self, db_session_local: Any
    ) -> None:
        SessionLocal = db_session_local
        loop = asyncio.new_event_loop()

        user_id = uuid.uuid4()
        config = make_config(fable_downgrade=True)

        params = GenerateParams()  # default → no Fable models
        subs = model_substitutions(params, config)
        assert subs == {}, "Expected no substitutions"

        params_dict = params.model_dump(mode="json")
        # Strip the server-derived field (mirrors production code in routes.py).
        params_dict.pop("model_substitutions", None)
        # subs is empty, so no model_substitutions key added — byte-identical to before.

        async def _store() -> dict[str, Any]:
            async with SessionLocal() as session:
                session.add(User(id=user_id, email=f"{user_id}@example.com"))
                await session.flush()
                log = GenerationLog(
                    user_id=user_id,
                    params_json=params_dict,
                    status="completed",
                )
                session.add(log)
                await session.commit()
                await session.refresh(log)
                return log.params_json  # type: ignore[return-value]

        stored = loop.run_until_complete(_store())
        loop.close()
        assert "model_substitutions" not in stored
