from __future__ import annotations

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server import db


def test_shared_async_engine_configures_pre_ping_and_recycling() -> None:
    assert db.engine.pool._pre_ping is True
    assert db.engine.pool._recycle == 300
