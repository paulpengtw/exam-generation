"""Issue #912 – Admission limits and duplicate-submit protection.

Tests cover:
- Submission-key deduplication: repeated (user, key) returns same run (202).
- Queue limit: 6th queued run returns 429 with stable ``code`` field.
- Duplicate-key retry at limit: still returns original run, not 429.
- Race-condition IntegrityError path (mocked).
- Queue position in GET /api/runs/{id}.
- GET /api/runs listing endpoint.
- Frontend 429 handling is tested in the frontend test suite.

Postgres-specific concurrency tests are marked ``@pytest.mark.postgres``
and require the ``TEST_POSTGRES_URL`` environment variable.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.run import QUEUE_LIMIT, QueueLimitError, accept_run
from server.models import Base, GenerationLog, User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MATH_BASE: dict[str, Any] = {
    "subject": "math",
    "seed": 42,
    "grade": 8,
    "context": ["個人"],
    "set_type": "單一題",
    "q_type": ["選擇題"],
    "style": ["text_only"],
    "math_thinking": ["形成"],
    "learning_content": ["A-7-7"],
    "learning_performance": ["s-IV-12"],
    "core_competency": ["數-J-A2"],
    "content_type": "純文字",
    "skip_verify": True,
    "count": 1,
}


def _body(**overrides: Any) -> dict[str, Any]:
    payload = complete_math_query_params(**{k: v for k, v in _MATH_BASE.items() if k != "subject"})
    payload.pop("stream_version", None)
    payload.update(overrides)
    return payload


class _Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.db_url = f"sqlite+aiosqlite:///{tmp_path / 'admission.db'}"
        self.config = ServerConfig(
            api_key="x",
            jwt_secret="test-secret",
            gemini_api_key="x",
            output_dir=tmp_path / "out",
            data_dir=Path("data"),
        )
        self.owner = uuid.uuid4()
        self.other = uuid.uuid4()

        async def _init() -> None:
            engine = create_async_engine(self.db_url)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with sessions() as session:
                session.add_all([
                    User(id=self.owner, email="owner@example.com"),
                    User(id=self.other, email="other@example.com"),
                ])
                await session.commit()
            await engine.dispose()

        asyncio.run(_init())

    def _session_factory(self) -> async_sessionmaker:
        engine = create_async_engine(self.db_url)
        return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    def app(self) -> Any:
        sessions = self._session_factory()

        async def override_session():
            async with sessions() as session:
                yield session

        app = create_app()
        app.dependency_overrides[get_async_session] = override_session
        app.dependency_overrides[get_config] = lambda: self.config
        limiter.reset()
        return app

    def headers(self, user_id: uuid.UUID | None = None) -> dict[str, str]:
        uid = user_id if user_id is not None else self.owner
        email = "owner@example.com" if uid == self.owner else "other@example.com"
        return {
            "Authorization": f"Bearer {create_jwt(uid, email, config=self.config)}",
            "X-Frontend-Build-ID": "test-build-id",
        }

    async def _submit_n_queued(
        self, sessions: async_sessionmaker, user_id: uuid.UUID, count: int
    ) -> list[str]:
        """Insert ``count`` queued runs directly (bypassing routes)."""
        from server.generate.models import GenerateParams
        from server.generate.run import accept_run

        run_ids = []
        params = GenerateParams(**{k: v for k, v in complete_math_query_params(
            **{k: v for k, v in _MATH_BASE.items() if k != "subject"}
        ).items() if k != "stream_version"})
        for _ in range(count):
            async with sessions() as session:
                ar = await accept_run(params, user_id, session=session)
                run_ids.append(ar.run_id)
        return run_ids


@pytest.fixture()
def harness(tmp_path: Path) -> _Harness:
    return _Harness(tmp_path)


# ---------------------------------------------------------------------------
# Submission-key deduplication
# ---------------------------------------------------------------------------


def test_duplicate_submission_key_returns_same_run(harness: _Harness) -> None:
    """Repeated (user, submission_key) returns the original run without creating a second."""
    key = str(uuid.uuid4())
    body = _body(stream_version=3, submission_key=key)
    with TestClient(harness.app()) as client:
        r1 = client.post("/api/generate", json=body, headers=harness.headers())
        r2 = client.post("/api/generate", json=body, headers=harness.headers())

    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["run_id"] == r2.json()["run_id"], "Both responses must carry the SAME run_id"


def test_different_keys_create_different_runs(harness: _Harness) -> None:
    body1 = _body(stream_version=3, submission_key=str(uuid.uuid4()))
    body2 = _body(stream_version=3, submission_key=str(uuid.uuid4()))
    with TestClient(harness.app()) as client:
        r1 = client.post("/api/generate", json=body1, headers=harness.headers())
        r2 = client.post("/api/generate", json=body2, headers=harness.headers())

    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["run_id"] != r2.json()["run_id"]


def test_missing_key_accepted_without_dedup(harness: _Harness) -> None:
    """A request without submission_key is accepted and creates a new run each time."""
    body = _body(stream_version=3)  # no submission_key
    with TestClient(harness.app()) as client:
        r1 = client.post("/api/generate", json=body, headers=harness.headers())
        r2 = client.post("/api/generate", json=body, headers=harness.headers())

    assert r1.status_code == 202
    assert r2.status_code == 202
    # No dedup → two different runs
    assert r1.json()["run_id"] != r2.json()["run_id"]


def test_same_key_different_users_creates_different_runs(harness: _Harness) -> None:
    key = str(uuid.uuid4())
    body = _body(stream_version=3, submission_key=key)
    with TestClient(harness.app()) as client:
        r1 = client.post("/api/generate", json=body, headers=harness.headers(harness.owner))
        r2 = client.post("/api/generate", json=body, headers=harness.headers(harness.other))

    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["run_id"] != r2.json()["run_id"]


# ---------------------------------------------------------------------------
# Queue limit (HTTP layer)
# ---------------------------------------------------------------------------


def test_sixth_run_returns_429(harness: _Harness) -> None:
    """QUEUE_LIMIT queued runs → the next submission returns 429."""
    sessions = harness._session_factory()
    # Submit exactly QUEUE_LIMIT runs
    asyncio.run(harness._submit_n_queued(sessions, harness.owner, QUEUE_LIMIT))

    body = _body(stream_version=3, submission_key=str(uuid.uuid4()))
    with TestClient(harness.app()) as client:
        r = client.post("/api/generate", json=body, headers=harness.headers())

    assert r.status_code == 429
    data = r.json()
    assert data["code"] == "queue_limit_reached", f"Expected stable code, got {data}"
    assert isinstance(data["detail"], str) and data["detail"]


def test_429_creates_no_new_run(harness: _Harness) -> None:
    sessions = harness._session_factory()
    asyncio.run(harness._submit_n_queued(sessions, harness.owner, QUEUE_LIMIT))

    body = _body(stream_version=3, submission_key=str(uuid.uuid4()))
    with TestClient(harness.app()) as client:
        before = len(client.get("/api/runs", headers=harness.headers()).json())
        client.post("/api/generate", json=body, headers=harness.headers())
        after = len(client.get("/api/runs", headers=harness.headers()).json())

    assert after == before, "429 must not create a new run"


def test_dedup_retry_at_limit_returns_original_run(harness: _Harness) -> None:
    """A duplicate-key retry when at the limit returns the original run, NOT 429."""
    # First, fill the queue to QUEUE_LIMIT - 1
    sessions = harness._session_factory()
    asyncio.run(harness._submit_n_queued(sessions, harness.owner, QUEUE_LIMIT - 1))

    # Submit one more run with a specific key (now at limit)
    key = str(uuid.uuid4())
    body = _body(stream_version=3, submission_key=key)
    with TestClient(harness.app()) as client:
        r1 = client.post("/api/generate", json=body, headers=harness.headers())
        assert r1.status_code == 202
        original_run_id = r1.json()["run_id"]

        # Now queue is at QUEUE_LIMIT. Retrying with the same key must return
        # the original run (dedup path), not 429.
        r2 = client.post("/api/generate", json=body, headers=harness.headers())

    assert r2.status_code == 202, f"Dedup retry must return 202, got {r2.status_code}: {r2.text}"
    assert r2.json()["run_id"] == original_run_id


# ---------------------------------------------------------------------------
# Queue position in GET /api/runs/{id}
# ---------------------------------------------------------------------------


def test_queue_position_for_first_queued_run_is_zero(harness: _Harness) -> None:
    with TestClient(harness.app()) as client:
        r = client.post(
            "/api/generate",
            json=_body(stream_version=3),
            headers=harness.headers(),
        )
        run_id = r.json()["run_id"]
        snap = client.get(f"/api/runs/{run_id}", headers=harness.headers()).json()

    assert snap["status"] == "queued"
    assert snap["queue_position"] == 0


def test_queue_position_increases_for_later_runs(harness: _Harness) -> None:
    run_ids = []
    with TestClient(harness.app()) as client:
        for _ in range(3):
            r = client.post(
                "/api/generate",
                json=_body(stream_version=3),
                headers=harness.headers(),
            )
            assert r.status_code == 202
            run_ids.append(r.json()["run_id"])

        positions = []
        for rid in run_ids:
            snap = client.get(f"/api/runs/{rid}", headers=harness.headers()).json()
            positions.append(snap["queue_position"])

    assert positions == [0, 1, 2], f"Expected [0,1,2], got {positions}"


def test_queue_position_is_null_when_not_queued(harness: _Harness) -> None:
    """Completed and failed runs have queue_position == None."""
    sessions = harness._session_factory()

    async def _make_completed_run() -> str:
        async with sessions() as session:
            from server.generate.models import GenerateParams
            params = GenerateParams(**{k: v for k, v in complete_math_query_params(
                **{k: v for k, v in _MATH_BASE.items() if k != "subject"}
            ).items() if k != "stream_version"})
            ar = await accept_run(params, harness.owner, session=session)
            # Mark as completed directly
            log = (await session.execute(
                select(GenerationLog).where(GenerationLog.id == uuid.UUID(ar.run_id))
            )).scalar_one()
            log.status = "completed"
            await session.commit()
            return ar.run_id

    run_id = asyncio.run(_make_completed_run())

    with TestClient(harness.app()) as client:
        snap = client.get(f"/api/runs/{run_id}", headers=harness.headers()).json()

    assert snap["queue_position"] is None


# ---------------------------------------------------------------------------
# GET /api/runs listing endpoint
# ---------------------------------------------------------------------------


def test_list_runs_returns_owner_runs_newest_first(harness: _Harness) -> None:
    with TestClient(harness.app()) as client:
        for i in range(3):
            client.post(
                "/api/generate",
                json=_body(stream_version=3),
                headers=harness.headers(),
            )
        rows = client.get("/api/runs", headers=harness.headers()).json()

    assert len(rows) == 3
    # Newest first: queue_position should be 2, 1, 0 in order
    assert rows[0]["queue_position"] == 2
    assert rows[1]["queue_position"] == 1
    assert rows[2]["queue_position"] == 0


def test_list_runs_is_empty_for_new_user(harness: _Harness) -> None:
    with TestClient(harness.app()) as client:
        rows = client.get("/api/runs", headers=harness.headers()).json()
    assert rows == []


def test_list_runs_is_owner_only(harness: _Harness) -> None:
    """Owner's runs are NOT visible to another user."""
    with TestClient(harness.app()) as client:
        client.post(
            "/api/generate",
            json=_body(stream_version=3),
            headers=harness.headers(harness.owner),
        )
        other_rows = client.get("/api/runs", headers=harness.headers(harness.other)).json()

    assert other_rows == []


