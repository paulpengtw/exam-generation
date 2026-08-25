from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")
from alembic.config import Config as AlembicConfig

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command


def test_alembic_upgrade_creates_llm_exchanges(tmp_path, monkeypatch) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    cfg = AlembicConfig(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(cfg, "head")

    engine = create_async_engine(db_url)

    async def _inspect() -> dict[str, list[str]]:
        async with engine.begin() as conn:
            def _sync(sync_conn):
                insp = inspect(sync_conn)
                tables = insp.get_table_names()
                cols = [c["name"] for c in insp.get_columns("llm_exchanges")]
                indexes = [i["name"] for i in insp.get_indexes("llm_exchanges")]
                fks = insp.get_foreign_keys("llm_exchanges")
                return tables, cols, indexes, fks
            return await conn.run_sync(_sync)

    tables, cols, indexes, fks = asyncio.run(_inspect())
    asyncio.run(engine.dispose())

    assert "llm_exchanges" in tables
    assert set(cols) == {
        "id",
        "generation_log_id",
        "exchange_order",
        "agent",
        "purpose",
        "request_body",
        "response_body",
        "model_used",
        "prompt_tokens",
        "completion_tokens",
        "created_at",
    }
    assert any("generation_log_id" in i for i in indexes)
    assert any(fk["referred_table"] == "generation_logs" for fk in fks)
