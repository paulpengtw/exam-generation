from __future__ import annotations

import asyncio
import uuid

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.models import Base, GenerationRecord, User


def test_generation_record_persists_parent_and_annotations_round_trip(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'generation-records.db'}"
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    user_id = uuid.uuid4()
    annotations = {
        "圈選": [{"start": 2, "end": 5}],
        "修改指示": "把第二題改成生活情境題",
    }

    async def round_trip() -> GenerationRecord | None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            session.add(User(id=user_id, email="annotations@example.com"))
            session.add(
                GenerationRecord(
                    id=parent_id,
                    user_id=user_id,
                    subject="math",
                    question_id="parent-question",
                    params_json={},
                    question_json={},
                    image_files=[],
                )
            )
            session.add(
                GenerationRecord(
                    id=child_id,
                    user_id=user_id,
                    parent_record_id=parent_id,
                    annotations_json=annotations,
                    subject="math",
                    question_id="child-question",
                    params_json={},
                    question_json={},
                    image_files=[],
                )
            )
            await session.commit()

        async with session_factory() as session:
            return (
                await session.execute(
                    select(GenerationRecord).where(GenerationRecord.id == child_id)
                )
            ).scalar_one_or_none()

    try:
        reloaded = asyncio.run(round_trip())
    finally:
        asyncio.run(engine.dispose())

    assert reloaded is not None
    assert reloaded.parent_record_id == parent_id
    assert reloaded.annotations_json == annotations
