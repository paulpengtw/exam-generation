"""When generate_question_stream yields a result event, one GenerationRecord is written."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.config import ServerConfig
from server.generate import service
from server.generate.models import GenerateParams
from server.models import Base, GenerationRecord, User
from src.social_studies.schemas import ExamQuestion


def test_generate_stream_writes_generation_record(tmp_path, monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(service, "AsyncSessionLocal", SessionLocal)

    user_id = uuid.uuid4()

    async def add_user():
        async with SessionLocal() as s:
            s.add(User(id=user_id, email="u@example.com"))
            await s.commit()
    asyncio.run(add_user())

    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = GenerateParams(subject="social_studies", count=1, skip_verify=True)

    def fake_generate(**kwargs):
        sampled = kwargs["params"]
        q = ExamQuestion(
            id=kwargs["question_id"],
            核心問題="核心問題",
            文本="文本",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            閱讀歷程=[p.value for p in sampled.閱讀歷程],
            文本形式=sampled.文本形式.value,
            題目=["題目"],
            正確解題分析=["解析"],
        )
        q.圖片 = f"{q.id}.png"
        (tmp_path / q.圖片).write_bytes(b"png")
        return q

    monkeypatch.setattr(service, "ss_generate_with_corrections", fake_generate)

    async def run():
        async for _ in service.generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            user_id=user_id,
            generation_log_id=None,
        ):
            pass
    asyncio.run(run())

    async def check():
        async with SessionLocal() as s:
            rows = (await s.execute(select(GenerationRecord))).scalars().all()
            assert len(rows) == 1
            row = rows[0]
            assert row.user_id == user_id
            assert row.subject == "social_studies"
            assert row.question_id.startswith("ss_")
            assert row.image_files and row.image_files[0].endswith(".png")
            assert "image_base64" not in row.question_json
    asyncio.run(check())
    asyncio.run(engine.dispose())
