from __future__ import annotations

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.models import (
    Base,
    GenerationLog,
    GenerationRecord,
    GenerationRecordStatus,
    GenerationStatus,
    LLMExchange,
    MagicLinkToken,
    User,
)


def test_server_config_default_database_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = ServerConfig.from_env()
    assert config.database_url == "sqlite+aiosqlite:///./dev.db"


def test_server_config_default_llm_exchange_retention_days(monkeypatch) -> None:
    monkeypatch.delenv("LLM_EXCHANGE_RETENTION_DAYS", raising=False)
    config = ServerConfig.from_env()
    assert config.llm_exchange_retention_days == 30


def test_server_config_reads_llm_exchange_retention_days(monkeypatch) -> None:
    monkeypatch.setenv("LLM_EXCHANGE_RETENTION_DAYS", "0")
    config = ServerConfig.from_env()
    assert config.llm_exchange_retention_days == 0
    monkeypatch.setenv("LLM_EXCHANGE_RETENTION_DAYS", "7")
    config = ServerConfig.from_env()
    assert config.llm_exchange_retention_days == 7


def test_model_table_names_and_status_values() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "magic_link_tokens",
        "generation_logs",
        "generation_records",
        "llm_exchanges",
    }
    assert list(GenerationStatus.enums) == ["started", "completed", "failed"]


def test_model_key_columns() -> None:
    assert User.__table__.c.email.unique is True
    assert User.__table__.c.email.nullable is False
    assert MagicLinkToken.__table__.c.token_hash.nullable is False
    assert GenerationLog.__table__.c.user_id.nullable is False


def test_generation_record_columns() -> None:
    cols = GenerationRecord.__table__.c
    assert cols["user_id"].nullable is False
    assert cols["user_id"].index is True
    assert cols["generation_log_id"].nullable is True
    assert str(cols["subject"].type) == "VARCHAR(30)"
    assert str(cols["question_id"].type) == "VARCHAR(100)"
    assert cols["params_json"].nullable is False
    assert cols["question_json"].nullable is True
    assert cols["image_files"].nullable is False
    assert cols["status"].nullable is False
    assert cols["error"].nullable is True
    assert cols["created_at"].nullable is False


def test_generation_record_status_values() -> None:
    assert list(GenerationRecordStatus.enums) == ["completed", "failed", "aborted"]


def test_llm_exchange_columns_and_indexes() -> None:
    cols = LLMExchange.__table__.c
    assert cols.id.primary_key is True
    assert cols.generation_log_id.nullable is False
    assert cols.generation_log_id.index is True
    assert list(cols.generation_log_id.foreign_keys)[0].column.table.name == "generation_logs"
    assert cols.exchange_order.nullable is False
    assert cols.agent.nullable is False
    assert cols.agent.type.length == 50
    assert cols.purpose.nullable is False
    assert cols.purpose.type.length == 50
    assert cols.request_body.nullable is True
    assert cols.response_body.nullable is True
    assert cols.model_used.nullable is False
    assert cols.model_used.type.length == 100
    assert cols.prompt_tokens.nullable is True
    assert cols.completion_tokens.nullable is True
    assert cols.created_at.nullable is False