# ---------------------------------------------------------------------------
# Unit-level accept_run tests (no HTTP)
# ---------------------------------------------------------------------------


def test_accept_run_unit_dedup() -> None:
    """accept_run returns the same AcceptedRun for a repeated (user, key)."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def _run(tmp_path_str: str) -> None:
        db_url = f"sqlite+aiosqlite:///{tmp_path_str}/unit.db"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        user_id = uuid.uuid4()
        async with sessions() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

        from server.generate.models import GenerateParams
        params = GenerateParams(**{k: v for k, v in complete_math_query_params(
            **{k: v for k, v in _MATH_BASE.items() if k != "subject"}
        ).items() if k != "stream_version"}, submission_key="abc-key")

        async with sessions() as s1:
            ar1 = await accept_run(params, user_id, session=s1)
        async with sessions() as s2:
            ar2 = await accept_run(params, user_id, session=s2)
        assert ar1.run_id == ar2.run_id, "Dedup must return same run_id"
        await engine.dispose()

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run(tmp))


def test_accept_run_unit_queue_limit() -> None:
    """accept_run raises QueueLimitError when queue is full."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def _run(tmp_path_str: str) -> None:
        db_url = f"sqlite+aiosqlite:///{tmp_path_str}/unit_limit.db"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        user_id = uuid.uuid4()
        async with sessions() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

        from server.generate.models import GenerateParams
        # fill queue to limit (no key — each creates a distinct run)
        for i in range(QUEUE_LIMIT):
            params = GenerateParams(**{k: v for k, v in complete_math_query_params(
                **{k: v for k, v in _MATH_BASE.items() if k != "subject"}
            ).items() if k != "stream_version"})
            async with sessions() as s:
                await accept_run(params, user_id, session=s)

        # now the limit is hit; next call must raise
        params_over = GenerateParams(**{k: v for k, v in complete_math_query_params(
            **{k: v for k, v in _MATH_BASE.items() if k != "subject"}
        ).items() if k != "stream_version"})
        async with sessions() as s:
            with pytest.raises(QueueLimitError):
                await accept_run(params_over, user_id, session=s)
        await engine.dispose()

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run(tmp))


