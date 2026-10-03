"""Issue #908 – 生成執行 schema migrations (detached-generation-runs tasks 2.2–2.4).

SQLite: the migrations upgrade, expose the run columns and the per-question
處理狀態 table, and round-trip through downgrade.

Postgres (marked ``postgres``): the native ``generation_status`` enum gains
queued / running / cancelled, and a 終止原因 written with
``WHERE termination_reason IS NULL`` is recorded exactly once.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")
from alembic.config import Config as AlembicConfig
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

PRE_RUN_REVISION = "d9e5f2a3b7c1"


def _alembic_config() -> AlembicConfig:
    return AlembicConfig(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


async def _inspect(db_url: str) -> dict:
    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as conn:

            def _collect(sync_conn):
                inspector = inspect(sync_conn)
                tables = set(inspector.get_table_names())
                log_columns = {c["name"]: c for c in inspector.get_columns("generation_logs")}
                log_uniques = inspector.get_unique_constraints("generation_logs")
                state_columns = (
                    {c["name"]: c for c in inspector.get_columns("generation_question_states")}
                    if "generation_question_states" in tables
                    else {}
                )
                state_uniques = (
                    inspector.get_unique_constraints("generation_question_states")
                    if "generation_question_states" in tables
                    else []
                )
                return {
                    "tables": tables,
                    "log_columns": log_columns,
                    "log_uniques": log_uniques,
                    "state_columns": state_columns,
                    "state_uniques": state_uniques,
                }

            return await conn.run_sync(_collect)
    finally:
        await engine.dispose()


def test_run_migrations_add_columns_and_question_state_table(tmp_path, monkeypatch) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    command.upgrade(_alembic_config(), "head")

    schema = asyncio.run(_inspect(db_url))
    assert {
        "heartbeat_at",
        "attempts",
        "claimed_by",
        "cancel_requested",
        "submission_key",
    }.issubset(schema["log_columns"])
    assert schema["log_columns"]["attempts"]["nullable"] is False
    assert schema["log_columns"]["cancel_requested"]["nullable"] is False
    assert any(
        u["column_names"] == ["user_id", "submission_key"] for u in schema["log_uniques"]
    )
    assert "generation_question_states" in schema["tables"]
    assert {
        "generation_log_id",
        "question_id",
        "index",
        "processing",
        "current_step",
        "termination_reason",
        "terminal_json",
        "generation_record_id",
        "error",
        "failure_class",
        "updated_at",
    }.issubset(schema["state_columns"])
    assert any(
        u["column_names"] == ["generation_log_id", "question_id"]
        for u in schema["state_uniques"]
    )


def test_run_migrations_round_trip_on_sqlite(tmp_path, monkeypatch) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'roundtrip.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    cfg = _alembic_config()

    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRE_RUN_REVISION)

    schema = asyncio.run(_inspect(db_url))
    assert "generation_question_states" not in schema["tables"]
    assert "attempts" not in schema["log_columns"]
    assert "submission_key" not in schema["log_columns"]

    command.upgrade(cfg, "head")
    schema = asyncio.run(_inspect(db_url))
    assert "generation_question_states" in schema["tables"]


@pytest.mark.postgres
def test_run_migrations_on_postgres_extend_enum_and_record_terminal_once(pg_engine) -> None:
    """Upgrade a fresh schema on real Postgres; check the enum and exactly-once."""
    schema_name = f"mig_{uuid.uuid4().hex[:12]}"

    async def _run() -> None:
        async with pg_engine.connect() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))
            await conn.execute(text(f'SET search_path TO "{schema_name}"'))
            await conn.commit()
            try:
                cfg = _alembic_config()

                def _upgrade(sync_conn) -> None:
                    cfg.attributes["connection"] = sync_conn
                    command.upgrade(cfg, "head")

                await conn.run_sync(_upgrade)
                await conn.commit()

                labels = (
                    await conn.execute(
                        text("SELECT unnest(enum_range(NULL::generation_status))::text")
                    )
                ).scalars().all()
                assert {"queued", "running", "cancelled"}.issubset(set(labels))

                user_id = uuid.uuid4()
                log_id = uuid.uuid4()
                await conn.execute(
                    text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                    {"id": user_id, "email": f"{schema_name}@example.com"},
                )
                await conn.execute(
                    text(
                        "INSERT INTO generation_logs (id, user_id, params_json, status) "
                        "VALUES (:id, :user_id, '{}', 'queued')"
                    ),
                    {"id": log_id, "user_id": user_id},
                )
                await conn.execute(
                    text(
                        "INSERT INTO generation_question_states "
                        "(id, generation_log_id, question_id, index, processing) "
                        "VALUES (:id, :log_id, 'q_1', 0, 'waiting')"
                    ),
                    {"id": uuid.uuid4(), "log_id": log_id},
                )
                first = await conn.execute(
                    text(
                        "UPDATE generation_question_states SET termination_reason='normal' "
                        "WHERE generation_log_id=:log_id AND termination_reason IS NULL"
                    ),
                    {"log_id": log_id},
                )
                second = await conn.execute(
                    text(
                        "UPDATE generation_question_states SET termination_reason='cancelled' "
                        "WHERE generation_log_id=:log_id AND termination_reason IS NULL"
                    ),
                    {"log_id": log_id},
                )
                assert first.rowcount == 1
                assert second.rowcount == 0
                reason = (
                    await conn.execute(
                        text(
                            "SELECT termination_reason FROM generation_question_states "
                            "WHERE generation_log_id=:log_id"
                        ),
                        {"log_id": log_id},
                    )
                ).scalar_one()
                assert reason == "normal"
                await conn.commit()
            finally:
                await conn.rollback()
                await conn.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
                await conn.commit()

    asyncio.run(_run())
