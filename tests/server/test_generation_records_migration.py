from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from alembic.config import Config as AlembicConfig
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

PRE_TOMBSTONE_REVISION = "3a3b61d0b77f"


def _alembic_config(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    return cfg


async def _inspect_generation_records(db_url: str) -> tuple[list[dict], list[dict]]:
    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as conn:
            def _inspect(sync_conn):
                inspector = inspect(sync_conn)
                return (
                    inspector.get_columns("generation_records"),
                    inspector.get_indexes("generation_records"),
                )

            return await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


def test_generation_record_migration_creates_nullable_tombstone_schema(
    tmp_path, monkeypatch
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    cfg = _alembic_config(db_url)

    command.upgrade(cfg, "head")

    columns, indexes = asyncio.run(_inspect_generation_records(db_url))
    by_name = {column["name"]: column for column in columns}
    assert {
        "status",
        "error",
        "parent_record_id",
        "annotations_json",
        "verification_trail_json",
    }.issubset(by_name)
    assert by_name["status"]["nullable"] is False
    assert by_name["error"]["nullable"] is True
    assert by_name["parent_record_id"]["nullable"] is True
    assert by_name["annotations_json"]["nullable"] is True
    assert by_name["verification_trail_json"]["nullable"] is True
    assert by_name["question_json"]["nullable"] is True
    assert any("user_id" in index["column_names"] for index in indexes)


def test_generation_record_migration_upgrades_existing_rows_and_round_trips(
    tmp_path, monkeypatch
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'existing.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, PRE_TOMBSTONE_REVISION)

    user_id = uuid.uuid4().hex
    record_id = uuid.uuid4().hex
    engine = create_async_engine(db_url)
    try:
        async def insert_existing_row() -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO users (id, email) VALUES (:id, :email)"
                    ),
                    {"id": user_id, "email": "existing@example.com"},
                )
                await conn.execute(
                    text(
                        "INSERT INTO generation_records "
                        "(id, user_id, subject, question_id, params_json, question_json, "
                        "image_files) "
                        "VALUES (:id, :user_id, :subject, :question_id, :params, "
                        ":question, :images)"
                    ),
                    {
                        "id": record_id,
                        "user_id": user_id,
                        "subject": "math",
                        "question_id": "math_old",
                        "params": json.dumps({"subject": "math", "grade": 8}),
                        "question": json.dumps({"id": "math_old", "題目": ["舊題目"]}),
                        "images": json.dumps([]),
                    },
                )

        asyncio.run(insert_existing_row())
    finally:
        asyncio.run(engine.dispose())


    command.upgrade(cfg, "head")

    engine = create_async_engine(db_url)
    try:
        async def read_upgraded_row() -> tuple[
            str, str, str | None, str | None, str | None
        ]:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT status, question_json, parent_record_id, annotations_json, "
                        "verification_trail_json "
                        "FROM generation_records "
                        "WHERE id = :id"
                    ),
                    {"id": record_id},
                )
                return result.one()

        (
            status,
            question_json,
            parent_record_id,
            annotations_json,
            verification_trail_json,
        ) = asyncio.run(read_upgraded_row())
        assert status == "completed"
        assert json.loads(question_json)["題目"] == ["舊題目"]
        assert parent_record_id is None
        assert annotations_json is None
        assert verification_trail_json is None

        async def insert_failed_tombstone() -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO generation_records "
                        "(id, user_id, subject, question_id, params_json, question_json, "
                        "image_files, status, error) "
                        "VALUES (:id, :user_id, :subject, :question_id, :params, NULL, "
                        ":images, :status, :error)"
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "user_id": user_id,
                        "subject": "math",
                        "question_id": "",
                        "params": "{}",
                        "images": "[]",
                        "status": "failed",
                        "error": "boom",
                    },
                )

        asyncio.run(insert_failed_tombstone())
    finally:
        asyncio.run(engine.dispose())

    command.downgrade(cfg, PRE_TOMBSTONE_REVISION)
    columns, _indexes = asyncio.run(_inspect_generation_records(db_url))
    names = {column["name"] for column in columns}
    assert "status" not in names
    assert "error" not in names
    assert "parent_record_id" not in names
    assert "annotations_json" not in names
    assert "verification_trail_json" not in names
    assert (
        next(column for column in columns if column["name"] == "question_json")["nullable"]
        is False
    )

    engine = create_async_engine(db_url)
    try:
        async def read_downgraded_rows() -> list[str]:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT question_id FROM generation_records")
                )
                return [row[0] for row in result]

        assert asyncio.run(read_downgraded_rows()) == ["math_old"]
    finally:
        asyncio.run(engine.dispose())


def test_generation_record_migration_does_not_backfill_old_failed_generation_logs(
    tmp_path, monkeypatch
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'no-backfill.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, PRE_TOMBSTONE_REVISION)

    user_id = uuid.uuid4().hex
    log_id = uuid.uuid4().hex
    engine = create_async_engine(db_url)
    try:
        async def insert_failed_log() -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                    {"id": user_id, "email": "pre-feature@example.com"},
                )
                await conn.execute(
                    text(
                        "INSERT INTO generation_logs "
                        "(id, user_id, params_json, status, question_id) "
                        "VALUES (:id, :user_id, :params, 'failed', NULL)"
                    ),
                    {"id": log_id, "user_id": user_id, "params": "{}"},
                )

        asyncio.run(insert_failed_log())
    finally:
        asyncio.run(engine.dispose())

    command.upgrade(cfg, "head")

    engine = create_async_engine(db_url)
    try:
        async def read_counts() -> tuple[int, str]:
            async with engine.connect() as conn:
                record_count = (
                    await conn.execute(text("SELECT COUNT(*) FROM generation_records"))
                ).scalar_one()
                log_status = (
                    await conn.execute(
                        text("SELECT status FROM generation_logs WHERE id = :id"),
                        {"id": log_id},
                    )
                ).scalar_one()
                return int(record_count), log_status

        record_count, log_status = asyncio.run(read_counts())
    finally:
        asyncio.run(engine.dispose())

    assert record_count == 0
    assert log_status == "failed"
