"""Issue #907 – At most one saved result per run and question.

Covers:
  - persist_generation_record called twice with same (log_id, question_id) → one row
  - second call returns the same id as the first; no exception raised
  - Sentry not called, backoff_fn never invoked (no retries consumed)
  - first row content preserved (not overwritten by second call)
  - same question_id under two different logs → two rows
  - two saves with generation_log_id=None → two rows (NULLs are distinct)
  - raw INSERT duplicate is rejected by the unique constraint
  - alembic upgrade head adds the constraint on SQLite; downgrade removes it
  - Postgres-marked: constraint exists, double save leaves one row, same id returned
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from alembic.config import Config as AlembicConfig
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from server.generate.models import GenerateParams
from server.generate.persistence import (
    SAVE_MAX_ATTEMPTS,
    _session_dialect_name,
    persist_generation_record,
)
from server.models import Base, GenerationLog, GenerationRecord, User
from tests.plugins.postgres_db import postgres_test_url

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALEMBIC_INI = str(Path(__file__).resolve().parents[2] / "alembic.ini")
_REPO_ROOT = str(Path(__file__).resolve().parents[2])

PREV_REVISION = "d9e5f2a3b7c1"


def _alembic_cfg() -> AlembicConfig:
    return AlembicConfig(_ALEMBIC_INI)


def _alembic_subprocess(cmd: str, revision: str, *, db_url: str) -> None:
    """Run an alembic command in a fresh subprocess so its asyncio.run() call
    does not share an event loop with the test process.  This prevents the
    session-scoped pg_engine fixture's pool connections (bound to the test
    process's current event loop) from being disrupted by Alembic's internal
    asyncio.run() inside env.py.
    """
    env = {**os.environ, "DATABASE_URL": db_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", cmd, revision],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {cmd} {revision!r} failed (rc={result.returncode}):\n"
            f"  stderr: {result.stderr[:800]}\n"
            f"  stdout: {result.stdout[:800]}"
        )


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _create_schema(engine: Any) -> None:
    """Create all ORM tables in the given async engine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _insert_user(engine: Any) -> uuid.UUID:
    """Insert a User row and return its id."""
    user = User(email=f"{uuid.uuid4().hex}@test.example")
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with sf() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _insert_log(engine: Any, user_id: uuid.UUID) -> uuid.UUID:
    """Insert a GenerationLog row and return its id."""
    log = GenerationLog(
        user_id=user_id,
        params_json={"subject": "math", "grade": 8},
        status="started",
    )
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with sf() as session:
        session.add(log)
        await session.commit()
        await session.refresh(log)
        return log.id


def _make_params() -> GenerateParams:
    return GenerateParams(subject="math", skip_verify=True, drawn=["learning_content"])


def _make_payload(question_id: str) -> dict[str, Any]:
    return {"id": question_id, "text": "test question"}


def _make_factory(engine: Any) -> Any:
    """Return a real async session factory for the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _count_rows(engine: Any, log_id: uuid.UUID | None, qid: str) -> int:
    """Count generation_records rows matching (log_id, qid) via ORM query."""
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with sf() as session:
        if log_id is None:
            q = (
                select(func.count())
                .select_from(GenerationRecord)
                .where(
                    GenerationRecord.generation_log_id.is_(None),
                    GenerationRecord.question_id == qid,
                )
            )
        else:
            q = (
                select(func.count())
                .select_from(GenerationRecord)
                .where(
                    GenerationRecord.generation_log_id == log_id,
                    GenerationRecord.question_id == qid,
                )
            )
        return (await session.execute(q)).scalar_one()


async def _has_unique_constraint(engine: Any) -> bool:
    """Return True if the uq_generation_records_log_question constraint exists."""
    async with engine.connect() as conn:
        def _insp(sync_conn: Any) -> list[dict]:
            return inspect(sync_conn).get_unique_constraints("generation_records")

        constraints = await conn.run_sync(_insp)
    return any(
        c.get("name") == "uq_generation_records_log_question" for c in constraints
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_sqlite_engine_factory(tmp_path):
    """Create a real SQLite engine with the full schema from Base.metadata.create_all."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_907.db'}"
    engine = create_async_engine(db_url, echo=False)
    asyncio.run(_create_schema(engine))
    factory = _make_factory(engine)
    yield engine, factory
    asyncio.run(engine.dispose())


