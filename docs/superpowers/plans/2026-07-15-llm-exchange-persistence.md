# LLM Exchange Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every LLM request/response pair emitted during a web `/api/generate` run into a new `llm_exchanges` table (FK to `generation_logs`), and expose a `GET /api/generation-logs/{id}/exchanges` route for post-hoc debugging. Adds a retention window (`LLM_EXCHANGE_RETENTION_DAYS`, default 30) so the ~93 KB curriculum prompt does not fill disks; `0` disables persistence.

**Architecture:** New SQLAlchemy model `LLMExchange` + Alembic migration. A new `ExchangeRecorder` observer (thread-safe; keyed by `event["agent"]`) buffers `llm_request` events and flushes one row when the matching `llm_response` arrives. `server/generate/service.py` composes the recorder with the existing SSE queue observer and installs the pair on each `LLMClient` (top-level and sub-clients inherit the same observer via `set_observer`). Writes go from the worker thread back to the main event loop via `asyncio.run_coroutine_threadsafe`. CLI runs in `src/` are unaffected — no recorder is attached and no DB dependency is added to `src/`.

**Tech Stack:** SQLAlchemy 2.x (`Mapped`/`mapped_column`), Alembic, FastAPI, Pydantic, pytest with in-memory SQLite (`sqlite+aiosqlite:///:memory:`), existing `LLMObserver = Callable[[dict], None]` protocol from `src/llm_client.py`.

**Spec:** `docs/superpowers/specs/2026-07-15-llm-exchange-persistence-design.md`

## Global Constraints

- Backend-only change. No `web/` edits, no UI in this issue.
- `src/` (CLI + LLM client) must not import from `server/`. Only the web worker attaches the recorder.
- Persistence failures **log a warning and never raise** — generation must succeed even if the DB is unreachable.
- When `LLM_EXCHANGE_RETENTION_DAYS=0`, the recorder is not attached; **no rows are written** and startup pruning is skipped.
- Retention pruning runs once per app startup, **after** the Alembic upgrade completes.
- Missing-side handling: if only `llm_request` is seen (worker crashed), the row is still written with `response_body=NULL`; if only `llm_response` is seen (defensive), the row is written with `request_body=NULL`.
- `agent` string is the value already on the event (`generator`, `sub_generator#3`, `verifier`, `corrector`, `image_agent`, `planner`, ...). `purpose` is the existing `purpose` string.
- Image bytes are never persisted. `request_body.messages` uses the summarized form already produced by `LLMClient._summarize_for_observer` (data URLs replaced by `{mime}; len=N`).
- `GET /api/generation-logs/{id}/exchanges` is auth-guarded (`get_current_user`), returns 404 when the log is not owned by the caller (never 403 — hides existence), and orders rows by `exchange_order ASC`.
- All tests live under `tests/server/` and run via `uv run pytest`.

---

### Task 1: `LLMExchange` ORM model + retention config

**Files:**
- Modify: `server/models.py` (add `LLMExchange` class after `GenerationLog`)
- Modify: `server/config.py` (`ServerConfig.llm_exchange_retention_days` field + env read)
- Modify: `tests/server/test_db_models.py` (extend existing assertions)

**Interfaces:**
- Consumes: `Base` (existing), `GenerationLog.id` (existing FK target), `ServerConfig` (existing).
- Produces:
  - `server.models.LLMExchange` — ORM class Task 2 references in the migration and Task 3/4/5/6 import.
  - `ServerConfig.llm_exchange_retention_days: int` — read by Task 4 (skip attach when 0) and Task 6 (pruning cutoff).

- [ ] **Step 1: Write the failing test**

Replace the body of `tests/server/test_db_models.py` with:

```python
from __future__ import annotations

from server.config import ServerConfig
from server.models import (
    Base,
    GenerationLog,
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
        "llm_exchanges",
    }
    assert list(GenerationStatus.enums) == ["started", "completed", "failed"]


def test_model_key_columns() -> None:
    assert User.__table__.c.email.unique is True
    assert User.__table__.c.email.nullable is False
    assert MagicLinkToken.__table__.c.token_hash.nullable is False
    assert GenerationLog.__table__.c.user_id.nullable is False


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_db_models.py -x`
Expected: FAIL with `ImportError: cannot import name 'LLMExchange' from 'server.models'`.

- [ ] **Step 3: Add the ORM class**

In `server/models.py`, extend the imports on line 8 and append the class after `GenerationLog`:

```python
from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
```

Then append at the end of the file (after `GenerationLog`):

