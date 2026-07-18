# Generation History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every successful generation per user, browse them at `/history`, view the full question + download the JSON, and re-run with the same params pre-filled into the Generate form (GitHub issue #30).

**Architecture:** New `generation_records` SQLAlchemy model + Alembic migration alongside the existing `generation_logs` table in `server/models.py`. The stream worker in `server/generate/service.py` inserts one row per successful `result` event via a fresh `AsyncSessionLocal` (best-effort, warns-not-fails). A new `server/history/routes.py` exposes list / detail / download endpoints, guarded by `get_current_user` and with ownership enforced by `user_id`. Frontend adds `web/src/pages/HistoryPage.tsx` (list + detail modes on two routes), a nav link on `GeneratePage` header, and a router-state-based prefill flow for `ParamForm`.

**Tech Stack:** SQLAlchemy 2 async + Alembic, FastAPI, Pydantic, pytest (`uv run pytest`), React 19 + react-router-dom v7, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-07-15-generation-history-design.md`

## Global Constraints

- New table name is exactly `generation_records`; columns and types are `id UUID PK`, `user_id UUID FK→users indexed`, `generation_log_id UUID FK→generation_logs nullable`, `subject str(30)`, `question_id str(100)`, `params_json JSON`, `question_json JSON`, `image_files JSON`, `created_at DateTime(timezone=True)`.
- `subject` values are one of `math` / `social_studies` / `natural_sciences`.
- Images stay on disk under `OUTPUT_DIR`; `image_files` stores filenames only; no base64 is written to the DB.
- Recording failures **log a warning and never fail generation** — a generation that succeeds but whose history row fails to persist still returns a `result` event to the client.
- History endpoints require auth; a record owned by another user returns **HTTP 404** (not 403) to avoid leaking existence.
- Retention env var is `GENERATION_HISTORY_RETENTION_DAYS`, default **0 = keep forever**; any positive integer prunes rows older than that many days at server startup (after Alembic upgrade), mirroring the `LLM_EXCHANGE_RETENTION_DAYS` pruning called for by issue #113 (spec `docs/superpowers/specs/2026-07-15-llm-exchange-persistence-design.md`).
- Pruning deletes DB rows only; PNG cleanup in `OUTPUT_DIR` is out of scope (files may be shared with batch outputs).
- Missing PNG files at detail time render the record **without** those images (no HTTP 500).
- Regenerate is **not** a silent re-submit: the button navigates to `/generate/<subject>` with the stored params injected into form state; the user reviews and clicks Generate themselves.
- Stored params referencing values no longer present in the current schema CSVs (e.g. a removed 情境 value) prefill what they can and leave the rest at defaults, with a visible in-form notice.
- All frontend commands run from `/workspace/exam-generation/web/`; all backend commands run from `/workspace/exam-generation/`.

## Pre-existing defect this plan fixes first

`web/package.json` currently ships **no** vitest / testing-library devDependencies and no `test` / `test:watch` scripts, even though `web/vitest.config.ts`, `web/src/test/setup.ts`, and two `*.test.tsx` files remain in the tree (same defect the error-report-button plan documents at commit `d534147`). Task 1 restores that tooling so the TDD cycle in this plan can run. Test files are already excluded from `tsc -b` via `tsconfig.app.json`, so restoring them does not affect the production build. If a sibling plan (e.g. `2026-07-15-error-report-button.md`) has already been merged and vitest is present, Task 1 is a no-op — `npm test` in Step 3 already passes; commit only the necessary edits.

---

### Task 1: Restore web test tooling

**Files:**
- Modify: `web/package.json` (scripts + devDependencies)
- Modify: `web/package-lock.json` (via npm)

**Interfaces:**
- Consumes: nothing.
- Produces: working `npm test` (vitest run) command used by every later frontend task.

- [ ] **Step 1: Reinstall the test devDependencies**

```bash
cd /workspace/exam-generation/web
npm install -D vitest @vitest/ui jsdom @testing-library/jest-dom @testing-library/react @testing-library/user-event
```

- [ ] **Step 2: Restore the test scripts in `web/package.json`**

In the `"scripts"` block, after `"preview": "vite preview"`, add:

```json
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
```

- [ ] **Step 3: Run the existing test suite to verify it passes**

```bash
cd /workspace/exam-generation/web
npm test
```

Expected: PASS — the existing `src/components/QuestionCard.test.tsx` and `src/components/CoreQuestionPicker.test.tsx` files run green.

- [ ] **Step 4: Verify the production build still works**

```bash
cd /workspace/exam-generation/web
npm run build
```

Expected: `tsc -b && vite build` succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add web/package.json web/package-lock.json
git commit -m "fix(web): restore vitest + testing-library tooling for history plan"
```

---

### Task 2: `GenerationRecord` ORM model + Alembic migration

**Files:**
- Modify: `server/models.py` (append `GenerationRecord` class after `GenerationLog`)
- Create: `alembic/versions/<autogen>_add_generation_records.py`
- Modify: `tests/server/test_db_models.py` (extend metadata assertion)

**Interfaces:**
- Consumes: existing `Base`, `User`, `GenerationLog` in `server/models.py`.
- Produces: `GenerationRecord` (imported by Task 3, Task 4, Task 5) with fields `id`, `user_id`, `generation_log_id`, `subject`, `question_id`, `params_json`, `question_json`, `image_files`, `created_at`.

- [ ] **Step 1: Write the failing test**

