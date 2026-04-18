from __future__ import annotations

from server.config import ServerConfig
from server.models import Base, GenerationLog, GenerationStatus, MagicLinkToken, User


def test_server_config_default_database_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = ServerConfig.from_env()
    assert config.database_url == "sqlite+aiosqlite:///./dev.db"


def test_model_table_names_and_status_values() -> None:
    assert set(Base.metadata.tables) == {"users", "magic_link_tokens", "generation_logs"}
    assert list(GenerationStatus.enums) == ["started", "completed", "failed"]


def test_model_key_columns() -> None:
    assert User.__table__.c.email.unique is True
    assert User.__table__.c.email.nullable is False
    assert MagicLinkToken.__table__.c.token_hash.nullable is False
    assert GenerationLog.__table__.c.user_id.nullable is False