# ---------------------------------------------------------------------------
# Postgres-specific race-condition and FIFO tests
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_submission_key_unique_constraint_enforced_by_postgres(pg_engine: Any) -> None:
    """The DB-level UniqueConstraint on (user_id, submission_key) is enforced by Postgres.

    Uses the session-scoped pg_engine fixture (NullPool, each test drives its
    own asyncio.run() loop so connections are never reused across loops).
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from server.generate.models import GenerateParams

    async def _run() -> tuple[str, str]:
        async with pg_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        sf = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
        user_id = uuid.uuid4()
        async with sf() as session:
            session.add(User(id=user_id, email=f"pg_dedup_{user_id}@example.com"))
            await session.commit()

        params = GenerateParams(**{k: v for k, v in complete_math_query_params(
            **{k: v for k, v in _MATH_BASE.items() if k != "subject"}
        ).items() if k != "stream_version"}, submission_key="pg-dedup-key")

        # Sequential dedup: second accept_run with the same key must return the
        # first run (IntegrityError → rollback → look up winner path).
        async with sf() as s1:
            ar1 = await accept_run(params, user_id, session=s1)
        async with sf() as s2:
            ar2 = await accept_run(params, user_id, session=s2)
        return ar1.run_id, ar2.run_id

    run1, run2 = asyncio.run(_run())
    assert run1 == run2, f"Postgres dedup must return same run: {run1} != {run2}"


@pytest.mark.postgres
def test_concurrent_queue_limit_exactly_one_wins(pg_engine: Any) -> None:
    """Two concurrent accept_run calls at the limit boundary: exactly one queued run is created.

    With the per-teacher SELECT … FOR UPDATE serialisation lock, whichever
    transaction acquires the lock first will insert successfully; the second
    will see queued_count == QUEUE_LIMIT and raise QueueLimitError.  Without
    the lock both would read queued_count == QUEUE_LIMIT - 1 and try to insert
    concurrently — the unique-key constraint catches an identical submission_key
    but cannot prevent two different-key inserts from both slipping through.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from server.generate.models import GenerateParams

    async def _run() -> None:
        async with pg_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
        user_id = uuid.uuid4()
        async with sf() as session:
            session.add(User(id=user_id, email=f"pg_race_limit_{user_id}@example.com"))
            await session.commit()

        def _make_params(key: str) -> GenerateParams:
            return GenerateParams(**{k: v for k, v in complete_math_query_params(
                **{k: v for k, v in _MATH_BASE.items() if k != "subject"}
            ).items() if k != "stream_version"}, submission_key=key)

        # Fill queue to QUEUE_LIMIT - 1 runs.
        for i in range(QUEUE_LIMIT - 1):
            async with sf() as s:
                await accept_run(_make_params(f"pre-{i}"), user_id, session=s)

        # Two concurrent calls: one for the last slot, one that should be blocked.
        results: list[Any] = [None, None]

        async def _submit(idx: int, key: str) -> None:
            try:
                async with sf() as s:
                    results[idx] = await accept_run(_make_params(key), user_id, session=s)
            except QueueLimitError:
                results[idx] = "limit"

        await asyncio.gather(
            _submit(0, "concurrent-a"),
            _submit(1, "concurrent-b"),
        )

        successes = [r for r in results if r != "limit"]
        failures = [r for r in results if r == "limit"]
        # Exactly one should succeed and one should hit the limit.
        assert len(successes) == 1, f"Expected 1 success, got results={results}"
        assert len(failures) == 1, f"Expected 1 limit error, got results={results}"

    asyncio.run(_run())