Edit `tests/server/test_db_models.py` — replace the existing `test_model_table_names_and_status_values` and append two new assertions:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_db_models.py -q
```

Expected: FAIL with `ImportError: cannot import name 'GenerationRecord' from 'server.models'`.

- [ ] **Step 3: Add the `GenerationRecord` model**

Append to `server/models.py` (after the `GenerationLog` class, keep the existing imports untouched):

```python
class GenerationRecord(Base):
    __tablename__ = "generation_records"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    generation_log_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("generation_logs.id"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(30), nullable=False)
    question_id: Mapped[str] = mapped_column(String(100), nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    question_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    image_files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: Generate the Alembic migration**

```bash
cd /workspace/exam-generation
uv run alembic revision --autogenerate -m "add generation_records"
```

Open the newly created `alembic/versions/<hash>_add_generation_records.py` and confirm the `upgrade()` body creates the `generation_records` table plus the `ix_generation_records_user_id` index, and `downgrade()` drops them. If autogenerate produced anything else (e.g. unrelated diffs from environment drift), edit the file down to the following body:

```python
def upgrade() -> None:
    op.create_table(
        "generation_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("generation_log_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=30), nullable=False),
        sa.Column("question_id", sa.String(length=100), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("question_json", sa.JSON(), nullable=False),
        sa.Column("image_files", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["generation_log_id"], ["generation_logs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_generation_records_user_id"),
        "generation_records",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_generation_records_user_id"), table_name="generation_records")
    op.drop_table("generation_records")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_db_models.py -q
```

Expected: PASS — 4 tests green.

- [ ] **Step 6: Commit**

```bash
cd /workspace/exam-generation
git add server/models.py alembic/versions/ tests/server/test_db_models.py
git commit -m "feat(server): add generation_records model + Alembic migration (#30)"
```

---

### Task 3: Startup retention pruning (`GENERATION_HISTORY_RETENTION_DAYS`)

**Files:**
- Modify: `server/config.py` (add `generation_history_retention_days: int` field + env read)
- Modify: `server/app.py` (`lifespan` — prune inside the same `asyncio.to_thread` block as Alembic upgrade)
- Create: `tests/server/test_history_retention.py`

**Interfaces:**
- Consumes: `GenerationRecord` from Task 2, `ServerConfig`, `AsyncSessionLocal`.
- Produces: `_prune_generation_records(session, retention_days)` async helper in `server/app.py` (also imported by the test).

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_history_retention.py`:

```python
"""Startup pruning for generation_records (GENERATION_HISTORY_RETENTION_DAYS)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

from server.app import _prune_generation_records
from server.models import Base, GenerationRecord, User


def _seed(session_maker, ages_days):
    async def _run():
        async with session_maker() as session:
            user = User(id=uuid.uuid4(), email="u@example.com")
            session.add(user)
            await session.flush()
            now = datetime.now(timezone.utc)
            for age in ages_days:
                session.add(
                    GenerationRecord(
                        user_id=user.id,
                        subject="math",
                        question_id=f"q_{age}",
                        params_json={},
                        question_json={},
                        image_files=[],
                        created_at=now - timedelta(days=age),
                    )
                )
            await session.commit()
    asyncio.run(_run())


def _count(session_maker):
    async def _run():
        async with session_maker() as session:
            result = await session.execute(select(GenerationRecord))
            return len(result.scalars().all())
    return asyncio.run(_run())


def test_prune_keeps_all_when_retention_zero():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    _seed(sm, [0, 10, 100])

    async def prune():
        async with sm() as s:
            await _prune_generation_records(s, 0)
    asyncio.run(prune())

    assert _count(sm) == 3
    asyncio.run(engine.dispose())


def test_prune_deletes_rows_older_than_retention():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    _seed(sm, [1, 10, 45])

    async def prune():
        async with sm() as s:
            await _prune_generation_records(s, 30)
    asyncio.run(prune())

    assert _count(sm) == 2
    asyncio.run(engine.dispose())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_history_retention.py -q
```

Expected: FAIL with `ImportError: cannot import name '_prune_generation_records' from 'server.app'`.

- [ ] **Step 3: Add the config field**

Edit `server/config.py`:

1. In the `@dataclass class ServerConfig` block (before `email_whitelist`), add:

```python
    generation_history_retention_days: int = 0
```

2. In `from_env()` (inside the `return cls(...)` call, before the `email_whitelist=` line), add:

```python
            generation_history_retention_days=int(
                os.environ.get("GENERATION_HISTORY_RETENTION_DAYS", "0")
            ),
```

- [ ] **Step 4: Add the pruning helper and wire it into `lifespan`**

Edit `server/app.py`:

1. Add these imports near the existing top-of-file imports:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import AsyncSessionLocal
from server.models import GenerationRecord
```

2. Add the helper function above `lifespan`:

```python
async def _prune_generation_records(session: AsyncSession, retention_days: int) -> None:
    """Delete generation_records older than retention_days.

    retention_days == 0 keeps every row (default). Failures are logged
    by the caller so startup never aborts on a prune error.
    """
    if retention_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    await session.execute(
        delete(GenerationRecord).where(GenerationRecord.created_at < cutoff)
    )
    await session.commit()
```

3. Inside `lifespan`, immediately after the `await asyncio.to_thread(_run_alembic)` line (still inside the enclosing `try:`), append:

```python
        try:
            async with AsyncSessionLocal() as session:
                await _prune_generation_records(
                    session, config.generation_history_retention_days
                )
        except Exception as exc:  # pragma: no cover - best effort on startup
            print(
                f"Warning: generation_records prune failed: {exc}", file=sys.stderr
            )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_history_retention.py tests/server/test_db_models.py -q
```

Expected: PASS — 6 tests green (4 from Task 2 + 2 new).

- [ ] **Step 6: Commit**

```bash
cd /workspace/exam-generation
git add server/config.py server/app.py tests/server/test_history_retention.py
git commit -m "feat(server): prune generation_records on startup per GENERATION_HISTORY_RETENTION_DAYS (#30)"
```

---

### Task 4: Persist a `GenerationRecord` on every successful result

**Files:**
- Modify: `server/generate/service.py` (extend `generate_question_stream` to accept `user_id` + `generation_log_id`, write a row inside the result branch)
- Modify: `server/generate/routes.py` (pass `user.id` + `log_id` when calling `generate_question_stream`)
- Create: `tests/server/test_history_write.py`

**Interfaces:**
- Consumes: `GenerationRecord` (Task 2), `AsyncSessionLocal`, `GenerateParams`.
- Produces: `generate_question_stream(params, config, app_state, user_id=None, generation_log_id=None)` — new keyword args; older callers may omit them and no record is written.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_history_write.py`:

```python
"""When generate_question_stream yields a result event, one GenerationRecord is written."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_history_write.py -q
```

Expected: FAIL — `generate_question_stream()` does not accept `user_id` / `generation_log_id`.

- [ ] **Step 3: Extend the service to write records**

Edit `server/generate/service.py`:

1. Add imports near the existing top-of-file imports:

```python
import uuid
from server.db import AsyncSessionLocal
from server.models import GenerationRecord
```

2. Add a helper directly after `_question_to_event` (~ line 122):

```python
def _extract_image_files(question) -> list[str]:
    files: list[str] = []
    top = getattr(question, "圖片", None)
    if top:
        files.append(top)
    for sub in getattr(question, "subquestions", []) or []:
        sub_img = getattr(sub, "圖片", None)
        if sub_img:
            files.append(sub_img)
    return files


async def _persist_generation_record(
    *,
    user_id: uuid.UUID,
    generation_log_id: uuid.UUID | None,
    subject: str,
    params: GenerateParams,
    question,
) -> None:
    """Insert one generation_records row; log-and-swallow on failure."""
    try:
        record = GenerationRecord(
            user_id=user_id,
            generation_log_id=generation_log_id,
            subject=subject,
            question_id=question.id or "",
            params_json=params.model_dump(mode="json"),
            question_json=json.loads(question.model_dump_json(exclude_none=True)),
            image_files=_extract_image_files(question),
        )
        async with AsyncSessionLocal() as session:
            session.add(record)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort persistence
        logger.warning("failed to persist generation_record: %s", exc)
```

3. Change the `generate_question_stream` signature to accept the new kwargs:

```python
async def generate_question_stream(
    params: GenerateParams,
    config: ServerConfig,
    app_state: Any,
    user_id: uuid.UUID | None = None,
    generation_log_id: uuid.UUID | None = None,
) -> AsyncIterator[dict[str, Any]]:
```

4. Inside the outer `try:` around the `while True: event = await queue.get()` loop (~ lines 395-400), replace the loop with:

```python
    try:
        while True:
            event = await queue.get()
            if event["event"] == "result" and user_id is not None:
                # Best-effort: persist the completed question so /api/history
                # can serve it later. Uses the payload the worker just built.
                try:
                    payload = event["data"] if isinstance(event["data"], dict) else {}
                    question_id = payload.get("id", "")
                    record = GenerationRecord(
                        user_id=user_id,
                        generation_log_id=generation_log_id,
                        subject=params.subject,
                        question_id=question_id,
                        params_json=params.model_dump(mode="json"),
                        question_json={
                            k: v for k, v in payload.items() if k != "image_base64"
                            and not (
                                k == "subquestions"
                                and isinstance(v, list)
                            )
                        }
                        | (
                            {
                                "subquestions": [
                                    {k: v for k, v in sub.items() if k != "image_base64"}
                                    for sub in payload.get("subquestions", []) or []
                                ]
                            }
                            if isinstance(payload.get("subquestions"), list)
                            else {}
                        ),
                        image_files=[
                            f
                            for f in (
                                [payload.get("圖片")]
                                + [
                                    sub.get("圖片")
                                    for sub in payload.get("subquestions", []) or []
                                ]
                            )
                            if f
                        ],
                    )
                    async with AsyncSessionLocal() as session:
                        session.add(record)
                        await session.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("failed to persist generation_record: %s", exc)
            yield event
            if event["event"] in ("done", "error"):
                break
    finally:
        await signal_task
        if renderer_pool is not None and html_renderer is not None:
            await renderer_pool.put(html_renderer)
```

5. Edit `server/generate/routes.py` — inside `generate_endpoint`, change the `event_generator` body to pass `user.id` and `log_id`:

Locate the existing call `async for event in generate_question_stream(params, config, app_state):` (~ line 129) and change it to:

```python
                async for event in generate_question_stream(
                    params, config, app_state, user_id=user.id, generation_log_id=log_id
                ):
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_history_write.py tests/server/test_generate_routes.py -q
```

Expected: PASS — new test green; existing `test_generate_routes.py` still passes (added kwargs are optional in test call sites).

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add server/generate/service.py server/generate/routes.py tests/server/test_history_write.py
git commit -m "feat(server): persist generation_record on successful stream result (#30)"
```

---

### Task 5: History API routes (list / detail / download)

**Files:**
- Create: `server/history/__init__.py` (empty package marker)
- Create: `server/history/routes.py`
- Modify: `server/app.py` (include the new router)
- Create: `tests/server/test_history_routes.py`

**Interfaces:**
- Consumes: `GenerationRecord` (Task 2), `get_current_user`, `AsyncSessionLocal`, `ServerConfig`.
- Produces: FastAPI `router` mounted at `/api`, exposing:
  - `GET /api/history?limit&offset&subject` → `list[HistoryListItem]` (newest first)
  - `GET /api/history/{id}` → `HistoryDetail` (embeds `image_base64` per top-level + per-小題)
  - `GET /api/history/{id}/download` → `application/json` attachment

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_history_routes.py`:

```python
"""Tests for /api/history endpoints."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationRecord, User
from server.rate_limit import limiter


def _setup(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as s:
            yield s

    config = ServerConfig(
        api_key="x", jwt_secret="test-secret", output_dir=tmp_path, data_dir=Path("data")
    )

    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    async def add_users_and_rows():
        async with SessionLocal() as s:
            s.add(User(id=user_a, email="a@example.com"))
            s.add(User(id=user_b, email="b@example.com"))
            await s.flush()
            for i in range(3):
                s.add(GenerationRecord(
                    user_id=user_a,
                    subject="social_studies",
                    question_id=f"ss_a_{i}",
                    params_json={"subject": "social_studies"},
                    question_json={"id": f"ss_a_{i}", "核心問題": f"核心 {i}"},
                    image_files=[],
                ))
            s.add(GenerationRecord(
                user_id=user_b,
                subject="math",
                question_id="q_b_0",
                params_json={"subject": "math"},
                question_json={"id": "q_b_0", "題目": ["題目 0"]},
                image_files=[],
            ))
            await s.commit()
    asyncio.run(add_users_and_rows())

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    token_a = create_jwt(user_a, "a@example.com", config=config)
    return app, config, engine, SessionLocal, token_a, user_a, user_b


def test_list_history_returns_owner_rows_newest_first(tmp_path) -> None:
    app, _config, engine, _sm, token, _ua, _ub = _setup(tmp_path)
    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/history?limit=10",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert isinstance(body["items"], list)
            assert body["total"] == 3
            question_ids = [item["question_id"] for item in body["items"]]
            assert question_ids == ["ss_a_2", "ss_a_1", "ss_a_0"]
            assert all(item["subject"] == "social_studies" for item in body["items"])
            assert "preview" in body["items"][0]
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_list_history_filters_by_subject(tmp_path) -> None:
    app, _config, engine, _sm, token, _ua, _ub = _setup(tmp_path)
    try:
        with TestClient(app) as client:
            r = client.get(
                "/api/history?subject=math",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            assert r.json()["total"] == 0
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_detail_returns_owned_record_and_embeds_image_when_present(tmp_path) -> None:
    app, config, engine, SessionLocal, token, user_a, _ub = _setup(tmp_path)
    (config.output_dir / "ss_a_0.png").write_bytes(b"png-bytes")

    async def stamp_image():
        async with SessionLocal() as s:
            rows = (await s.execute(
                __import__("sqlalchemy").select(GenerationRecord).where(
                    GenerationRecord.question_id == "ss_a_0"
                )
            )).scalars().all()
            rows[0].image_files = ["ss_a_0.png"]
            rows[0].question_json = {"id": "ss_a_0", "圖片": "ss_a_0.png"}
            await s.commit()
    asyncio.run(stamp_image())

    try:
        with TestClient(app) as client:
            list_r = client.get(
                "/api/history?limit=10",
                headers={"Authorization": f"Bearer {token}"},
            )
            record_id = [
                item for item in list_r.json()["items"]
                if item["question_id"] == "ss_a_0"
            ][0]["id"]

            r = client.get(
                f"/api/history/{record_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["question_json"]["image_base64"] == "cG5nLWJ5dGVz"
            assert body["params_json"]["subject"] == "social_studies"
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_detail_degrades_when_image_file_missing(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, _ua, _ub = _setup(tmp_path)

    async def stamp_missing_image():
        async with SessionLocal() as s:
            rows = (await s.execute(
                __import__("sqlalchemy").select(GenerationRecord).where(
                    GenerationRecord.question_id == "ss_a_0"
                )
            )).scalars().all()
            rows[0].image_files = ["missing.png"]
            rows[0].question_json = {"id": "ss_a_0", "圖片": "missing.png"}
            await s.commit()
    asyncio.run(stamp_missing_image())

    try:
        with TestClient(app) as client:
            list_r = client.get(
                "/api/history",
                headers={"Authorization": f"Bearer {token}"},
            )
            record_id = [
                item for item in list_r.json()["items"]
                if item["question_id"] == "ss_a_0"
            ][0]["id"]

            r = client.get(
                f"/api/history/{record_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert "image_base64" not in body["question_json"]
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_detail_returns_404_for_other_users_record(tmp_path) -> None:
    app, _config, engine, SessionLocal, token, _ua, user_b = _setup(tmp_path)

    async def get_b_id():
        async with SessionLocal() as s:
            rows = (await s.execute(
                __import__("sqlalchemy").select(GenerationRecord).where(
                    GenerationRecord.user_id == user_b
                )
            )).scalars().all()
            return rows[0].id
    record_id = asyncio.run(get_b_id())

    try:
        with TestClient(app) as client:
            r = client.get(
                f"/api/history/{record_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 404
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())


def test_download_returns_attachment_with_content_disposition(tmp_path) -> None:
    app, _config, engine, _sm, token, _ua, _ub = _setup(tmp_path)
    try:
        with TestClient(app) as client:
            list_r = client.get(
                "/api/history",
                headers={"Authorization": f"Bearer {token}"},
            )
            record_id = list_r.json()["items"][0]["id"]
            r = client.get(
                f"/api/history/{record_id}/download",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("application/json")
            disp = r.headers["content-disposition"]
            assert "attachment" in disp
            assert ".json" in disp
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_history_routes.py -q
```

Expected: FAIL — 404 (routes don't exist).

- [ ] **Step 3: Create the history routes**

Create `server/history/__init__.py` (empty file).

Create `server/history/routes.py`:

```python
"""GET /api/history — user-scoped generation history browse + detail + download."""

from __future__ import annotations

import base64
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.models import GenerationRecord, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["history"])


def _preview(question_json: dict) -> str:
    """One-line preview: 核心問題 if present, otherwise first 題目 line, capped to 120 chars."""
    core = question_json.get("核心問題")
    if isinstance(core, str) and core.strip():
        return core.strip()[:120]
    subs = question_json.get("subquestions")
    if isinstance(subs, list) and subs:
        first_body = subs[0].get("題目")
        if isinstance(first_body, str) and first_body.strip():
            return first_body.strip().splitlines()[0][:120]
    body = question_json.get("題目")
    if isinstance(body, list) and body:
        first = body[0]
        if isinstance(first, str):
            return first.strip()[:120]
    return ""


def _verified(question_json: dict) -> bool:
    ver = question_json.get("verification")
    return bool(isinstance(ver, dict) and ver.get("passed"))


@router.get("/history")
async def list_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    subject: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Return the user's records newest-first with a short preview per row."""
    stmt = select(GenerationRecord).where(GenerationRecord.user_id == user.id)
    count_stmt = select(func.count()).select_from(GenerationRecord).where(
        GenerationRecord.user_id == user.id
    )
    if subject:
        stmt = stmt.where(GenerationRecord.subject == subject)
        count_stmt = count_stmt.where(GenerationRecord.subject == subject)
    stmt = stmt.order_by(GenerationRecord.created_at.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(count_stmt)).scalar_one()

    items = [
        {
            "id": str(r.id),
            "subject": r.subject,
            "question_id": r.question_id,
            "created_at": r.created_at.isoformat(),
            "preview": _preview(r.question_json or {}),
            "verified": _verified(r.question_json or {}),
        }
        for r in rows
    ]
    return {"total": int(total), "items": items}


async def _load_owned(
    record_id: str, user: User, session: AsyncSession
) -> GenerationRecord:
    try:
        rid = uuid.UUID(record_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    row = (
        await session.execute(
            select(GenerationRecord).where(
                GenerationRecord.id == rid,
                GenerationRecord.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


def _embed_images(question_json: dict, config: ServerConfig) -> dict:
    """Copy question_json and embed image_base64 for any PNG still on disk.

    Missing files are silently skipped — the record renders without them.
    """
    out = dict(question_json)
    top = out.get("圖片")
    if isinstance(top, str) and top:
        path = config.output_dir / top
        if path.exists():
            out["image_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
    subs = out.get("subquestions")
    if isinstance(subs, list):
        new_subs = []
        for sub in subs:
            if not isinstance(sub, dict):
                new_subs.append(sub)
                continue
            sub_copy = dict(sub)
            sub_img = sub_copy.get("圖片")
            if isinstance(sub_img, str) and sub_img:
                path = config.output_dir / sub_img
                if path.exists():
                    sub_copy["image_base64"] = base64.b64encode(
                        path.read_bytes()
                    ).decode("ascii")
            new_subs.append(sub_copy)
        out["subquestions"] = new_subs
    return out


@router.get("/history/{record_id}")
async def get_history_detail(
    record_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    config: ServerConfig = Depends(get_config),
) -> dict:
    row = await _load_owned(record_id, user, session)
    return {
        "id": str(row.id),
        "subject": row.subject,
        "question_id": row.question_id,
        "created_at": row.created_at.isoformat(),
        "params_json": row.params_json or {},
        "question_json": _embed_images(row.question_json or {}, config),
    }


@router.get("/history/{record_id}/download")
async def download_history(
    record_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    row = await _load_owned(record_id, user, session)
    body = json.dumps(row.question_json or {}, ensure_ascii=False, indent=2)
    filename = f"{row.question_id or row.id}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

Register the router in `server/app.py` — inside `create_app()`, next to the existing `include_router` calls, add:

```python
    from server.history.routes import router as history_router
    app.include_router(history_router)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_history_routes.py -q
```

Expected: PASS — 6 tests green.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add server/history/ server/app.py tests/server/test_history_routes.py
git commit -m "feat(server): add /api/history list/detail/download endpoints (#30)"
```

---

### Task 6: Frontend API client — `listHistory`, `getHistoryDetail`, `downloadHistoryJson`

**Files:**
- Modify: `web/src/api/client.ts` (append types + functions)
- Create: `web/src/api/history.test.ts`

**Interfaces:**
- Consumes: existing `apiFetch`, `ApiError`.
- Produces:
  - `interface HistoryListItem { id, subject, question_id, created_at, preview, verified }`
  - `interface HistoryListResponse { total: number; items: HistoryListItem[] }`
  - `interface HistoryDetail { id, subject, question_id, created_at, params_json, question_json }`
  - `listHistory(opts?): Promise<HistoryListResponse>`
  - `getHistoryDetail(id): Promise<HistoryDetail>`
  - `downloadHistoryJson(id): Promise<Blob>`

- [ ] **Step 1: Write the failing test**

Create `web/src/api/history.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../store/authStore", () => ({
  useAuthStore: {
    getState: () => ({ token: "TOK", logout: vi.fn() }),
  },
}));

import { downloadHistoryJson, getHistoryDetail, listHistory } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("history api client", () => {
  it("listHistory builds a query string with limit/offset/subject", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ total: 1, items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await listHistory({ limit: 5, offset: 10, subject: "math" });
    const url = (fetchMock.mock.calls[0][0] as string) || "";
    expect(url).toContain("/api/history?");
    expect(url).toContain("limit=5");
    expect(url).toContain("offset=10");
    expect(url).toContain("subject=math");
  });

  it("getHistoryDetail returns parsed JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "abc",
          subject: "social_studies",
          question_id: "ss_1",
          created_at: "2026-07-15T00:00:00Z",
          params_json: {},
          question_json: {},
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const detail = await getHistoryDetail("abc");
    expect(detail.subject).toBe("social_studies");
  });

  it("downloadHistoryJson returns a Blob", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response('{"a":1}', {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const blob = await downloadHistoryJson("abc");
    expect(blob).toBeInstanceOf(Blob);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/exam-generation/web
npm test -- src/api/history.test.ts
```

Expected: FAIL — the three functions don't exist yet.

- [ ] **Step 3: Extend the API client**

Append to `web/src/api/client.ts`:

```ts
export interface HistoryListItem {
  id: string;
  subject: string;
  question_id: string;
  created_at: string;
  preview: string;
  verified: boolean;
}

export interface HistoryListResponse {
  total: number;
  items: HistoryListItem[];
}

export interface HistoryDetail {
  id: string;
  subject: string;
  question_id: string;
  created_at: string;
  params_json: Record<string, unknown>;
  question_json: Record<string, unknown>;
}

export interface ListHistoryOpts {
  limit?: number;
  offset?: number;
  subject?: string;
}

export async function listHistory(
  opts: ListHistoryOpts = {},
): Promise<HistoryListResponse> {
  const params = new URLSearchParams();
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  if (opts.subject) params.set("subject", opts.subject);
  const suffix = params.toString();
  const res = await apiFetch(
    suffix ? `/api/history?${suffix}` : "/api/history",
  );
  return (await res.json()) as HistoryListResponse;
}

export async function getHistoryDetail(id: string): Promise<HistoryDetail> {
  const res = await apiFetch(`/api/history/${encodeURIComponent(id)}`);
  return (await res.json()) as HistoryDetail;
}

export async function downloadHistoryJson(id: string): Promise<Blob> {
  const res = await apiFetch(`/api/history/${encodeURIComponent(id)}/download`);
  return await res.blob();
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /workspace/exam-generation/web
npm test -- src/api/history.test.ts
```

Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add web/src/api/client.ts web/src/api/history.test.ts
git commit -m "feat(web): add listHistory/getHistoryDetail/downloadHistoryJson client (#30)"
```

---

### Task 7: `HistoryPage` list view + `/history` route + i18n + nav link

**Files:**
- Modify: `web/src/i18n/messages.ts` (add `history.*` keys to both language blocks)
- Create: `web/src/pages/HistoryPage.tsx`
- Create: `web/src/pages/HistoryPage.test.tsx`
- Modify: `web/src/App.tsx` (mount `/history` behind `AuthGuard`)
- Modify: `web/src/pages/GeneratePage.tsx:117-152` (header — add nav link to `/history` between the back arrow and the language switcher)

**Interfaces:**
- Consumes: `listHistory` (Task 6), `useT`, `useNavigate`, `useAuthStore`.
- Produces: `HistoryPage` default export listing rows with pagination controls and clickable rows that navigate to `/history/:id` (detail rendered in Task 8).

- [ ] **Step 1: Add i18n keys**

In `web/src/i18n/messages.ts`, add to the `"en-US"` block, directly after the existing `"generate.btn_clear"` line (~ line 39):

```ts
    "history.title": "Generation history",
    "history.nav_link": "History",
    "history.empty": "No past generations yet — head back to the generator to create one.",
    "history.subject_math": "Math",
    "history.subject_ss": "Social Studies",
    "history.subject_ns": "Natural Sciences",
    "history.verified_badge": "Verified",
    "history.prev_page": "Previous",
    "history.next_page": "Next",
    "history.filter_subject_all": "All subjects",
    "history.btn_back_list": "Back to history",
    "history.btn_download_json": "Download JSON",
    "history.btn_regenerate": "Re-run in generator",
    "history.detail_loading": "Loading…",
    "history.detail_error": "Failed to load record.",
    "history.prefill_notice": "Some saved parameters are no longer available in the current schema and were left at their defaults.",
```

And to the `"zh-TW"` block, directly after its `"generate.btn_clear"` line:

```ts
    "history.title": "產生紀錄",
    "history.nav_link": "紀錄",
    "history.empty": "尚無過去的產生紀錄——請回到產生器產生題目。",
    "history.subject_math": "數學",
    "history.subject_ss": "社會",
    "history.subject_ns": "自然",
    "history.verified_badge": "已驗證",
    "history.prev_page": "上一頁",
    "history.next_page": "下一頁",
    "history.filter_subject_all": "全部科目",
    "history.btn_back_list": "回到紀錄列表",
    "history.btn_download_json": "下載 JSON",
    "history.btn_regenerate": "帶入產生器重跑",
    "history.detail_loading": "載入中…",
    "history.detail_error": "紀錄讀取失敗。",
    "history.prefill_notice": "部分儲存的參數已不在目前的題目設定中，保留為預設值。",
```

- [ ] **Step 2: Write the failing tests**

Create `web/src/pages/HistoryPage.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (s: { user: { email: string } | null }) => unknown) =>
    selector({ user: { email: "u@example.com" } }),
}));

const listHistoryMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  listHistory: listHistoryMock,
}));

import HistoryPage from "./HistoryPage";

describe("HistoryPage (list mode)", () => {
  it("renders rows returned by listHistory", async () => {
    listHistoryMock.mockResolvedValueOnce({
      total: 2,
      items: [
        {
          id: "id-1",
          subject: "social_studies",
          question_id: "ss_1",
          created_at: "2026-07-15T00:00:00Z",
          preview: "全球暖化與都市規劃",
          verified: true,
        },
        {
          id: "id-2",
          subject: "math",
          question_id: "q_1",
          created_at: "2026-07-14T00:00:00Z",
          preview: "一元一次方程式",
          verified: false,
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/history"]}>
        <Routes>
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByText("全球暖化與都市規劃")).toBeInTheDocument(),
    );
    expect(screen.getByText("一元一次方程式")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });

  it("shows the empty-state message when the API returns no items", async () => {
    listHistoryMock.mockResolvedValueOnce({ total: 0, items: [] });

    render(
      <MemoryRouter initialEntries={["/history"]}>
        <Routes>
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/No past generations yet/i),
      ).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /workspace/exam-generation/web
npm test -- src/pages/HistoryPage.test.tsx
```

Expected: FAIL — cannot resolve `./HistoryPage`.

- [ ] **Step 4: Create the page component**

Create `web/src/pages/HistoryPage.tsx`:

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import LanguageSwitcher from "../components/LanguageSwitcher";
import { useT } from "../i18n/useT";
import {
  listHistory,
  type HistoryListItem,
  type HistoryListResponse,
} from "../api/client";
import { useAuthStore } from "../store/authStore";
import HistoryDetail from "./HistoryDetail";

const PAGE_SIZE = 20;

function subjectLabel(t: (k: string) => string, subject: string): string {
  if (subject === "math") return t("history.subject_math");
  if (subject === "social_studies") return t("history.subject_ss");
  if (subject === "natural_sciences") return t("history.subject_ns");
  return subject;
}

export default function HistoryPage() {
  const params = useParams<{ id?: string }>();
  if (params.id) {
    return <HistoryDetail recordId={params.id} />;
  }
  return <HistoryList />;
}

function HistoryList() {
  const navigate = useNavigate();
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const [data, setData] = useState<HistoryListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [subject, setSubject] = useState<string>("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await listHistory({
        limit: PAGE_SIZE,
        offset,
        subject: subject || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "error");
    }
  }, [offset, subject]);

  useEffect(() => {
    void load();
  }, [load]);

  const items: HistoryListItem[] = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total ?? 0;
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-2 px-3 py-3 sm:px-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate("/generate")}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              ←
            </button>
            <h1 className="text-base font-semibold sm:text-lg">
              {t("history.title")}
            </h1>
          </div>
          <div className="flex items-center gap-2 text-sm sm:gap-3">
            <LanguageSwitcher />
            {user && (
              <span className="hidden max-w-[12rem] truncate text-gray-700 sm:inline">
                {user.email}
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-4 px-3 py-4 sm:px-4 sm:py-6">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-700">
            <select
              value={subject}
              onChange={(e) => {
                setSubject(e.target.value);
                setOffset(0);
              }}
              className="ml-2 rounded border border-gray-300 bg-white px-2 py-1 text-sm"
            >
              <option value="">{t("history.filter_subject_all")}</option>
              <option value="math">{t("history.subject_math")}</option>
              <option value="social_studies">{t("history.subject_ss")}</option>
              <option value="natural_sciences">{t("history.subject_ns")}</option>
            </select>
          </label>
        </div>

        {error && (
          <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {data && items.length === 0 && !error && (
          <div className="rounded border bg-white p-6 text-center text-sm text-gray-600 shadow-sm">
            {t("history.empty")}
          </div>
        )}

        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id}>
              <Link
                to={`/history/${item.id}`}
                className="flex flex-col gap-1 rounded border bg-white p-3 shadow-sm hover:border-blue-400"
              >
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span className="rounded bg-gray-100 px-2 py-0.5 font-medium text-gray-700">
                    {subjectLabel(t, item.subject)}
                  </span>
                  <span>{new Date(item.created_at).toLocaleString()}</span>
                </div>
                <div className="text-sm text-gray-800">{item.preview}</div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-gray-500">{item.question_id}</span>
                  {item.verified && (
                    <span className="rounded bg-green-100 px-1.5 py-0.5 font-medium text-green-700">
                      {t("history.verified_badge")}
                    </span>
                  )}
                </div>
              </Link>
            </li>
          ))}
        </ul>

        <div className="flex items-center justify-between">
          <button
            type="button"
            disabled={!hasPrev}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("history.prev_page")}
          </button>
          <button
            type="button"
            disabled={!hasNext}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("history.next_page")}
          </button>
        </div>
      </main>
    </div>
  );
}
```

Also create a placeholder `web/src/pages/HistoryDetail.tsx` so this task compiles standalone — Task 8 will fill it in:

```tsx
export interface HistoryDetailProps {
  recordId: string;
}

/** Placeholder — Task 8 replaces this with the full detail view. */
export default function HistoryDetail({ recordId }: HistoryDetailProps) {
  return (
    <div className="min-h-screen bg-gray-50 p-6 text-sm text-gray-600">
      Loading record {recordId}…
    </div>
  );
}
```

- [ ] **Step 5: Mount the route in `App.tsx`**

Edit `web/src/App.tsx` — import `HistoryPage` and register two routes (`/history` and `/history/:id`) inside `<Routes>`, both wrapped in `<AuthGuard>`. The full file becomes:

```tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import AuthGuard from "./components/AuthGuard";
import StagingBanner from "./components/StagingBanner";
import LoginPage from "./pages/LoginPage";
import VerifyPage from "./pages/VerifyPage";
import GeneratePage from "./pages/GeneratePage";
import HistoryPage from "./pages/HistoryPage";
import SubjectSelectPage from "./pages/SubjectSelectPage";

export default function App() {
  return (
    <BrowserRouter>
      <StagingBanner />
      <Routes>
        <Route path="/" element={<LoginPage />} />
        <Route path="/verify" element={<VerifyPage />} />
        <Route
          path="/generate"
          element={
            <AuthGuard>
              <SubjectSelectPage />
            </AuthGuard>
          }
        />
        <Route
          path="/generate/math"
          element={
            <AuthGuard>
              <GeneratePage subject="math" />
            </AuthGuard>
          }
        />
        <Route
          path="/generate/social_studies"
          element={
            <AuthGuard>
              <GeneratePage subject="social_studies" />
            </AuthGuard>
          }
        />
        <Route
          path="/generate/natural_sciences"
          element={
            <AuthGuard>
              <GeneratePage subject="natural_sciences" />
            </AuthGuard>
          }
        />
        <Route
          path="/history"
          element={
            <AuthGuard>
              <HistoryPage />
            </AuthGuard>
          }
        />
        <Route
          path="/history/:id"
          element={
            <AuthGuard>
              <HistoryPage />
            </AuthGuard>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 6: Add the nav link on `GeneratePage`**

Edit `web/src/pages/GeneratePage.tsx` at the header block (currently lines 117–152). Insert a `history` nav link between the language switcher and the logout button (still inside the second `<div>` at line 136). Replace lines 136–150 with:

```tsx
          <div className="flex min-w-0 items-center gap-2 text-sm sm:gap-3">
            <LanguageSwitcher />
            <button
              type="button"
              onClick={() => navigate("/history")}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("history.nav_link")}
            </button>
            {user && (
              <span className="hidden max-w-[12rem] truncate text-gray-700 sm:inline">
                {user.email}
              </span>
            )}
            <button
              type="button"
              onClick={handleLogout}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("generate.btn_logout")}
            </button>
          </div>
```

- [ ] **Step 7: Run tests, lint, and build**

```bash
cd /workspace/exam-generation/web
npm test -- src/pages/HistoryPage.test.tsx
npm run lint
npm run build
```

Expected: all tests pass, lint clean, build succeeds.

- [ ] **Step 8: Commit**

```bash
cd /workspace/exam-generation
git add web/src/i18n/messages.ts web/src/pages/HistoryPage.tsx web/src/pages/HistoryPage.test.tsx web/src/pages/HistoryDetail.tsx web/src/App.tsx web/src/pages/GeneratePage.tsx
git commit -m "feat(web): add /history list page + nav link on GeneratePage (#30)"
```

---

### Task 8: `HistoryDetail` — full record view with regenerate + download

**Files:**
- Modify: `web/src/pages/HistoryDetail.tsx` (replace placeholder from Task 7)
- Create: `web/src/pages/HistoryDetail.test.tsx`

**Interfaces:**
- Consumes: `getHistoryDetail`, `downloadHistoryJson` (Task 6); `QuestionCard`; `useNavigate` from react-router-dom.
- Produces: default-exported `HistoryDetail({ recordId })` React component.
- Router state contract (consumed in Task 9): navigating to `/generate/<subject>` with `state: { prefillParams: HistoryDetail.params_json }` triggers ParamForm prefill.

- [ ] **Step 1: Write the failing tests**

Create `web/src/pages/HistoryDetail.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getDetailMock = vi.hoisted(() => vi.fn());
const downloadMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  getHistoryDetail: getDetailMock,
  downloadHistoryJson: downloadMock,
}));

vi.mock("../components/QuestionCard", () => ({
  default: ({ question }: { question: { id?: string } }) => (
    <div data-testid="qc">{question?.id ?? ""}</div>
  ),
}));

import HistoryDetail from "./HistoryDetail";

function LocationSpy() {
  const loc = useLocation();
  return (
    <div data-testid="loc-state">{JSON.stringify(loc.state ?? null)}</div>
  );
}

describe("HistoryDetail", () => {
  it("renders the stored question and calls the download API", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "abc",
      subject: "social_studies",
      question_id: "ss_1",
      created_at: "2026-07-15T00:00:00Z",
      params_json: { subject: "social_studies", grade: 8 },
      question_json: { id: "ss_1", 核心問題: "核心" },
    });
    downloadMock.mockResolvedValueOnce(new Blob(["{}"], { type: "application/json" }));

    render(
      <MemoryRouter initialEntries={["/history/abc"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="abc" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("qc")).toHaveTextContent("ss_1"));

    fireEvent.click(screen.getByRole("button", { name: /Download JSON/i }));
    await waitFor(() => expect(downloadMock).toHaveBeenCalledWith("abc"));
  });

  it("regenerate button navigates to /generate/<subject> with params in router state", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "abc",
      subject: "social_studies",
      question_id: "ss_1",
      created_at: "2026-07-15T00:00:00Z",
      params_json: { subject: "social_studies", grade: 8, topic: "climate" },
      question_json: { id: "ss_1" },
    });

    render(
      <MemoryRouter initialEntries={["/history/abc"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="abc" />} />
          <Route path="/generate/social_studies" element={<LocationSpy />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Re-run in generator/i }))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Re-run in generator/i }));

    await waitFor(() =>
      expect(screen.getByTestId("loc-state").textContent).toContain(
        '"topic":"climate"',
      ),
    );
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/exam-generation/web
npm test -- src/pages/HistoryDetail.test.tsx
```

Expected: FAIL — placeholder component has no Download / Re-run buttons.

- [ ] **Step 3: Replace `HistoryDetail.tsx` with the full implementation**

Overwrite `web/src/pages/HistoryDetail.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import QuestionCard from "../components/QuestionCard";
import type { ExamQuestion } from "../hooks/useGenerate";
import { useT } from "../i18n/useT";
import {
  downloadHistoryJson,
  getHistoryDetail,
  type HistoryDetail as HistoryDetailPayload,
} from "../api/client";

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export interface HistoryDetailProps {
  recordId: string;
}

export default function HistoryDetail({ recordId }: HistoryDetailProps) {
  const t = useT();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<HistoryDetailPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setDetail(null);
    getHistoryDetail(recordId)
      .then((res) => {
        if (!cancelled) setDetail(res);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "error");
      });
    return () => {
      cancelled = true;
    };
  }, [recordId]);

  const handleDownload = async () => {
    if (!detail) return;
    const blob = await downloadHistoryJson(recordId);
    saveBlob(blob, `${detail.question_id || detail.id}.json`);
  };

  const handleRegenerate = () => {
    if (!detail) return;
    navigate(`/generate/${detail.subject}`, {
      state: { prefillParams: detail.params_json },
    });
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-2 px-3 py-3 sm:px-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate("/history")}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              ← {t("history.btn_back_list")}
            </button>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!detail}
              onClick={handleDownload}
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {t("history.btn_download_json")}
            </button>
            <button
              type="button"
              disabled={!detail}
              onClick={handleRegenerate}
              className="rounded border border-blue-600 bg-white px-3 py-1.5 text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-50"
            >
              {t("history.btn_regenerate")}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-4 px-3 py-4 sm:px-4 sm:py-6">
        {error && (
          <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {t("history.detail_error")} {error}
          </div>
        )}
        {!detail && !error && (
          <div className="text-sm text-gray-500">{t("history.detail_loading")}</div>
        )}
        {detail && (
          <QuestionCard
            question={detail.question_json as unknown as ExamQuestion}
            phase="verified"
            isFinal
          />
        )}
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /workspace/exam-generation/web
npm test -- src/pages/HistoryDetail.test.tsx
```

Expected: PASS — 2 tests green.

- [ ] **Step 5: Full frontend verification**

```bash
cd /workspace/exam-generation/web
npm test && npm run lint && npm run build
```

Expected: all tests pass, lint clean, build succeeds.

- [ ] **Step 6: Commit**

```bash
cd /workspace/exam-generation
git add web/src/pages/HistoryDetail.tsx web/src/pages/HistoryDetail.test.tsx
git commit -m "feat(web): add /history/:id detail view with download + regenerate (#30)"
```

---

### Task 9: `ParamForm` prefill from router state + missing-schema notice

**Files:**
- Modify: `web/src/pages/GeneratePage.tsx` (read `location.state.prefillParams`, pass into `ParamForm` as `initialParams`, expose a notice slot)
- Modify: `web/src/components/ParamForm.tsx` (accept optional `initialParams` prop, initialize state from it, compute a `missingKeys` notice after schemas load)
- Modify: `web/src/components/QuestionCard.test.tsx` — no change; only mentioned to confirm the ParamForm edits don't break its snapshot expectations.
- Create: `web/src/components/ParamForm.test.tsx`

**Interfaces:**
- Consumes: `GenerateParams` (backend query shape from `web/src/hooks/useGenerate.ts` — the same fields serialized into `params_json`).
- Produces:
  - `ParamForm` accepts `initialParams?: Partial<GenerateParams>` (from `web/src/components/ParamForm.tsx`'s exported `GenerateParams` interface).
  - After schemas load, values in `initialParams` that no longer exist in the current `schemas` are dropped and a translated notice with i18n key `history.prefill_notice` is rendered above the form.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/ParamForm.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getSchemasMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
}));

import ParamForm from "./ParamForm";

const FAKE_MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [
    { value: "個人", instruction: "" },
    { value: "社會時事", instruction: "" },
  ],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "textbook", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

describe("ParamForm prefill", () => {
  it("initializes visible fields from initialParams", async () => {
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);

    render(
      <ParamForm
        subject="math"
        disabled={false}
        onSubmit={() => {}}
        initialParams={{ grade: 8, topic: "climate change" }}
      />,
    );

    await waitFor(() =>
      expect(screen.getByDisplayValue("climate change")).toBeInTheDocument(),
    );
    expect((screen.getByLabelText(/Grade/i) as HTMLSelectElement).value).toBe("8");
  });

  it("shows the prefill-notice when initialParams contain values not in the current schema", async () => {
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);

    render(
      <ParamForm
        subject="math"
        disabled={false}
        onSubmit={() => {}}
        initialParams={{
          grade: 8,
          context: ["個人", "已刪除情境"],
          set_type: "已刪除設定",
        }}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/Some saved parameters are no longer available/i),
      ).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/exam-generation/web
npm test -- src/components/ParamForm.test.tsx
```

Expected: FAIL — `ParamForm` doesn't accept `initialParams` yet; no notice element.

- [ ] **Step 3: Edit `web/src/components/ParamForm.tsx`**

1. Extend the `ParamFormProps` interface (currently at ~ line 44):

```ts
export interface ParamFormProps {
  subject?: string;
  onSubmit: (params: GenerateParams) => void;
  disabled: boolean;
  initialParams?: Partial<GenerateParams> & { [key: string]: unknown };
}
```

2. Change the default export signature to accept it:

```ts
export default function ParamForm({
  subject = "math",
  onSubmit,
  disabled,
  initialParams,
}: ParamFormProps) {
```

3. For each `useState<...>(...)` at lines 188-213, replace the literal default with a lookup from `initialParams` when the key is present. Add this helper at the top of the function body (before the first `useState`):

```ts
  const ip = initialParams ?? {};
  function fromInit<T>(key: string, fallback: T): T {
    return (ip[key] as T | undefined) ?? fallback;
  }
```

Then rewrite the state initializers:

```ts
  const [grade, setGrade] = useState<number | "">(fromInit<number | "">("grade", ""));
  const [style, setStyle] = useState<string>(fromInit<string>("style", ""));
  const [contentType, setContentType] = useState<string>(
    fromInit<string>("content_type", "純文字"),
  );
  const [customContentType, setCustomContentType] = useState<string>("");
  const [context, setContext] = useState<string[]>(fromInit<string[]>("context", []));
  const [setType, setSetType] = useState<string>(fromInit<string>("set_type", ""));
  const [qType, setQType] = useState<string[]>(fromInit<string[]>("q_type", []));
  const [count, setCount] = useState<number>(fromInit<number>("count", 1));
  const [skipVerify, setSkipVerify] = useState<boolean>(
    fromInit<boolean>("skip_verify", false),
  );
  const [disableReferenceFewshot, setDisableReferenceFewshot] =
    useState<boolean>(fromInit<boolean>("disable_reference_fewshot", false));
  const [imageGenerationMode, setImageGenerationMode] =
    useState<"html" | "gpt_image">(
      fromInit<"html" | "gpt_image">("image_generation_mode", "html"),
    );
  const [subjectFilter, setSubjectFilter] = useState<string>(
    fromInit<string>("subject_filter", ""),
  );
  const [passage, setPassage] = useState<string>(fromInit<string>("passage", TEXT_HINT));
  const [textWordLimit, setTextWordLimit] = useState<number | undefined>(
    fromInit<number | undefined>("text_word_limit", undefined),
  );
  const [options, setOptions] = useState<string[]>(
    fromInit<string[]>("options", [OPTION_HINT, OPTION_HINT, OPTION_HINT, OPTION_HINT]),
  );
  const [topic, setTopic] = useState<string>(fromInit<string>("topic", ""));
  const [coreQuestion, setCoreQuestion] = useState<string | null>(
    fromInit<string | null>("core_question", null),
  );
  const [subContext, setSubContext] = useState<string>(fromInit<string>("sub_context", ""));
  const [scienceCompetency, setScienceCompetency] = useState<string[]>(
    fromInit<string[]>("science_competency", []),
  );
  const [learningPerformance, setLearningPerformance] = useState<string[]>(
    fromInit<string[]>("learning_performance", []),
  );
  const [learningContent, setLearningContent] = useState<string[]>(
    fromInit<string[]>("learning_content", []),
  );
  const [useCurriculumSearch, setUseCurriculumSearch] = useState<boolean>(false);
  const [subQuestionCount, setSubQuestionCount] = useState<number | "">(
    fromInit<number | "">("sub_question_count", ""),
  );
  const [subquestionConfigs, setSubquestionConfigs] = useState<SubQuestionConfig[]>(
    fromInit<SubQuestionConfig[]>("subquestion_configs", []),
  );
```

4. Add a missing-keys notice. Just after the existing `useEffect` that fetches schemas (find the block that calls `getSchemas(...).then(setSchemas)`), append:

```ts
  const [prefillNotice, setPrefillNotice] = useState<string | null>(null);
  useEffect(() => {
    if (!schemas || !initialParams) return;
    const missing: string[] = [];
    const arr = (key: string): string[] => {
      const raw = (initialParams as Record<string, unknown>)[key];
      return Array.isArray(raw) ? (raw as string[]) : [];
    };
    const single = (key: string): string | undefined => {
      const raw = (initialParams as Record<string, unknown>)[key];
      return typeof raw === "string" ? raw : undefined;
    };
    const check = (
      key: string,
      values: string[],
      allowed: string[] | undefined,
    ): void => {
      if (!allowed) return;
      for (const v of values) if (!allowed.includes(v)) missing.push(`${key}: ${v}`);
    };
    check("情境", arr("context"), schemas.情境?.map((s) => s.value));
    check("題型", arr("q_type"), schemas.題型?.map((s) => s.value));
    const st = single("set_type");
    if (st !== undefined) {
      check("題型種類", [st], schemas.題型種類?.map((s) => s.value));
    }
    check(
      "科目",
      arr("subject_filter"),
      schemas.科目?.map((s) => s.value),
    );
    if (missing.length > 0) {
      setPrefillNotice(t("history.prefill_notice"));
      // Drop the missing entries so the form submits a clean payload.
      const allowedCtx = new Set(schemas.情境?.map((s) => s.value));
      setContext((prev) => prev.filter((v) => allowedCtx.has(v)));
      const allowedQT = new Set(schemas.題型?.map((s) => s.value));
      setQType((prev) => prev.filter((v) => allowedQT.has(v)));
      const allowedST = new Set(schemas.題型種類?.map((s) => s.value));
      setSetType((prev) => (allowedST.has(prev) ? prev : ""));
    } else {
      setPrefillNotice(null);
    }
  }, [schemas, initialParams, t]);
```

5. Render the notice above the first fieldset in the returned JSX. Locate the outer form container (the one returned near the bottom of `ParamForm`) and insert directly under its opening tag:

```tsx
      {prefillNotice && (
        <div className="mb-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-800">
          {prefillNotice}
        </div>
      )}
```

- [ ] **Step 4: Edit `web/src/pages/GeneratePage.tsx` to forward router state**

Locate the imports at the top and add:

```tsx
import { useLocation, useNavigate } from "react-router-dom";
```

(replace the existing `useNavigate` import.)

Inside `GeneratePage`, right after `const navigate = useNavigate();` (line 29), add:

```tsx
  const location = useLocation();
  const prefillParams =
    (location.state as { prefillParams?: Record<string, unknown> } | null)
      ?.prefillParams ?? null;
```

Then update the `<ParamForm ... />` call inside the returned JSX (line 156) to pass it through:

```tsx
          <ParamForm
            subject={subject}
            onSubmit={handleSubmit}
            disabled={status === "generating" || status === "queued"}
            initialParams={prefillParams ?? undefined}
          />
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /workspace/exam-generation/web
npm test -- src/components/ParamForm.test.tsx src/pages/HistoryDetail.test.tsx src/pages/HistoryPage.test.tsx
```

Expected: PASS — all previously-added tests still pass, plus the two new ParamForm tests.

- [ ] **Step 6: Full frontend verification**

```bash
cd /workspace/exam-generation/web
npm test && npm run lint && npm run build
```

Expected: all tests pass, lint clean, build succeeds.

- [ ] **Step 7: Final backend regression pass**

```bash
cd /workspace/exam-generation
uv run pytest tests/server/ -q
```

Expected: all server tests green (Task 2-5 additions + existing suites).

- [ ] **Step 8: Commit**

```bash
cd /workspace/exam-generation
git add web/src/components/ParamForm.tsx web/src/components/ParamForm.test.tsx web/src/pages/GeneratePage.tsx
git commit -m "feat(web): prefill ParamForm from history router state with missing-schema notice (#30)"
```

---

## Spec coverage check

| Spec requirement | Covered by |
|---|---|
| New `generation_records` table with the 8 columns | Task 2 |
| Images stay on disk; DB stores filenames | Task 2 (schema) + Task 4 (write path) |
| Insert one row per successful question, warn-not-fail | Task 4 |
| `GET /api/history?limit&offset&subject` newest-first with preview + verified | Task 5 |
| `GET /api/history/{id}` embeds `image_base64` per detail-view convention | Task 5 |
| `GET /api/history/{id}/download` JSON attachment | Task 5 |
| Ownership: 404 for other users' records | Task 5 |
| New `/history` route + nav link on GeneratePage header | Task 7 |
| Paginated list (subject chip, preview, date, verified badge) | Task 7 |
| Detail view reuses `QuestionCard` with Download JSON | Task 8 |
| Regenerate button navigates to `/generate/<subject>` with stored params | Task 8 |
| Env `GENERATION_HISTORY_RETENTION_DAYS` (default 0 = keep forever); startup prune mirroring #113 | Task 3 |
| Pruning deletes DB rows only, no file cleanup | Task 3 (helper deletes only) |
| Missing image files → render without images (no 500) | Task 5 (`_embed_images` skips missing) + Task 5 test `test_detail_degrades_when_image_file_missing` |
| Stored params referencing removed schema values → prefill what's possible, leave rest at defaults, show notice | Task 9 |
| pytest tests (write, list pagination + ownership, detail image degradation, download) | Tasks 4, 5 |
| Vitest tests (HistoryPage list from mocked API; regenerate carries params) | Tasks 7, 8, 9 |