@pytest.fixture
def migrated_sqlite_engine(tmp_path, monkeypatch):
    """SQLite engine created via alembic upgrade head (exercises the migration)."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'migrated_907.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    command.upgrade(_alembic_cfg(), "head")
    engine = create_async_engine(db_url, echo=False)
    factory = _make_factory(engine)
    yield engine, factory
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# SQLite: double-save leaves one row, returns same id
# ---------------------------------------------------------------------------


def test_double_save_leaves_one_row(real_sqlite_engine_factory) -> None:
    """Saving the same (log_id, question_id) twice leaves exactly one row."""
    engine, factory = real_sqlite_engine_factory

    async def _run() -> int:
        user_id = await _insert_user(engine)
        log_id = await _insert_log(engine, user_id)
        params = _make_params()
        payload = _make_payload("q_test_907_one")

        await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        return await _count_rows(engine, log_id, "q_test_907_one")

    count = asyncio.run(_run())
    assert count == 1, f"Expected 1 row after double save, got {count}"


def test_double_save_returns_same_id(real_sqlite_engine_factory) -> None:
    """Second save returns the id of the already-existing row."""
    engine, factory = real_sqlite_engine_factory

    async def _run() -> tuple[uuid.UUID | None, uuid.UUID | None]:
        user_id = await _insert_user(engine)
        log_id = await _insert_log(engine, user_id)
        params = _make_params()
        payload = _make_payload("q_test_907_same_id")

        id1 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        id2 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        return id1, id2

    id1, id2 = asyncio.run(_run())
    assert id1 is not None, "First save should return an id"
    assert id2 is not None, "Second save should return an id"
    assert id1 == id2, f"Expected same id on duplicate save; got {id1!r} and {id2!r}"


def test_double_save_no_retries_no_sentry(real_sqlite_engine_factory) -> None:
    """Duplicate save does not consume retries or report to Sentry."""
    engine, factory = real_sqlite_engine_factory
    backoff_calls: list[int] = []

    async def _backoff(attempt: int) -> None:
        backoff_calls.append(attempt)

    async def _run() -> tuple[uuid.UUID | None, uuid.UUID | None]:
        user_id = await _insert_user(engine)
        log_id = await _insert_log(engine, user_id)
        params = _make_params()
        payload = _make_payload("q_test_907_no_retry")

        kwargs: dict[str, Any] = dict(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
            max_attempts=SAVE_MAX_ATTEMPTS,
            backoff_fn=_backoff,
            report_exhaustion=True,
        )
        id1 = await persist_generation_record(**kwargs)
        id2 = await persist_generation_record(**kwargs)
        return id1, id2

    with patch("server.generate.persistence.sentry_sdk") as mock_sentry:
        id1, id2 = asyncio.run(_run())

    assert id1 == id2, "ids should match"
    assert backoff_calls == [], (
        f"backoff_fn must not be called on duplicate save; got: {backoff_calls}"
    )
    assert mock_sentry.capture_exception.call_count == 0, (
        "Sentry must not be called on a duplicate save"
    )


def test_double_save_preserves_first_row_content(real_sqlite_engine_factory) -> None:
    """The first-saved row is not overwritten by the second save."""
    engine, factory = real_sqlite_engine_factory

    async def _run() -> str:
        user_id = await _insert_user(engine)
        log_id = await _insert_log(engine, user_id)

        params1 = _make_params()
        payload1 = {"id": "q_test_907_content", "text": "original text"}

        params2 = GenerateParams(subject="social_studies", skip_verify=True)
        payload2 = {"id": "q_test_907_content", "text": "overwrite attempt"}

        await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params1,
            payload=payload1,
            session_factory=factory,
        )
        await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="social_studies",
            params=params2,
            payload=payload2,
            session_factory=factory,
        )

        sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with sf() as session:
            result = await session.execute(
                select(GenerationRecord.subject).where(
                    GenerationRecord.generation_log_id == log_id,
                    GenerationRecord.question_id == "q_test_907_content",
                )
            )
            return result.scalar_one()

    subject = asyncio.run(_run())
    assert subject == "math", "Subject must come from the FIRST save, not the second"


# ---------------------------------------------------------------------------
# SQLite: NULL log_id rows and different log_ids → no spurious conflicts
# ---------------------------------------------------------------------------


def test_different_logs_produce_two_rows(real_sqlite_engine_factory) -> None:
    """Same question_id under two different logs creates two distinct rows."""
    engine, factory = real_sqlite_engine_factory

    async def _run() -> tuple[uuid.UUID | None, uuid.UUID | None]:
        user_id = await _insert_user(engine)
        log_id_a = await _insert_log(engine, user_id)
        log_id_b = await _insert_log(engine, user_id)
        params = _make_params()
        payload = _make_payload("q_test_907_diff_logs")

        id1 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id_a,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        id2 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id_b,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        return id1, id2

    id1, id2 = asyncio.run(_run())
    assert id1 is not None and id2 is not None
    assert id1 != id2, "Different logs must produce different rows"


def test_null_log_id_two_saves_two_rows(real_sqlite_engine_factory) -> None:
    """Two saves with generation_log_id=None always produce two rows (NULLs are distinct)."""
    engine, factory = real_sqlite_engine_factory

    async def _run() -> tuple[uuid.UUID | None, uuid.UUID | None, int]:
        user_id = await _insert_user(engine)
        params = _make_params()
        payload = _make_payload("q_test_907_null_log")

        id1 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=None,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        id2 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=None,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        count = await _count_rows(engine, None, "q_test_907_null_log")
        return id1, id2, count

    id1, id2, count = asyncio.run(_run())
    assert id1 is not None and id2 is not None
    assert id1 != id2, "NULL log_id saves must never conflict — each row is distinct"
    assert count == 2, f"Expected 2 rows for null-log saves, got {count}"


# ---------------------------------------------------------------------------
# SQLite: raw constraint verification
# ---------------------------------------------------------------------------


def test_constraint_exists_via_create_all(real_sqlite_engine_factory) -> None:
    """The unique constraint is present on the table created by Base.metadata.create_all."""
    engine, _ = real_sqlite_engine_factory
    assert asyncio.run(_has_unique_constraint(engine)), (
        "uq_generation_records_log_question unique constraint missing after create_all"
    )


def test_raw_duplicate_insert_rejected(real_sqlite_engine_factory) -> None:
    """A raw duplicate INSERT at the SQL level is rejected by the constraint."""
    engine, _ = real_sqlite_engine_factory

    async def _run() -> None:
        user_id = await _insert_user(engine)
        log_id = await _insert_log(engine, user_id)
        # Use .hex so SQLite's UUID-as-hex storage matches
        uid_hex = user_id.hex
        lid_hex = log_id.hex

        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO generation_records "
                    "(id, user_id, generation_log_id, subject, question_id, "
                    "params_json, image_files, status) "
                    "VALUES (:id, :uid, :lid, 'math', 'q_dup_raw', '{}', '[]', 'completed')"
                ),
                {"id": uuid.uuid4().hex, "uid": uid_hex, "lid": lid_hex},
            )

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO generation_records "
                        "(id, user_id, generation_log_id, subject, question_id, "
                        "params_json, image_files, status) "
                        "VALUES (:id, :uid, :lid, 'math', 'q_dup_raw', '{}', '[]', 'completed')"
                    ),
                    {"id": uuid.uuid4().hex, "uid": uid_hex, "lid": lid_hex},
                )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# SQLite: alembic migration adds and removes the constraint
# ---------------------------------------------------------------------------


def test_alembic_migration_adds_constraint(tmp_path, monkeypatch) -> None:
    """alembic upgrade head adds the unique constraint."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'up_907.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    cfg = _alembic_cfg()

    # Go to the previous revision — constraint must not exist yet.
    command.upgrade(cfg, PREV_REVISION)
    engine_before = create_async_engine(db_url, echo=False)
    assert not asyncio.run(_has_unique_constraint(engine_before)), (
        "Constraint should not exist before upgrade to e3f6b2c1a4d8"
    )
    asyncio.run(engine_before.dispose())

    # Upgrade to head — constraint must now exist.
    command.upgrade(cfg, "head")
    engine_after = create_async_engine(db_url, echo=False)
    assert asyncio.run(_has_unique_constraint(engine_after)), (
        "Constraint must exist after alembic upgrade to head"
    )
    asyncio.run(engine_after.dispose())


