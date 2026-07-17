from __future__ import annotations

from server.config import ServerConfig
from server.models import (
    Base,
    GenerationLog,
    GenerationRecord,
    GenerationStatus,
    MagicLinkToken,
    User,
)


def test_server_config_default_database_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = ServerConfig.from_env()
    assert config.database_url == "sqlite+aiosqlite:///./dev.db"


def test_model_table_names_and_status_values() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "magic_link_tokens",
        "generation_logs",
        "generation_records",
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
    for col_name in ("params_json", "question_json", "image_files"):
        assert cols[col_name].nullable is False, col_name
    assert cols["created_at"].nullable is False