```python
class LLMExchange(Base):
    __tablename__ = "llm_exchanges"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    generation_log_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("generation_logs.id"),
        nullable=False,
        index=True,
    )
    exchange_order: Mapped[int] = mapped_column(Integer, nullable=False)
    agent: Mapped[str] = mapped_column(String(50), nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    request_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: Add the retention config field**

In `server/config.py`:

1. Add the dataclass field after `email_whitelist` (line 35):

```python
    llm_exchange_retention_days: int = 30
```

2. Add the env read to `from_env` — inside the `return cls(...)` block, before the closing paren (after `math_curriculum_dir=...` around line 97):

```python
            llm_exchange_retention_days=int(
                os.environ.get("LLM_EXCHANGE_RETENTION_DAYS", "30")
            ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/server/test_db_models.py -x`
Expected: PASS — 6 tests green.

- [ ] **Step 6: Commit**

```bash
git add server/models.py server/config.py tests/server/test_db_models.py
git commit -m "feat(server): add LLMExchange model + LLM_EXCHANGE_RETENTION_DAYS config (#113)"
```

---

### Task 2: Alembic migration for `llm_exchanges`

**Files:**
- Create: `alembic/versions/<hash>_add_llm_exchanges.py`

**Interfaces:**
- Consumes: existing revision `3670c7404c79` (initial).
- Produces: schema table `llm_exchanges` with FK to `generation_logs.id` + index on `generation_log_id`.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_llm_exchanges_migration.py`:

```python
from __future__ import annotations

import asyncio
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_llm_exchanges_migration.py -x`
Expected: FAIL — `llm_exchanges` table not created.

- [ ] **Step 3: Generate a stub migration and edit it**

```bash
DATABASE_URL="sqlite+aiosqlite:///./dev.db" uv run alembic revision -m "add_llm_exchanges"
```

Alembic writes `alembic/versions/<HASH>_add_llm_exchanges.py`. Overwrite its body with:

```python
"""add_llm_exchanges

Revises: 3670c7404c79
Create Date: 2026-07-15 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "<KEEP_THE_HASH_ALEMBIC_GAVE_YOU>"
down_revision: Union[str, Sequence[str], None] = "3670c7404c79"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_exchanges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_log_id", sa.Uuid(), nullable=False),
        sa.Column("exchange_order", sa.Integer(), nullable=False),
        sa.Column("agent", sa.String(length=50), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("request_body", sa.JSON(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["generation_log_id"], ["generation_logs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_exchanges_generation_log_id"),
        "llm_exchanges",
        ["generation_log_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_exchanges_generation_log_id"), table_name="llm_exchanges")
    op.drop_table("llm_exchanges")
```

Replace `<KEEP_THE_HASH_ALEMBIC_GAVE_YOU>` with the hash Alembic printed on stdout (also the filename prefix).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_llm_exchanges_migration.py -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/*_add_llm_exchanges.py tests/server/test_llm_exchanges_migration.py
git commit -m "feat(server): alembic migration for llm_exchanges table (#113)"
```

---

### Task 3: `ExchangeRecorder` observer module

**Files:**
- Create: `server/generate/exchange_recorder.py`
- Create: `tests/server/test_exchange_recorder.py`

**Interfaces:**
- Consumes:
  - `event: dict` shaped like `LLMClient` observer events — `{"type": "llm_request"|"llm_response", "agent": str, "purpose": str, "model": str, "messages"?, "params"?, "content"?, "reasoning"?, "usage"?}`.
  - A `write_row: Callable[[dict], None]` — Task 4 binds this to a DB insert; the unit test binds it to a list `.append`.
- Produces:
  - `ExchangeRecorder(generation_log_id: uuid.UUID, write_row: Callable[[dict], None])` — its `__call__(event)` satisfies `LLMObserver = Callable[[dict], None]` (from `src/llm_client.py`).

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_exchange_recorder.py`:

```python
from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest

from server.generate.exchange_recorder import ExchangeRecorder


@pytest.fixture
def sink() -> tuple[list[dict[str, Any]], Any]:
    rows: list[dict[str, Any]] = []

    def write(row: dict[str, Any]) -> None:
        rows.append(row)

    return rows, write


def _req(agent: str, purpose: str = "generate") -> dict:
    return {
        "type": "llm_request",
        "agent": agent,
        "purpose": purpose,
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ],
        "params": {"max_tokens": 8192, "temperature": 0.7},
    }


def _resp(agent: str, purpose: str = "generate") -> dict:
    return {
        "type": "llm_response",
        "agent": agent,
        "purpose": purpose,
        "model": "claude-sonnet-4-6",
        "content": "ok",
        "reasoning": None,
        "usage": {"input": 12, "output": 3, "cache_read": 0, "cache_creation": 0},
    }


def test_request_response_pair_produces_one_row(sink):
    rows, write = sink
    log_id = uuid.uuid4()
    rec = ExchangeRecorder(log_id, write)

    rec(_req("generator"))
    assert rows == []  # no row until response arrives
    rec(_resp("generator"))

    assert len(rows) == 1
    row = rows[0]
    assert row["generation_log_id"] == log_id
    assert row["exchange_order"] == 1
    assert row["agent"] == "generator"
    assert row["purpose"] == "generate"
    assert row["model_used"] == "claude-sonnet-4-6"
    assert row["prompt_tokens"] == 12
    assert row["completion_tokens"] == 3
    assert row["request_body"]["messages"][1]["content"] == "hello"
    assert row["response_body"]["content"] == "ok"


def test_order_counter_increments_and_is_stable(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)

    rec(_req("generator"))
    rec(_resp("generator"))
    rec(_req("verifier", purpose="verify"))
    rec(_resp("verifier", purpose="verify"))

    assert [r["exchange_order"] for r in rows] == [1, 2]
    assert [r["agent"] for r in rows] == ["generator", "verifier"]


def test_parallel_agents_are_matched_by_agent_id(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)

    # Interleaved events from three parallel sub-generators.
    rec(_req("sub_generator#1"))
    rec(_req("sub_generator#2"))
    rec(_req("sub_generator#3"))
    rec(_resp("sub_generator#2"))
    rec(_resp("sub_generator#1"))
    rec(_resp("sub_generator#3"))

    agents = {r["agent"] for r in rows}
    assert agents == {"sub_generator#1", "sub_generator#2", "sub_generator#3"}
    assert len(rows) == 3
    orders = sorted(r["exchange_order"] for r in rows)
    assert orders == [1, 2, 3]


def test_response_without_request_writes_null_request(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)

    rec(_resp("verifier", purpose="verify"))

    assert len(rows) == 1
    assert rows[0]["request_body"] is None
    assert rows[0]["response_body"]["content"] == "ok"
    assert rows[0]["agent"] == "verifier"
    assert rows[0]["purpose"] == "verify"


def test_write_failures_are_swallowed_and_logged(sink, caplog):
    def boom(_row):
        raise RuntimeError("db down")

    rec = ExchangeRecorder(uuid.uuid4(), boom)
    with caplog.at_level("WARNING"):
        rec(_req("generator"))
        rec(_resp("generator"))
    assert any("ExchangeRecorder" in r.getMessage() for r in caplog.records)


def test_thread_safety_under_concurrent_events(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)

    def hammer(agent: str) -> None:
        for _ in range(50):
            rec(_req(agent))
            rec(_resp(agent))

    threads = [
        threading.Thread(target=hammer, args=(f"sub_generator#{i}",))
        for i in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(rows) == 4 * 50
    orders = sorted(r["exchange_order"] for r in rows)
    assert orders == list(range(1, 4 * 50 + 1))


def test_non_llm_events_are_ignored(sink):
    rows, write = sink
    rec = ExchangeRecorder(uuid.uuid4(), write)
    rec({"type": "stage", "agent": "generator", "stage": "llm_generate", "status": "start"})
    rec({"type": "llm_content_delta", "agent": "generator", "text": "hi"})
    assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_exchange_recorder.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.generate.exchange_recorder'`.

- [ ] **Step 3: Write the implementation**

Create `server/generate/exchange_recorder.py`:

```python
"""Persistence observer that pairs llm_request/llm_response events into DB rows."""

from __future__ import annotations

import itertools
import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

WriteRow = Callable[[dict[str, Any]], None]


class ExchangeRecorder:
    """Buffer llm_request events per-agent, write one row on llm_response.

    Thread-safe: parallel sub-generators emit interleaved events through
    the same observer. Write failures are logged as warnings and never
    raised — generation must continue even when the DB is unreachable.

    A row with `request_body=NULL` is written if a response arrives with
    no matching request (defensive). If a request never gets a response
    (worker crashed), that row is intentionally not written — the
    generation_log row's `status='failed'` already signals the crash.
    """

    def __init__(self, generation_log_id: uuid.UUID, write_row: WriteRow) -> None:
        self._log_id = generation_log_id
        self._write_row = write_row
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    def __call__(self, event: dict[str, Any]) -> None:
        try:
            event_type = event.get("type")
            if event_type == "llm_request":
                agent = str(event.get("agent", ""))
                with self._lock:
                    self._pending[agent] = event
                return
            if event_type == "llm_response":
                agent = str(event.get("agent", ""))
                with self._lock:
                    req = self._pending.pop(agent, None)
                self._flush(agent, req, event)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("ExchangeRecorder failed to handle event: %s", exc)

    def _flush(
        self,
        agent: str,
        req: dict[str, Any] | None,
        resp: dict[str, Any] | None,
    ) -> None:
        source = req or resp or {}
        usage = (resp or {}).get("usage") if resp else None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        if isinstance(usage, dict):
            prompt_tokens = usage.get("input")
            completion_tokens = usage.get("output")

        with self._lock:
            order = next(self._counter)

        row: dict[str, Any] = {
            "generation_log_id": self._log_id,
            "exchange_order": order,
            "agent": agent,
            "purpose": str(source.get("purpose", "")),
            "request_body": (
                {
                    "messages": req.get("messages"),
                    "params": req.get("params"),
                    "model": req.get("model"),
                }
                if req is not None
                else None
            ),
            "response_body": (
                {
                    "content": resp.get("content"),
                    "reasoning": resp.get("reasoning"),
                    "usage": resp.get("usage"),
                }
                if resp is not None
                else None
            ),
            "model_used": str(source.get("model", "")),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
        try:
            self._write_row(row)
        except Exception as exc:
            logger.warning(
                "ExchangeRecorder write failed (agent=%s, order=%d): %s",
                agent,
                order,
                exc,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_exchange_recorder.py -x`
Expected: PASS — 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add server/generate/exchange_recorder.py tests/server/test_exchange_recorder.py
git commit -m "feat(server): add ExchangeRecorder observer for llm request/response pairing (#113)"
```

---

### Task 4: Wire recorder into `generate_question_stream`

**Files:**
- Modify: `server/generate/service.py` (extend signature, compose observer, write via `run_coroutine_threadsafe`)
- Modify: `server/generate/routes.py` (pass `log.id` into the stream)
- Modify: `tests/server/test_generate_routes.py` (extend existing fake-stream fixtures to assert DB rows written)

**Interfaces:**
- Consumes:
  - `ExchangeRecorder` from Task 3.
  - `LLMExchange` from Task 1.
  - `ServerConfig.llm_exchange_retention_days` from Task 1.
- Produces: rows in `llm_exchanges` per generation call. Task 5's route reads these.

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_generate_routes.py`:

```python
def test_generate_stream_writes_llm_exchange_rows(tmp_path) -> None:
    from types import SimpleNamespace

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from server.generate import service
    from server.generate.models import GenerateParams
    from server.models import Base, LLMExchange
    from src.social_studies.schemas import ExamQuestion

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Patch service.AsyncSessionLocal so the recorder's write path uses our engine.
    original_sessionmaker = service.AsyncSessionLocal
    service.AsyncSessionLocal = SessionLocal  # type: ignore[assignment]

    log_id = uuid.uuid4()
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_exchange_retention_days=30,
    )
    params = GenerateParams(subject="social_studies", count=1, skip_verify=True)

    def fake_generate_with_corrections(**kwargs):
        question_id = kwargs["question_id"]
        sampled = kwargs["params"]
        obs = kwargs["client"].get_observer()
        # Simulate two LLM calls (generator + verifier) coming through the observer.
        obs({
            "type": "llm_request", "agent": "generator", "purpose": "generate",
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hi"}],
            "params": {"max_tokens": 8192, "temperature": 0.7},
        })
        obs({
            "type": "llm_response", "agent": "generator", "purpose": "generate",
            "model": "claude-sonnet-4-6", "content": "ok", "reasoning": None,
            "usage": {"input": 10, "output": 5, "cache_read": 0, "cache_creation": 0},
        })
        obs({
            "type": "llm_request", "agent": "verifier", "purpose": "verify",
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "verify"}],
            "params": {"max_tokens": 8192, "temperature": 0.7},
        })
        obs({
            "type": "llm_response", "agent": "verifier", "purpose": "verify",
            "model": "claude-sonnet-4-6", "content": "{\"passed\": true}",
            "reasoning": None,
            "usage": {"input": 7, "output": 2, "cache_read": 0, "cache_creation": 0},
        })
        return ExamQuestion(
            id=question_id,
            核心問題="c",
            文本="p",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            閱讀歷程=[p.value for p in sampled.閱讀歷程],
            文本形式=sampled.文本形式.value,
            題目=["q"],
            正確解題分析=["a"],
        )

    original = service.ss_generate_with_corrections
    service.ss_generate_with_corrections = fake_generate_with_corrections  # type: ignore[assignment]

    async def _drive() -> None:
        async for _ in service.generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            generation_log_id=log_id,
        ):
            pass

    try:
        asyncio.run(_drive())
    finally:
        service.ss_generate_with_corrections = original  # type: ignore[assignment]
        service.AsyncSessionLocal = original_sessionmaker  # type: ignore[assignment]

    async def _read() -> list[LLMExchange]:
        async with SessionLocal() as s:
            result = await s.execute(
                select(LLMExchange)
                .where(LLMExchange.generation_log_id == log_id)
                .order_by(LLMExchange.exchange_order)
            )
            return list(result.scalars().all())

    rows = asyncio.run(_read())
    asyncio.run(engine.dispose())

    assert [r.agent for r in rows] == ["generator", "verifier"]
    assert [r.exchange_order for r in rows] == [1, 2]
    assert rows[0].purpose == "generate"
    assert rows[0].prompt_tokens == 10
    assert rows[0].completion_tokens == 5
    assert rows[1].purpose == "verify"
    assert rows[1].model_used == "claude-sonnet-4-6"


def test_generate_stream_skips_recording_when_retention_zero(tmp_path) -> None:
    from types import SimpleNamespace

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from server.generate import service
    from server.generate.models import GenerateParams
    from server.models import Base, LLMExchange
    from src.social_studies.schemas import ExamQuestion

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    original_sessionmaker = service.AsyncSessionLocal
    service.AsyncSessionLocal = SessionLocal  # type: ignore[assignment]

    log_id = uuid.uuid4()
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_exchange_retention_days=0,
    )
    params = GenerateParams(subject="social_studies", count=1, skip_verify=True)

    def fake_generate_with_corrections(**kwargs):
        obs = kwargs["client"].get_observer()
        # Recorder must not be attached; if it were, this would insert.
        if obs is not None:
            obs({
                "type": "llm_request", "agent": "generator", "purpose": "generate",
                "model": "m", "messages": [], "params": {},
            })
            obs({
                "type": "llm_response", "agent": "generator", "purpose": "generate",
                "model": "m", "content": "x", "reasoning": None, "usage": {},
            })
        sampled = kwargs["params"]
        return ExamQuestion(
            id=kwargs["question_id"],
            核心問題="c", 文本="p", subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            閱讀歷程=[p.value for p in sampled.閱讀歷程],
            文本形式=sampled.文本形式.value,
            題目=["q"], 正確解題分析=["a"],
        )

    original = service.ss_generate_with_corrections
    service.ss_generate_with_corrections = fake_generate_with_corrections  # type: ignore[assignment]

    async def _drive() -> None:
        async for _ in service.generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            generation_log_id=log_id,
        ):
            pass

    try:
        asyncio.run(_drive())
    finally:
        service.ss_generate_with_corrections = original  # type: ignore[assignment]
        service.AsyncSessionLocal = original_sessionmaker  # type: ignore[assignment]

    async def _read_count() -> int:
        async with SessionLocal() as s:
            result = await s.execute(select(LLMExchange))
            return len(list(result.scalars().all()))

    count = asyncio.run(_read_count())
    asyncio.run(engine.dispose())
    assert count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_generate_routes.py::test_generate_stream_writes_llm_exchange_rows -x`
Expected: FAIL — `TypeError: generate_question_stream() got an unexpected keyword argument 'generation_log_id'`.

- [ ] **Step 3: Extend `service.py` — add generation_log_id, compose recorder**

At the top of `server/generate/service.py`, extend the imports (after `from server.generate.models import GenerateParams` on line 19):

```python
import uuid

from server.db import AsyncSessionLocal
from server.generate.exchange_recorder import ExchangeRecorder
from server.models import LLMExchange
```

Change the signature of `generate_question_stream` (line 124) to:

```python
async def generate_question_stream(
    params: GenerateParams,
    config: ServerConfig,
    app_state: Any,
    generation_log_id: uuid.UUID | None = None,
) -> AsyncIterator[dict[str, Any]]:
```

Inside `generate_question_stream`, immediately after the existing `_make_queue_observer` definition (currently ends around line 221), add a recorder factory + composite-observer helper:

```python
    def _make_recorder() -> ExchangeRecorder | None:
        if generation_log_id is None or config.llm_exchange_retention_days <= 0:
            return None

        async def _insert(row: dict[str, Any]) -> None:
            async with AsyncSessionLocal() as sess:
                sess.add(LLMExchange(**row))
                await sess.commit()

        def _write_row(row: dict[str, Any]) -> None:
            future = asyncio.run_coroutine_threadsafe(_insert(row), loop)
            try:
                future.result(timeout=10)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("llm_exchanges insert failed: %s", exc)

        return ExchangeRecorder(generation_log_id, _write_row)

    def _make_observer(
        queue_obs: LLMObserver,
        recorder: ExchangeRecorder | None,
    ) -> LLMObserver:
        def observer(event: dict) -> None:
            try:
                queue_obs(event)
            except Exception:
                pass
            if recorder is not None:
                try:
                    recorder(event)
                except Exception:
                    pass
        return observer
```

Replace the current line in `worker_one` that reads:

```python
        question_client.set_observer(_make_queue_observer(loop, queue))
```

with:

```python
        question_client.set_observer(
            _make_observer(_make_queue_observer(loop, queue), _make_recorder())
        )
```

- [ ] **Step 4: Extend `routes.py` — pass `log.id` to the stream**

In `server/generate/routes.py`, change the single call to `generate_question_stream` inside `event_generator` (currently `async for event in generate_question_stream(params, config, app_state):` at line 129) to:

```python
            async for event in generate_question_stream(
                params, config, app_state, generation_log_id=log_id,
            ):
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/server/test_generate_routes.py -x`
Expected: PASS — including the two new tests plus the existing 3 tests in that file.

- [ ] **Step 6: Commit**

```bash
git add server/generate/service.py server/generate/routes.py tests/server/test_generate_routes.py
git commit -m "feat(server): persist LLM exchanges via recorder observer wired into worker (#113)"
```

---

### Task 5: `GET /api/generation-logs/{id}/exchanges` route

**Files:**
- Modify: `server/generate/routes.py` (add endpoint at the bottom of the file)
- Create: `tests/server/test_exchange_routes.py`

**Interfaces:**
- Consumes: `get_current_user`, `get_async_session`, `LLMExchange`, `GenerationLog` (existing).
- Produces: JSON list `[{id, exchange_order, agent, purpose, request_body, response_body, model_used, prompt_tokens, completion_tokens, created_at}, ...]` ordered by `exchange_order ASC`. 404 when the log does not exist or is owned by another user.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_exchange_routes.py`:

```python
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationLog, LLMExchange, User
from server.rate_limit import limiter


@pytest.fixture
def app_ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret")

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    yield app, SessionLocal, config

    limiter.reset()
    asyncio.run(engine.dispose())


def _seed(SessionLocal, user_id: uuid.UUID, log_id: uuid.UUID, *, exchanges: int) -> None:
    async def _add() -> None:
        async with SessionLocal() as s:
            s.add(User(id=user_id, email=f"{user_id}@example.com"))
            s.add(
                GenerationLog(
                    id=log_id,
                    user_id=user_id,
                    params_json={"subject": "math"},
                    status="completed",
                )
            )
            for i in range(exchanges):
                s.add(
                    LLMExchange(
                        generation_log_id=log_id,
                        exchange_order=exchanges - i,  # inserted out of order on purpose
                        agent=f"generator" if i == 0 else f"sub_generator#{i}",
                        purpose="generate",
                        request_body={"messages": [{"role": "user", "content": f"q{i}"}]},
                        response_body={"content": f"a{i}"},
                        model_used="claude-sonnet-4-6",
                        prompt_tokens=10 + i,
                        completion_tokens=1 + i,
                    )
                )
            await s.commit()

    asyncio.run(_add())


def test_owner_lists_exchanges_sorted_by_order(app_ctx):
    app, SessionLocal, config = app_ctx
    user_id = uuid.uuid4()
    log_id = uuid.uuid4()
    _seed(SessionLocal, user_id, log_id, exchanges=3)

    token = create_jwt(user_id, "u@example.com", config=config)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/generation-logs/{log_id}/exchanges",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert [row["exchange_order"] for row in data] == [1, 2, 3]
    assert data[0]["model_used"] == "claude-sonnet-4-6"
    assert data[0]["request_body"]["messages"][0]["content"] in {"q0", "q1", "q2"}


def test_other_user_gets_404(app_ctx):
    app, SessionLocal, config = app_ctx
    owner_id = uuid.uuid4()
    log_id = uuid.uuid4()
    _seed(SessionLocal, owner_id, log_id, exchanges=1)

    other_id = uuid.uuid4()

    async def add_other() -> None:
        async with SessionLocal() as s:
            s.add(User(id=other_id, email="other@example.com"))
            await s.commit()

    asyncio.run(add_other())

    token = create_jwt(other_id, "other@example.com", config=config)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/generation-logs/{log_id}/exchanges",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 404


def test_unknown_log_id_returns_404(app_ctx):
    app, SessionLocal, config = app_ctx
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as s:
            s.add(User(id=user_id, email="u@example.com"))
            await s.commit()

    asyncio.run(add_user())

    token = create_jwt(user_id, "u@example.com", config=config)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/generation-logs/{uuid.uuid4()}/exchanges",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 404


def test_unauthenticated_returns_401(app_ctx):
    app, _SessionLocal, _config = app_ctx
    with TestClient(app) as client:
        resp = client.get(f"/api/generation-logs/{uuid.uuid4()}/exchanges")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_exchange_routes.py -x`
Expected: FAIL — 404 on the owner-happy-path test (route does not exist yet → FastAPI returns 404 with no matching path).

- [ ] **Step 3: Add the endpoint**

Append to `server/generate/routes.py` (after the closing of `plan_core_questions_endpoint`):

```python
@router.get("/generation-logs/{log_id}/exchanges")
async def list_generation_log_exchanges(
    log_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[dict[str, Any]]:
    """Return LLM exchanges for a generation the caller owns, ordered by exchange_order.

    404 on missing/other-user logs (existence-hiding — never 403).
    """
    from sqlalchemy import select

    from server.models import GenerationLog as _GL
    from server.models import LLMExchange

    log_row = (
        await session.execute(
            select(_GL).where(_GL.id == log_id, _GL.user_id == user.id)
        )
    ).scalar_one_or_none()
    if log_row is None:
        raise HTTPException(status_code=404, detail="generation log not found")

    rows = (
        await session.execute(
            select(LLMExchange)
            .where(LLMExchange.generation_log_id == log_id)
            .order_by(LLMExchange.exchange_order.asc())
        )
    ).scalars().all()

    return [
        {
            "id": str(row.id),
            "exchange_order": row.exchange_order,
            "agent": row.agent,
            "purpose": row.purpose,
            "request_body": row.request_body,
            "response_body": row.response_body,
            "model_used": row.model_used,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
```

Add the `uuid` import at the top of the file if not already present (`import uuid`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_exchange_routes.py -x`
Expected: PASS — 4 tests green.

- [ ] **Step 5: Commit**

```bash
git add server/generate/routes.py tests/server/test_exchange_routes.py
git commit -m "feat(server): GET /api/generation-logs/{id}/exchanges for debugging (#113)"
```

---

### Task 6: Startup retention pruning

**Files:**
- Modify: `server/app.py` (extend `lifespan` after the Alembic upgrade)
- Create: `tests/server/test_exchange_retention.py`

**Interfaces:**
- Consumes: `ServerConfig.llm_exchange_retention_days`, `LLMExchange`, `AsyncSessionLocal`.
- Produces: at startup, deletes `LLMExchange` rows with `created_at < now() - retention_days` when retention > 0. Skipped entirely when retention == 0.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_exchange_retention.py`:

```python
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import prune_expired_llm_exchanges
from server.config import ServerConfig
from server.models import Base, GenerationLog, LLMExchange, User


def _make_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    return engine


def _seed(SessionLocal, log_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async def _add() -> None:
        async with SessionLocal() as s:
            s.add(User(id=user_id, email="u@example.com"))
            s.add(
                GenerationLog(
                    id=log_id,
                    user_id=user_id,
                    params_json={},
                    status="completed",
                )
            )
            old = datetime.now(timezone.utc) - timedelta(days=45)
            fresh = datetime.now(timezone.utc) - timedelta(days=1)
            s.add(
                LLMExchange(
                    generation_log_id=log_id,
                    exchange_order=1,
                    agent="generator",
                    purpose="generate",
                    request_body=None,
                    response_body=None,
                    model_used="m",
                    created_at=old,
                )
            )
            s.add(
                LLMExchange(
                    generation_log_id=log_id,
                    exchange_order=2,
                    agent="verifier",
                    purpose="verify",
                    request_body=None,
                    response_body=None,
                    model_used="m",
                    created_at=fresh,
                )
            )
            await s.commit()

    asyncio.run(_add())


def test_prune_removes_rows_older_than_window():
    engine = _make_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    _seed(SessionLocal, uuid.uuid4(), uuid.uuid4())
    config = ServerConfig(api_key="x", jwt_secret="s", llm_exchange_retention_days=30)

    asyncio.run(prune_expired_llm_exchanges(config, session_maker=SessionLocal))

    async def _read():
        async with SessionLocal() as s:
            result = await s.execute(select(LLMExchange).order_by(LLMExchange.exchange_order))
            return list(result.scalars().all())

    rows = asyncio.run(_read())
    asyncio.run(engine.dispose())
    assert [r.exchange_order for r in rows] == [2]
    assert rows[0].agent == "verifier"


def test_prune_is_noop_when_retention_zero():
    engine = _make_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    _seed(SessionLocal, uuid.uuid4(), uuid.uuid4())
    config = ServerConfig(api_key="x", jwt_secret="s", llm_exchange_retention_days=0)

    asyncio.run(prune_expired_llm_exchanges(config, session_maker=SessionLocal))

    async def _read():
        async with SessionLocal() as s:
            result = await s.execute(select(LLMExchange))
            return list(result.scalars().all())

    rows = asyncio.run(_read())
    asyncio.run(engine.dispose())
    # 0 means "disable persistence entirely" — pruning must not delete existing rows.
    assert len(rows) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_exchange_retention.py -x`
Expected: FAIL — `ImportError: cannot import name 'prune_expired_llm_exchanges' from 'server.app'`.

- [ ] **Step 3: Add the pruning helper and wire it into lifespan**

In `server/app.py`, extend the imports (top of file):

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from server.db import AsyncSessionLocal
from server.models import LLMExchange
```

Add the helper function above `create_app()`:

```python
async def prune_expired_llm_exchanges(
    config: ServerConfig,
    *,
    session_maker=None,
) -> int:
    """Delete llm_exchanges rows older than `LLM_EXCHANGE_RETENTION_DAYS`.

    Returns the number of rows deleted. When retention == 0, persistence is
    disabled entirely — do not delete existing rows either (they remain
    inspectable via the read endpoint until the operator raises retention
    back above zero and old rows exit the window).
    """
    retention = config.llm_exchange_retention_days
    if retention <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
    sm = session_maker or AsyncSessionLocal
    async with sm() as sess:
        result = await sess.execute(
            delete(LLMExchange).where(LLMExchange.created_at < cutoff)
        )
        await sess.commit()
        return result.rowcount or 0
```

Extend `lifespan` — after the `await asyncio.to_thread(_run_alembic)` block (currently around line 50), add:

```python
    try:
        deleted = await prune_expired_llm_exchanges(config)
        if deleted:
            print(f"Pruned {deleted} expired llm_exchanges rows")
    except Exception as exc:  # pragma: no cover - best effort
        print(f"Warning: llm_exchanges pruning failed: {exc}", file=sys.stderr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_exchange_retention.py -x`
Expected: PASS — 2 tests green.

- [ ] **Step 5: Run the full server test suite as a smoke check**

Run: `uv run pytest tests/server/ -x`
Expected: PASS — all server tests green (existing + Tasks 1–6).

- [ ] **Step 6: Commit**

```bash
git add server/app.py tests/server/test_exchange_retention.py
git commit -m "feat(server): prune expired llm_exchanges rows at startup (#113)"
```

---

### Task 7: Document the feature in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (extend the "Key Files" table and env-var section)

**Interfaces:** none — documentation only.

- [ ] **Step 1: Extend the Key Files table**

In `CLAUDE.md`, in the file table, add rows for the four new/changed files. Insert after the `server/generate/routes.py` row:

```markdown
| `server/generate/exchange_recorder.py` | `ExchangeRecorder` observer — buffers `llm_request` events per-agent and writes one `LLMExchange` row on the matching `llm_response`. Thread-safe (parallel `sub_generator#i` workers share one recorder). Persistence failures log a warning and never raise. |
| `server/models.py` `LLMExchange` | New table `llm_exchanges` (FK → `generation_logs.id`, indexed). Columns: `id`, `generation_log_id`, `exchange_order`, `agent`, `purpose`, `request_body`, `response_body`, `model_used`, `prompt_tokens`, `completion_tokens`, `created_at`. |
| `server/generate/routes.py` `/api/generation-logs/{id}/exchanges` | Auth-guarded GET; returns the LLM exchanges owned by the caller, ordered by `exchange_order`. Returns 404 for other users' logs (existence-hiding). |
| `server/app.py` `prune_expired_llm_exchanges` | Startup helper that deletes `llm_exchanges` rows older than `LLM_EXCHANGE_RETENTION_DAYS` (default 30). `0` disables persistence entirely — the recorder is not attached at request time and pruning is skipped. |
```

- [ ] **Step 2: Document the env var**

Under the "Common Commands" section (or wherever env vars are enumerated near `SUBGEN_MAX_CONCURRENCY`), add one line:

```markdown
- `LLM_EXCHANGE_RETENTION_DAYS` (default `30`) — window in days for retaining `llm_exchanges` rows. Set to `0` to disable persistence entirely (no rows written, no pruning).
```

- [ ] **Step 3: Verify the documentation renders**

Run: `git diff CLAUDE.md`
Expected: only additive changes; no accidental deletions of existing rows.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document llm_exchanges table and LLM_EXCHANGE_RETENTION_DAYS (#113)"
```