def test_alembic_migration_downgrade_removes_constraint(tmp_path, monkeypatch) -> None:
    """alembic downgrade back to d9e5f2a3b7c1 removes the unique constraint."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'down_907.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    cfg = _alembic_cfg()

    command.upgrade(cfg, "head")
    command.downgrade(cfg, PREV_REVISION)

    engine_down = create_async_engine(db_url, echo=False)
    assert not asyncio.run(_has_unique_constraint(engine_down)), (
        "Constraint should be absent after downgrade to d9e5f2a3b7c1"
    )
    asyncio.run(engine_down.dispose())


# ---------------------------------------------------------------------------
# Via migrated engine — constraint + double save
# ---------------------------------------------------------------------------


def test_migrated_sqlite_double_save_one_row(migrated_sqlite_engine) -> None:
    """After alembic upgrade head, double save returns same id and leaves one row."""
    engine, factory = migrated_sqlite_engine

    async def _run() -> tuple[uuid.UUID | None, uuid.UUID | None, int]:
        user_id = await _insert_user(engine)
        log_id = await _insert_log(engine, user_id)
        params = _make_params()
        payload = _make_payload("q_migrated_907")

        id1 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        id2 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        count = await _count_rows(engine, log_id, "q_migrated_907")
        return id1, id2, count

    id1, id2, count = asyncio.run(_run())
    assert id1 is not None and id2 is not None
    assert id1 == id2
    assert count == 1


# ---------------------------------------------------------------------------
# _session_dialect_name helper
# ---------------------------------------------------------------------------


def test_session_dialect_name_sqlite_and_fake() -> None:
    """_session_dialect_name returns 'sqlite' for a real session; None for a fake."""
    # Real sqlite async_sessionmaker session → "sqlite"
    db_url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_dialect() -> str | None:
        async with factory() as session:
            return _session_dialect_name(session)

    dialect = asyncio.run(_get_dialect())
    asyncio.run(engine.dispose())
    assert dialect == "sqlite", f"Expected 'sqlite', got {dialect!r}"

    # Bare fake session with no bind → None
    class _FakeSession:
        async def commit(self) -> None:
            pass

    assert _session_dialect_name(_FakeSession()) is None


# ---------------------------------------------------------------------------
# Postgres-marked tests
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_postgres_constraint_and_double_save() -> None:
    """Postgres: UniqueConstraint exists; double save leaves one row, returns same id.

    Creates all tables via Base.metadata.create_all (idempotent / checkfirst=True)
    so the test is self-contained and re-runnable.  This exercises both the
    model's __table_args__ constraint declaration and the insert-or-ignore path
    on a real Postgres backend.

    Uses its own NullPool engine rather than the session-scoped pg_engine fixture
    to avoid leaving stale pool connections that break subsequent postgres tests
    running in a different asyncio.run() call.
    """
    pg_url = postgres_test_url()
    if pg_url is None:
        pytest.skip("Postgres not available")

    own_engine = create_async_engine(pg_url, echo=False, poolclass=NullPool)

    async def _run() -> tuple[uuid.UUID | None, uuid.UUID | None, int, bool]:
        # Create tables idempotently (checkfirst=True is default).
        async with own_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        constraint_exists = await _has_unique_constraint(own_engine)

        factory = _make_factory(own_engine)
        user_id = await _insert_user(own_engine)
        log_id = await _insert_log(own_engine, user_id)
        params = _make_params()
        # Use a unique question_id per test run so re-runs don't conflict with
        # leftover data from a TEST_POSTGRES_URL environment.
        payload = _make_payload(f"q_pg907_{uuid.uuid4().hex[:8]}")

        id1 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        id2 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        count = await _count_rows(own_engine, log_id, payload["id"])
        return id1, id2, count, constraint_exists

    try:
        id1, id2, count, constraint_exists = asyncio.run(_run())
    finally:
        asyncio.run(own_engine.dispose())

    assert constraint_exists, (
        "Unique constraint uq_generation_records_log_question missing on Postgres"
    )
    assert id1 is not None and id2 is not None
    assert id1 == id2, f"Expected same id on duplicate save; got {id1!r} and {id2!r}"
    assert count == 1, f"Expected 1 row after duplicate save on Postgres; got {count}"


@pytest.mark.postgres
def test_postgres_alembic_migration_chain() -> None:
    """Postgres: alembic upgrade head → downgrade → upgrade on an isolated throwaway DB.

    Creates a fresh PostgreSQL database, runs the full Alembic migration chain
    there, verifies (a) uq_generation_records_log_question exists after upgrade
    and is absent after downgrade, (b) a second upgrade re-adds it, and (c) the
    double-save path leaves one row and returns the same id.  Drops the throwaway
    database in a finally block.

    Works with both TEST_POSTGRES_URL and the in-process pgserver fixture.

    Design notes:
    - Admin DDL (CREATE/DROP DATABASE) and migration commands each run in their
      own subprocess so their asyncio.run() calls never share an event loop with
      the test process (avoiding pool-connection orphan issues from the session-
      scoped pg_engine fixture).
    - All async database work in the test process runs inside a single
      asyncio.run() call so connections stay within one event loop.
    """
    import asyncpg  # type: ignore[import]

    throwaway_db = f"test_907_{uuid.uuid4().hex[:12]}"

    # Build connection parameters for asyncpg admin operations and the Alembic
    # DATABASE_URL to point at the throwaway database.
    base_url = postgres_test_url()
    if base_url is None:
        pytest.skip("Postgres not available")
    alembic_url = postgres_test_url(database=throwaway_db)

    # Derive asyncpg admin connection kwargs from the base URL.
    if "?host=" in base_url:
        # pgserver: socket directory embedded as ?host=<dir>
        socket_dir = base_url.split("?host=")[1]
        admin_connect_kwargs: dict[str, Any] = {
            "host": socket_dir,
            "user": "postgres",
            "database": "postgres",
        }
    else:
        # TEST_POSTGRES_URL: strip the asyncpg driver prefix for raw asyncpg DSN
        admin_dsn = base_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        admin_connect_kwargs = {"dsn": admin_dsn}

    async def _admin_exec(ddl: str) -> None:
        """Create or drop a database using asyncpg directly (no SQLAlchemy pool)."""
        conn = await asyncpg.connect(**admin_connect_kwargs)
        try:
            await conn.execute(ddl)
        finally:
            await conn.close()

    async def _run_checks_and_save(
        throw_engine: Any,
    ) -> tuple[bool, bool, bool, uuid.UUID | None, uuid.UUID | None, int]:
        """Run all constraint checks and the double-save test in ONE event loop."""
        # Step 1: upgrade to head (subprocess) then check constraint.
        _alembic_subprocess("upgrade", "head", db_url=alembic_url)
        has_after_up = await _has_unique_constraint(throw_engine)

        # Step 2: downgrade (subprocess) then check constraint is gone.
        _alembic_subprocess("downgrade", PREV_REVISION, db_url=alembic_url)
        has_after_down = await _has_unique_constraint(throw_engine)

        # Step 3: upgrade again (subprocess) then verify constraint is back.
        _alembic_subprocess("upgrade", "head", db_url=alembic_url)
        has_after_re_up = await _has_unique_constraint(throw_engine)

        # Step 4: double-save semantics on the fully migrated schema.
        factory = _make_factory(throw_engine)
        user_id = await _insert_user(throw_engine)
        log_id = await _insert_log(throw_engine, user_id)
        params = _make_params()
        payload = _make_payload(f"q_pg907_alembic_{uuid.uuid4().hex[:8]}")
        id1 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        id2 = await persist_generation_record(
            user_id=user_id,
            generation_log_id=log_id,
            subject="math",
            params=params,
            payload=payload,
            session_factory=factory,
        )
        count = await _count_rows(throw_engine, log_id, payload["id"])
        return has_after_up, has_after_down, has_after_re_up, id1, id2, count

    # Create the throwaway database.  Use NullPool so there are no pooled
    # connections surviving between asyncio.run() calls in the test process.
    asyncio.run(_admin_exec(f'CREATE DATABASE "{throwaway_db}"'))
    throw_engine = create_async_engine(alembic_url, echo=False, poolclass=NullPool)
    try:
        has_up, has_down, has_re_up, id1, id2, count = asyncio.run(
            _run_checks_and_save(throw_engine)
        )
    finally:
        asyncio.run(throw_engine.dispose())
        asyncio.run(_admin_exec(f'DROP DATABASE IF EXISTS "{throwaway_db}"'))

    assert has_up, (
        "Constraint uq_generation_records_log_question must exist after "
        "alembic upgrade to head on Postgres"
    )
    assert not has_down, (
        f"Constraint must be absent after alembic downgrade to {PREV_REVISION} on Postgres"
    )
    assert has_re_up, (
        "Constraint must exist after alembic re-upgrade to head on Postgres"
    )
    assert id1 is not None and id2 is not None
    assert id1 == id2, (
        f"Double save must return the same id on Postgres; got {id1!r} vs {id2!r}"
    )
    assert count == 1, (
        f"Double save must leave exactly one row on Postgres; got {count}"
    )