@pytest.mark.postgres
def test_concurrent_same_key_both_get_same_run(pg_engine: Any) -> None:
    """Two concurrent accept_run calls with the same submission_key both get the same run_id."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from server.generate.models import GenerateParams

    async def _run() -> tuple[str, str]:
        async with pg_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
        user_id = uuid.uuid4()
        async with sf() as session:
            session.add(User(id=user_id, email=f"pg_same_key_{user_id}@example.com"))
            await session.commit()

        params = GenerateParams(**{k: v for k, v in complete_math_query_params(
            **{k: v for k, v in _MATH_BASE.items() if k != "subject"}
        ).items() if k != "stream_version"}, submission_key="concurrent-same-key")

        run_ids: list[str] = [None, None]  # type: ignore[list-item]

        async def _submit(idx: int) -> None:
            async with sf() as s:
                ar = await accept_run(params, user_id, session=s)
                run_ids[idx] = ar.run_id

        await asyncio.gather(_submit(0), _submit(1))
        return run_ids[0], run_ids[1]

    run1, run2 = asyncio.run(_run())
    assert run1 is not None and run2 is not None
    assert run1 == run2, (
        f"Concurrent same-key submits must return same run: {run1!r} != {run2!r}"
    )


@pytest.mark.postgres
def test_fifo_claim_order_matches_submission_order(pg_engine: Any) -> None:
    """claim_next_run returns runs in submission order (FIFO) for the same teacher.

    Verifies the ORDER BY started_at, id clause in claim_next_run works on Postgres.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from server.generate.models import GenerateParams
    from server.generate.run import claim_next_run

    async def _run() -> list[str]:
        async with pg_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Truncate tables so rows from other postgres tests do not affect
            # the claim order.  CASCADE handles FK-dependent child rows.
            from sqlalchemy import text as _text
            await conn.execute(
                _text(
                    "TRUNCATE TABLE generation_logs, users RESTART IDENTITY CASCADE"
                )
            )
        sf = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

        # Two distinct teachers so each teacher can have one run claimed at a time.
        teacher1 = uuid.uuid4()
        teacher2 = uuid.uuid4()
        teacher3 = uuid.uuid4()
        async with sf() as session:
            session.add_all([
                User(id=teacher1, email=f"t1_{teacher1}@example.com"),
                User(id=teacher2, email=f"t2_{teacher2}@example.com"),
                User(id=teacher3, email=f"t3_{teacher3}@example.com"),
            ])
            await session.commit()

        def _make_params() -> GenerateParams:
            return GenerateParams(**{k: v for k, v in complete_math_query_params(
                **{k: v for k, v in _MATH_BASE.items() if k != "subject"}
            ).items() if k != "stream_version"})

        # Submit in order: teacher1, teacher2, teacher3.
        async with sf() as s:
            ar1 = await accept_run(_make_params(), teacher1, session=s)
        async with sf() as s:
            ar2 = await accept_run(_make_params(), teacher2, session=s)
        async with sf() as s:
            ar3 = await accept_run(_make_params(), teacher3, session=s)

        # Claim all three; FIFO means teacher1's run comes first.
        claimed_order = []
        for _ in range(3):
            c = await claim_next_run(sf, host_id="fifo-host")
            if c is not None:
                claimed_order.append(str(c.run_id))
        return claimed_order, [ar1.run_id, ar2.run_id, ar3.run_id]

    claimed, expected = asyncio.run(_run())
    assert claimed == expected, (
        f"Claimed order {claimed} does not match submission order {expected}"
    )
