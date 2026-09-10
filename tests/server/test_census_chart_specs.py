"""Tests for the generation-record chart_spec census (issue #110 gate evidence)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.census_chart_specs import (
    GATE_SUBJECTS,
    default_database_url,
    load_records,
    main,
    render_census_markdown,
    summarize_census,
)
from server.models import Base, GenerationRecord, User


def test_summarize_census_counts_questions_and_specs_per_subject() -> None:
    rows = [
        ("math", {"chart_spec": {"render_mode": "chart", "chart_type": "histogram", "data": {}}}),
        ("math", {"chart_spec": None}),
        (
            "social_studies",
            {
                "subquestions": [
                    {"chart_spec": {"render_mode": "html", "data": {"rows": [], "columns": []}}}
                ]
            },
        ),
    ]
    result = summarize_census(rows, min_per_subject=2)
    assert result.per_subject["math"].questions == 2
    assert result.per_subject["math"].questions_with_spec == 1
    assert result.per_subject["math"].specs_by_category["chart"] == 1
    assert result.per_subject["social_studies"].specs_by_category["table"] == 1
    assert result.per_subject["social_studies"].specs_by_render_mode["html"] == 1


def test_gate_requires_all_three_subjects_at_threshold() -> None:
    assert GATE_SUBJECTS == ("math", "social_studies", "natural_sciences")
    rows = [("math", {})] * 30 + [("social_studies", {})] * 30
    assert summarize_census(rows, min_per_subject=30).gate_met is False
    rows += [("natural_sciences", {})] * 30
    assert summarize_census(rows, min_per_subject=30).gate_met is True


def test_render_census_markdown_lists_subjects_and_gate_status() -> None:
    rows = [
        ("math", {"chart_spec": {"render_mode": "chart", "chart_type": "histogram", "data": {}}}),
    ]
    md = render_census_markdown(summarize_census(rows, min_per_subject=30))
    assert "| math | 1 | 1 |" in md
    # Subjects with zero rows still get a gate row.
    assert "| natural_sciences | 0 | 0 |" in md
    assert "GATE NOT MET" in md


def _seed_db(tmp_path) -> str:
    """Create an aiosqlite DB with one math generation record; return its URL."""
    url = f"sqlite+aiosqlite:///{tmp_path}/census.db"
    engine = create_async_engine(url)

    async def init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        user_id = uuid.uuid4()
        async with session_local() as s:
            s.add(User(id=user_id, email="census@example.com"))
            s.add(
                GenerationRecord(
                    user_id=user_id,
                    subject="math",
                    question_id="q1",
                    params_json={},
                    question_json={
                        "id": "q1",
                        "chart_spec": {
                            "render_mode": "chart",
                            "chart_type": "histogram",
                            "data": {},
                        },
                    },
                    image_files=[],
                )
            )
            await s.commit()
        await engine.dispose()

    asyncio.run(init())
    return url


def test_default_database_url_reads_env(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert default_database_url() == "sqlite+aiosqlite:///./dev.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./other.db")
    assert default_database_url() == "sqlite+aiosqlite:///./other.db"


def test_load_records_reads_subject_and_question_json(tmp_path) -> None:
    url = _seed_db(tmp_path)
    rows = asyncio.run(load_records(url))
    assert len(rows) == 1
    subject, item = rows[0]
    assert subject == "math"
    assert item["chart_spec"]["chart_type"] == "histogram"


def test_main_prints_markdown_and_check_gates_exit_code(tmp_path, capsys) -> None:
    url = _seed_db(tmp_path)
    # Without --check: always exit 0, markdown printed.
    assert main(["--database-url", url]) == 0
    out = capsys.readouterr().out
    assert "| math | 1 | 1 |" in out
    assert "GATE NOT MET" in out
    # With --check: gate unmet (SS/NS have 0 < 1 questions) -> exit 1.
    assert main(["--database-url", url, "--min-per-subject", "1", "--check"]) == 1
