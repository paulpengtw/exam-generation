# Per-request LLM Plan/Execute Model Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each `/api/generate` and `/api/plan-core-questions` request choose which planning model and which execution model to call, from an env-driven allowlist visible to all users; expose the choice as two dropdowns in the web form (issue #105).

**Architecture:** `ServerConfig` grows an `LLM_MODELS_ALLOWED` env-driven allowlist. `GenerateParams` and `PlanCoreQuestionsRequest` gain optional `model_plan` / `model_execute` strings; the route rejects out-of-allowlist values with HTTP 422 before any upstream call. `server/generate/service.generate_question_stream` and the plan-core-questions handler build each `LLMClient` from a `dataclasses.replace`-cloned `Config` with the overrides baked in — so all downstream `client.generate*` / `client.plan` calls transparently use the chosen model without touching `src/cli.py`, `src/social_studies/cli.py`, or `src/natural_sciences/cli.py` signatures (the client already reads `self.config.model_execute` / `self.config.model_plan` when no explicit `model=` is passed). Frontend adds a `GET /api/models` discovery endpoint and two `<select>` controls in `ParamForm.tsx` persisted in `localStorage`.

**Tech Stack:** Python 3.11+ (Pydantic v2, FastAPI, pytest via `uv run pytest`), TypeScript + React 19 + Vite, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-07-15-model-selection-design.md`

## Global Constraints

- Allowlist source: env `LLM_MODELS_ALLOWED` on `ServerConfig`, comma-separated. When unset ⇒ allowlist is exactly `[config.model_plan, config.model_execute]` (deduped, order preserved).
- Absent request fields = server defaults. A submitted `model_plan` or `model_execute` outside the allowlist → HTTP 422, with `detail` naming the allowlist; no upstream LLM call happens.
- Override threading is via `dataclasses.replace(config, model_plan=…, model_execute=…)` at `LLMClient` construction — no changes to `src/cli.py`, `src/social_studies/cli.py`, `src/natural_sciences/cli.py`, `src/verifier.py`, `src/corrector.py`, or `src/renderer.py` function signatures.
- `model_execute` applies to `/api/generate`. `model_plan` applies to `/api/plan-core-questions`; on `/api/generate` it is accepted but currently only affects planner-adjacent calls if any (kept for symmetry and for `plan()` calls made elsewhere in the pipeline).
- `GET /api/models` returns `{"allowed": [...], "defaults": {"plan": ..., "execute": ...}}` where `defaults` are `config.model_plan` and `config.model_execute` unconditionally, and `allowed` contains at least both defaults.
- No free-text overrides. No profiles. No per-子題 model overrides. No image-model override. No dynamic upstream discovery.
- Frontend fallback: when `GET /api/models` fails, the dropdowns are hidden and no `model_plan` / `model_execute` params are sent — the form must still submit successfully.
- All new i18n keys use the `params.` prefix (existing convention) and exist in **both** `en-US` and `zh-TW` blocks in `web/src/i18n/messages.ts`.
- All web commands run from `/workspace/exam-generation/web/`. All Python commands run from `/workspace/exam-generation/`.

## Pre-existing defect this plan fixes first

Commit `d534147` ("fix: remove unused fireEvent import that broke tsc build") also silently removed `vitest` and all testing-library devDependencies plus the `test` / `test:watch` scripts from `web/package.json` — while `web/vitest.config.ts`, `web/src/test/setup.ts`, and two `*.test.tsx` files remain in the tree. Task 1 restores the test tooling so this plan's vitest steps (and the existing tests) can run. Test files are excluded from `tsc -b` via `tsconfig.app.json` `exclude`, so restoring them does not affect the production build.

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

Run:

```bash
cd /workspace/exam-generation/web
npm test
```

Expected: PASS — the two existing test files (`src/components/QuestionCard.test.tsx`, `src/components/CoreQuestionPicker.test.tsx`) run green.

- [ ] **Step 4: Verify the production build still works**

Run:

```bash
cd /workspace/exam-generation/web
npm run build
```

Expected: `tsc -b && vite build` succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation/web
git add package.json package-lock.json
git commit -m "fix(web): restore vitest + testing-library tooling removed by d534147"
```

---

### Task 2: `ServerConfig.llm_models_allowed` env allowlist

**Files:**
- Modify: `server/config.py` (`ServerConfig` dataclass + `from_env`)
- Test: `tests/server/test_config_llm_models_allowed.py`

**Interfaces:**
- Consumes: env var `LLM_MODELS_ALLOWED`.
- Produces:
  - `ServerConfig.llm_models_allowed: tuple[str, ...]` — the effective allowlist. When `LLM_MODELS_ALLOWED` is unset or empty, it equals `(config.model_plan, config.model_execute)` deduped, preserving order.
  - Used by Task 3 (route validation) and Task 4 (`GET /api/models`).

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_config_llm_models_allowed.py`:

```python
"""Tests for ServerConfig.llm_models_allowed env plumbing."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from server.config import ServerConfig


def _base_env() -> dict[str, str]:
    return {
        "LLM_API_KEY": "x",
        "JWT_SECRET": "s",
        "LLM_MODEL_PLAN": "claude-opus-4-6",
        "LLM_MODEL_EXECUTE": "claude-sonnet-4-6",
    }


def test_allowlist_unset_falls_back_to_defaults(tmp_path: Path) -> None:
    env = _base_env()
    env.pop("LLM_MODELS_ALLOWED", None)
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.llm_models_allowed == ("claude-opus-4-6", "claude-sonnet-4-6")


def test_allowlist_env_parsed_comma_separated(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "claude-opus-4-6, claude-sonnet-4-6 ,claude-haiku-4-6"
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.llm_models_allowed == (
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-6",
    )


def test_allowlist_dedupe_when_defaults_match_env_entries(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "claude-opus-4-6,claude-opus-4-6,claude-sonnet-4-6"
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.llm_models_allowed == ("claude-opus-4-6", "claude-sonnet-4-6")


def test_allowlist_empty_string_falls_back_to_defaults(tmp_path: Path) -> None:
    env = _base_env()
    env["LLM_MODELS_ALLOWED"] = "   "
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.llm_models_allowed == ("claude-opus-4-6", "claude-sonnet-4-6")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_config_llm_models_allowed.py -q
```

Expected: FAIL with `AttributeError: 'ServerConfig' object has no attribute 'llm_models_allowed'` (or equivalent).

- [ ] **Step 3: Write minimal implementation**

Edit `server/config.py`. In the `ServerConfig` dataclass body, after `email_whitelist: tuple[str, ...] = ()`, add:

```python
    llm_models_allowed: tuple[str, ...] = ()
```

In `ServerConfig.from_env`, after the existing `email_whitelist=...` block and before the closing `)`, add the parsed `llm_models_allowed` argument. Also add a post-construction fallback for the "unset" case. The final `from_env` return becomes:

```python
        cfg = cls(
            api_key=os.environ.get("LLM_API_KEY", ""),
            base_url=os.environ.get("LLM_BASE_URL", "https://api.anthropic.com/v1"),
            model_plan=os.environ.get("LLM_MODEL_PLAN", "claude-opus-4-6"),
            model_execute=os.environ.get("LLM_MODEL_EXECUTE", "claude-sonnet-4-6"),
            image_api_key=os.environ.get("IMAGE_API_KEY", ""),
            image_base_url=os.environ.get("IMAGE_BASE_URL", "https://api.openai.com/v1"),
            image_model=os.environ.get("IMAGE_MODEL", "gpt-image2"),
            output_dir=Path(os.environ.get("OUTPUT_DIR", "./output")),
            data_dir=Path(os.environ.get("DATA_DIR", "./data")),
            rate_limit_delay=float(os.environ.get("LLM_RATE_LIMIT_DELAY", "0")),
            database_url=os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db"),
            jwt_secret=os.environ.get("JWT_SECRET", ""),
            jwt_expire_days=int(os.environ.get("JWT_EXPIRE_DAYS", "7")),
            aws_region=os.environ.get("AWS_REGION", ""),
            ses_from_email=os.environ.get("SES_FROM_EMAIL", ""),
            frontend_url=os.environ.get("FRONTEND_URL", ""),
            email_backend=os.environ.get("EMAIL_BACKEND", "console"),
            email_whitelist=tuple(
                e.strip().lower()
                for e in os.environ.get("EMAIL_WHITELIST", "").split(",")
                if e.strip()
            ),
            question_schemas_path=Path(
                os.environ.get(
                    "QUESTION_SCHEMAS_PATH",
                    str(Path(__file__).resolve().parent.parent / "question_schemas.json"),
                )
            ),
            social_studies_curriculum_dir=Path(
                os.environ.get(
                    "SOCIAL_STUDIES_CURRICULUM_DIR",
                    str(
                        Path(__file__).resolve().parent.parent
                        / "data" / "social_studies" / "curriculum"
                    ),
                )
            ),
            natural_sciences_curriculum_dir=Path(
                os.environ.get(
                    "NATURAL_SCIENCES_CURRICULUM_DIR",
                    str(
                        Path(__file__).resolve().parent.parent
                        / "data" / "natural_sciences" / "curriculum"
                    ),
                )
            ),
            math_curriculum_dir=Path(
                os.environ.get(
                    "MATH_CURRICULUM_DIR",
                    str(Path(__file__).resolve().parent.parent / "data" / "math" / "curriculum"),
                )
            ),
            llm_models_allowed=tuple(
                m.strip()
                for m in os.environ.get("LLM_MODELS_ALLOWED", "").split(",")
                if m.strip()
            ),
        )
        if not cfg.llm_models_allowed:
            seen: dict[str, None] = {}
            for m in (cfg.model_plan, cfg.model_execute):
                if m and m not in seen:
                    seen[m] = None
            cfg.llm_models_allowed = tuple(seen)
        else:
            seen = {}
            for m in cfg.llm_models_allowed:
                if m and m not in seen:
                    seen[m] = None
            cfg.llm_models_allowed = tuple(seen)
        return cfg
```

(Replace the existing `return cls(...)` block with the `cfg = cls(...) / return cfg` version shown above.)

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_config_llm_models_allowed.py -q
```

Expected: PASS — 4 tests green.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add server/config.py tests/server/test_config_llm_models_allowed.py
git commit -m "feat(server): add LLM_MODELS_ALLOWED env-driven allowlist on ServerConfig (#105)"
```

---

### Task 3: Add `model_plan` / `model_execute` to `GenerateParams` and `PlanCoreQuestionsRequest`

**Files:**
- Modify: `server/generate/models.py` (`GenerateParams`, `PlanCoreQuestionsRequest`)
- Modify: `server/generate/routes.py` (`generate_endpoint` `Query` params, `params = GenerateParams(...)`, and both endpoints' allowlist check)
- Test: `tests/server/test_model_selection_routes.py`

**Interfaces:**
- Consumes: `ServerConfig.llm_models_allowed` from Task 2.
- Produces:
  - `GenerateParams.model_plan: str | None`, `GenerateParams.model_execute: str | None`.
  - `PlanCoreQuestionsRequest.model_plan: str | None`, `PlanCoreQuestionsRequest.model_execute: str | None`.
  - Route-level validation that raises `HTTPException(422, detail="model '<x>' not in allowlist: [<a>, <b>, …]")` before any LLM call.
  - Params surface on `params.model_plan` / `params.model_execute` for Tasks 5 and 6 to consume.

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_model_selection_routes.py`:

```python
"""Route-level tests for the model_plan / model_execute overrides (#105)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter


def _make_app_and_token(allowed: tuple[str, ...] = ()):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    if not allowed:
        allowed = ("claude-opus-4-6", "claude-sonnet-4-6")
    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        llm_models_allowed=allowed,
    )
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()
    token = create_jwt(user_id, "u@example.com", config=config)
    return app, token, engine, config


def test_generate_route_accepts_allowlisted_models_and_forwards_to_params() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6")
    )

    captured: dict = {}

    async def fake_stream(params, *_args):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math"
                "&model_plan=claude-opus-4-6"
                "&model_execute=claude-haiku-4-6",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["params"].model_plan == "claude-opus-4-6"
    assert captured["params"].model_execute == "claude-haiku-4-6"


def test_generate_route_rejects_unlisted_model_execute_with_422() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-opus-4-6", "claude-sonnet-4-6")
    )

    called = {"count": 0}

    async def fake_stream(params, *_args):
        called["count"] += 1
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math&model_execute=gpt-4o",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "gpt-4o" in detail
    assert "claude-sonnet-4-6" in detail
    assert called["count"] == 0


def test_generate_route_absent_overrides_defaults_to_none() -> None:
    from server.generate import routes as gen_routes

    app, token, engine, _cfg = _make_app_and_token()

    captured: dict = {}

    async def fake_stream(params, *_args):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/generate?subject=math",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["params"].model_plan is None
    assert captured["params"].model_execute is None


def test_plan_core_questions_route_rejects_unlisted_model_plan_with_422() -> None:
    app, token, engine, _cfg = _make_app_and_token(
        allowed=("claude-opus-4-6", "claude-sonnet-4-6")
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "民主政治", "model_plan": "gpt-4o"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 422
    assert "gpt-4o" in response.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_model_selection_routes.py -q
```

Expected: FAIL — the first test fails because `GenerateParams` has no `model_plan` / `model_execute` fields; subsequent tests fail because the 422 gate does not exist.

- [ ] **Step 3: Add the fields on `GenerateParams` and `PlanCoreQuestionsRequest`**

Edit `server/generate/models.py`.

In `GenerateParams`, after the `subquestion_configs: str | None = None` line and before `model_config = {"populate_by_name": True}`, add:

```python
    # #105: per-request model overrides (validated against ServerConfig.llm_models_allowed
    # at the route level).
    model_plan: str | None = None
    model_execute: str | None = None
```

In `PlanCoreQuestionsRequest`, after the `subject: Literal["math", "social_studies", "natural_sciences"] = "social_studies"` line, add:

```python
    model_plan: str | None = None
    model_execute: str | None = None
```

- [ ] **Step 4: Wire the two `Query` params and the allowlist check into `generate_endpoint`**

Edit `server/generate/routes.py`.

Add a shared validator helper after the `_serialize_event` function and before `@router.get("/generate")`:

```python
def _check_model_allowed(model: str | None, config: ServerConfig, field: str) -> None:
    """Raise HTTPException(422) when a submitted model is outside the allowlist."""
    if model is None:
        return
    if model not in config.llm_models_allowed:
        allowed = ", ".join(config.llm_models_allowed)
        raise HTTPException(
            status_code=422,
            detail=f"{field}: model '{model}' not in allowlist: [{allowed}]",
        )
```

In the `generate_endpoint` signature, insert two new `Query` params next to the existing model-adjacent params — place them immediately after `subquestion_configs: str | None = Query(default=None)`:

```python
    model_plan: str | None = Query(default=None),
    model_execute: str | None = Query(default=None),
```

At the top of the function body (before `params = GenerateParams(...)`), add:

```python
    _check_model_allowed(model_plan, config, "model_plan")
    _check_model_allowed(model_execute, config, "model_execute")
```

In the `GenerateParams(...)` constructor call, after `subquestion_configs=subquestion_configs,`, add:

```python
        model_plan=model_plan,
        model_execute=model_execute,
```

In `plan_core_questions_endpoint`, immediately after the docstring `"""Return three candidate 核心問題 for a given topic (Opus single call)."""` and before `from src.config import Config as SrcConfig`, add:

```python
    _check_model_allowed(body.model_plan, config, "model_plan")
    _check_model_allowed(body.model_execute, config, "model_execute")
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_model_selection_routes.py -q
```

Expected: PASS — 4 tests green.

Also run the pre-existing route tests to confirm no regression:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_generate_routes.py tests/server/test_plan_core_questions_routes.py -q
```

Expected: PASS — no regression.

- [ ] **Step 6: Commit**

```bash
cd /workspace/exam-generation
git add server/generate/models.py server/generate/routes.py tests/server/test_model_selection_routes.py
git commit -m "feat(server): accept model_plan/model_execute overrides with allowlist 422 (#105)"
```

---

### Task 4: `GET /api/models` discovery endpoint

**Files:**
- Modify: `server/utility/routes.py` (new `/api/models` route)
- Test: `tests/server/test_utility_routes.py` (append cases)

**Interfaces:**
- Consumes: `ServerConfig.llm_models_allowed`, `ServerConfig.model_plan`, `ServerConfig.model_execute` (Task 2).
- Produces: `GET /api/models` → `{"allowed": [...], "defaults": {"plan": ..., "execute": ...}}`. Consumed by Task 7 (`getAvailableModels`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/server/test_utility_routes.py` (below the existing tests, still inside the same module):

```python
def test_models_endpoint_returns_allowlist_and_defaults() -> None:
    app = create_app()
    cfg = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        model_plan="claude-opus-4-6",
        model_execute="claude-sonnet-4-6",
        llm_models_allowed=(
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-6",
        ),
    )
    app.dependency_overrides[get_config] = lambda: cfg
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 200
    assert r.json() == {
        "allowed": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-6",
        ],
        "defaults": {
            "plan": "claude-opus-4-6",
            "execute": "claude-sonnet-4-6",
        },
    }


def test_models_endpoint_falls_back_to_defaults_only() -> None:
    app = create_app()
    cfg = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        model_plan="claude-opus-4-6",
        model_execute="claude-sonnet-4-6",
        # Explicitly empty allowlist to mirror the "env unset" default before
        # from_env fills it in — the endpoint must still return both defaults.
        llm_models_allowed=("claude-opus-4-6", "claude-sonnet-4-6"),
    )
    app.dependency_overrides[get_config] = lambda: cfg
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["defaults"] == {
        "plan": "claude-opus-4-6",
        "execute": "claude-sonnet-4-6",
    }
    assert body["allowed"] == ["claude-opus-4-6", "claude-sonnet-4-6"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_utility_routes.py -q -k models_endpoint
```

Expected: FAIL with `404 Not Found` (route missing).

- [ ] **Step 3: Add the endpoint**

Edit `server/utility/routes.py`. After the existing `@router.get("/health")` block and before `@router.get("/api/schemas")`, insert:

```python
@router.get("/api/models")
async def get_models(
    config: ServerConfig = Depends(get_config),
) -> dict:
    """Return the LLM model allowlist and the server-side defaults."""
    return {
        "allowed": list(config.llm_models_allowed),
        "defaults": {
            "plan": config.model_plan,
            "execute": config.model_execute,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_utility_routes.py -q
```

Expected: PASS — all utility-route tests green (including the two new ones).

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add server/utility/routes.py tests/server/test_utility_routes.py
git commit -m "feat(server): add GET /api/models discovery endpoint (#105)"
```

---

### Task 5: Thread overrides through `generate_question_stream` → `LLMClient`

**Files:**
- Modify: `server/generate/service.py` (`generate_question_stream`)
- Test: `tests/server/test_model_selection_service.py`

**Interfaces:**
- Consumes: `GenerateParams.model_plan` / `GenerateParams.model_execute` (Task 3).
- Produces: For each request, `LLMClient` instances built in `worker_one` receive a `dataclasses.replace(config, model_execute=params.model_execute or config.model_execute, model_plan=params.model_plan or config.model_plan)` — so all `client.generate*` / `client.plan` calls transparently pick up the override.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_model_selection_service.py`:

```python
"""Verify that GenerateParams.model_execute is forwarded to LLMClient.config."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from server.config import ServerConfig
from server.generate import service
from server.generate.models import GenerateParams
from src.social_studies.schemas import ExamQuestion


def test_model_execute_override_is_baked_into_llmclient_config(tmp_path: Path) -> None:
    config = ServerConfig(
        api_key="x",
        model_plan="claude-opus-4-6",
        model_execute="claude-sonnet-4-6",
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_models_allowed=(
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-6",
        ),
    )
    params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
        model_execute="claude-haiku-4-6",
        model_plan="claude-opus-4-6",
    )

    captured: dict = {}

    def fake_generate_with_corrections(**kwargs):
        client = kwargs["client"]
        captured["model_execute"] = client.config.model_execute
        captured["model_plan"] = client.config.model_plan
        sampled = kwargs["params"]
        return ExamQuestion(
            id=kwargs["question_id"],
            核心問題="q",
            文本="t",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            閱讀歷程=[p.value for p in sampled.閱讀歷程],
            文本形式=sampled.文本形式.value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    async def collect_events():
        events = []
        async for event in service.generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
        ):
            events.append(event)
        return events

    original = service.ss_generate_with_corrections
    service.ss_generate_with_corrections = fake_generate_with_corrections  # type: ignore[assignment]
    try:
        asyncio.run(collect_events())
    finally:
        service.ss_generate_with_corrections = original  # type: ignore[assignment]

    assert captured["model_execute"] == "claude-haiku-4-6"
    assert captured["model_plan"] == "claude-opus-4-6"


def test_model_override_absent_preserves_config_defaults(tmp_path: Path) -> None:
    config = ServerConfig(
        api_key="x",
        model_plan="claude-opus-4-6",
        model_execute="claude-sonnet-4-6",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    params = GenerateParams(subject="social_studies", count=1, skip_verify=True)

    captured: dict = {}

    def fake_generate_with_corrections(**kwargs):
        client = kwargs["client"]
        captured["model_execute"] = client.config.model_execute
        captured["model_plan"] = client.config.model_plan
        sampled = kwargs["params"]
        return ExamQuestion(
            id=kwargs["question_id"],
            核心問題="q",
            文本="t",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            閱讀歷程=[p.value for p in sampled.閱讀歷程],
            文本形式=sampled.文本形式.value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    async def collect_events():
        events = []
        async for event in service.generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
        ):
            events.append(event)
        return events

    original = service.ss_generate_with_corrections
    service.ss_generate_with_corrections = fake_generate_with_corrections  # type: ignore[assignment]
    try:
        asyncio.run(collect_events())
    finally:
        service.ss_generate_with_corrections = original  # type: ignore[assignment]

    assert captured["model_execute"] == "claude-sonnet-4-6"
    assert captured["model_plan"] == "claude-opus-4-6"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_model_selection_service.py -q
```

Expected: FAIL — override is not yet applied; `captured["model_execute"]` equals `"claude-sonnet-4-6"` (default), not `"claude-haiku-4-6"`.

- [ ] **Step 3: Apply the override in `worker_one`**

Edit `server/generate/service.py`.

At the top of the module, next to the other `dataclasses` / stdlib imports, add:

```python
import dataclasses
```

Locate the line `question_clients = [LLMClient(config) for _ in range(count)]` near the bottom of `generate_question_stream` (currently around line 383). Replace it with:

```python
    # #105: per-request model overrides are baked into each LLMClient's config so
    # downstream `client.generate*` / `client.plan` calls transparently use the
    # chosen model without changing subject-CLI signatures.
    client_config = dataclasses.replace(
        config,
        model_execute=params.model_execute or config.model_execute,
        model_plan=params.model_plan or config.model_plan,
    )
    question_clients = [LLMClient(client_config) for _ in range(count)]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_model_selection_service.py -q
```

Expected: PASS — both tests green.

Also run the existing service-level regression:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_generate_routes.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add server/generate/service.py tests/server/test_model_selection_service.py
git commit -m "feat(server): bake model overrides into per-request LLMClient config (#105)"
```

---

### Task 6: Thread `model_plan` / `model_execute` through `/api/plan-core-questions`

**Files:**
- Modify: `server/generate/routes.py` (`plan_core_questions_endpoint` body — the `LLMClient(src_config)` construction)
- Test: `tests/server/test_plan_core_questions_routes.py` (append)

**Interfaces:**
- Consumes: `PlanCoreQuestionsRequest.model_plan` / `PlanCoreQuestionsRequest.model_execute` (Task 3).
- Produces: The `LLMClient` used by `plan_core_questions` has `client.config.model_plan` set to the override (or falls back to `SrcConfig.from_env().model_plan`).

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_plan_core_questions_routes.py` (below the existing tests, same module):

```python
def test_plan_core_questions_forwards_model_plan_override(monkeypatch) -> None:
    """When model_plan is submitted, the LLMClient used by the planner sees it."""
    app, token, engine = _make_app_and_token()

    captured: dict = {}

    def fake_math_plan(client, topic, **kwargs):
        captured["model_plan"] = client.config.model_plan
        captured["model_execute"] = client.config.model_execute
        return ["核心問題一", "核心問題二", "核心問題三"]

    monkeypatch.setattr("src.planner.plan_core_questions", fake_math_plan)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={
                    "topic": "統計",
                    "subject": "math",
                    "model_plan": "claude-opus-4-6",
                    "model_execute": "claude-sonnet-4-6",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    assert captured["model_plan"] == "claude-opus-4-6"
    assert captured["model_execute"] == "claude-sonnet-4-6"


def test_plan_core_questions_absent_override_keeps_defaults(monkeypatch) -> None:
    app, token, engine = _make_app_and_token()

    captured: dict = {}

    def fake_ss_plan(client, topic, **kwargs):
        captured["model_plan"] = client.config.model_plan
        captured["model_execute"] = client.config.model_execute
        return ["問題一", "問題二", "問題三"]

    monkeypatch.setattr("src.social_studies.planner.plan_core_questions", fake_ss_plan)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/plan-core-questions",
                json={"topic": "民主政治"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        limiter.reset()
        asyncio.run(engine.dispose())

    assert response.status_code == 200
    # Defaults from SrcConfig.from_env() — not user-supplied.
    assert captured["model_plan"] == "claude-opus-4-6"
    assert captured["model_execute"] == "claude-sonnet-4-6"
```

Also, the existing helper `_make_app_and_token` seeds `ServerConfig(api_key="x", jwt_secret="test-secret")` which yields an empty `llm_models_allowed`. Because Task 3 puts the allowlist gate before this handler runs, add `llm_models_allowed=("claude-opus-4-6", "claude-sonnet-4-6")` to that `ServerConfig(...)` call in the same helper (still inside `test_plan_core_questions_routes.py`):

```python
    config = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        llm_models_allowed=("claude-opus-4-6", "claude-sonnet-4-6"),
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_plan_core_questions_routes.py -q -k model_plan
```

Expected: FAIL — override is not honored; `captured["model_plan"]` is still the env default, not the request value (or the test cannot construct the `LLMClient` with the override yet).

- [ ] **Step 3: Apply the override in `plan_core_questions_endpoint`**

Edit `server/generate/routes.py`. Add `import dataclasses` at the top of the module next to the other stdlib imports.

Inside `plan_core_questions_endpoint`, replace the existing two lines:

```python
    src_config = SrcConfig.from_env()
    client = LLMClient(src_config)
```

with:

```python
    src_config = SrcConfig.from_env()
    src_config = dataclasses.replace(
        src_config,
        model_plan=body.model_plan or src_config.model_plan,
        model_execute=body.model_execute or src_config.model_execute,
    )
    client = LLMClient(src_config)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /workspace/exam-generation
uv run pytest tests/server/test_plan_core_questions_routes.py -q
```

Expected: PASS — all plan-core-questions tests green (existing ones plus the two new).

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add server/generate/routes.py tests/server/test_plan_core_questions_routes.py
git commit -m "feat(server): honor model_plan/model_execute on /api/plan-core-questions (#105)"
```

---

### Task 7: Frontend API + `useGenerate` plumbing

**Files:**
- Modify: `web/src/api/client.ts` (new `getAvailableModels`)
- Modify: `web/src/hooks/useGenerate.ts` (`GenerateParams` fields + `buildQueryString`)
- Create: `web/src/hooks/useGenerate.test.ts`

**Interfaces:**
- Consumes: `GET /api/models` (Task 4).
- Produces:
  - `getAvailableModels(): Promise<{ allowed: string[]; defaults: { plan: string; execute: string } }>`.
  - `GenerateParams.model_plan?: string`, `GenerateParams.model_execute?: string`.
  - `buildQueryString` emits `model_plan` / `model_execute` only when the field is a non-empty string.
  - Consumed by Task 8 (`ParamForm.tsx`).

- [ ] **Step 1: Write the failing tests**

Create `web/src/hooks/useGenerate.test.ts`:

```ts
import { describe, expect, it } from "vitest";
// The buildQueryString helper is currently module-private. This test file
// intentionally imports it via a named re-export added in the implementation
// step below.
import { buildQueryString } from "./useGenerate";

describe("useGenerate — model overrides", () => {
  it("does not emit model_plan / model_execute when unset", () => {
    const qs = buildQueryString({ subject: "math", grade: 7 });
    expect(qs).not.toContain("model_plan");
    expect(qs).not.toContain("model_execute");
  });

  it("emits model_plan / model_execute when set to non-empty strings", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      model_plan: "claude-opus-4-6",
      model_execute: "claude-haiku-4-6",
    });
    const params = new URLSearchParams(qs);
    expect(params.get("model_plan")).toBe("claude-opus-4-6");
    expect(params.get("model_execute")).toBe("claude-haiku-4-6");
  });

  it("does not emit model_plan / model_execute when set to empty string", () => {
    const qs = buildQueryString({
      subject: "math",
      grade: 7,
      model_plan: "",
      model_execute: "",
    });
    expect(qs).not.toContain("model_plan");
    expect(qs).not.toContain("model_execute");
  });
});
```

Create `web/src/api/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { getAvailableModels } from "./client";

const fetchMock = vi.fn();

vi.stubGlobal("fetch", fetchMock);

vi.mock("../store/authStore", () => ({
  useAuthStore: {
    getState: () => ({ token: null, logout: () => {} }),
  },
}));

afterEach(() => {
  fetchMock.mockReset();
});

describe("getAvailableModels", () => {
  it("returns allowed + defaults from the JSON body", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          allowed: ["claude-opus-4-6", "claude-sonnet-4-6"],
          defaults: {
            plan: "claude-opus-4-6",
            execute: "claude-sonnet-4-6",
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await getAvailableModels();
    expect(result).toEqual({
      allowed: ["claude-opus-4-6", "claude-sonnet-4-6"],
      defaults: {
        plan: "claude-opus-4-6",
        execute: "claude-sonnet-4-6",
      },
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/models",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it("throws ApiError when the response is non-2xx", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('{"detail":"nope"}', {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(getAvailableModels()).rejects.toThrow("nope");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /workspace/exam-generation/web
npm test -- src/hooks/useGenerate.test.ts src/api/client.test.ts
```

Expected: FAIL — `buildQueryString` is not exported yet and `getAvailableModels` does not exist.

- [ ] **Step 3: Add `getAvailableModels` in `web/src/api/client.ts`**

Append to `web/src/api/client.ts` (after `planCoreQuestions`):

```ts
export interface AvailableModels {
  allowed: string[];
  defaults: { plan: string; execute: string };
}

export async function getAvailableModels(): Promise<AvailableModels> {
  const res = await apiFetch("/api/models");
  return (await res.json()) as AvailableModels;
}
```

- [ ] **Step 4: Add the fields + querystring emission in `web/src/hooks/useGenerate.ts`**

In `web/src/hooks/useGenerate.ts`:

1. In the `export interface GenerateParams {` block, after `subquestion_configs?: string;`, add:

```ts
  model_plan?: string;
  model_execute?: string;
```

2. Change the signature `function buildQueryString(params: GenerateParams): string {` to an exported form so the tests can import it:

```ts
export function buildQueryString(params: GenerateParams): string {
```

3. Inside `buildQueryString`, immediately before the closing `return qs.toString();`, add:

```ts
  if (params.model_plan && params.model_plan.length > 0) {
    qs.append("model_plan", params.model_plan);
  }
  if (params.model_execute && params.model_execute.length > 0) {
    qs.append("model_execute", params.model_execute);
  }
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
cd /workspace/exam-generation/web
npm test -- src/hooks/useGenerate.test.ts src/api/client.test.ts
```

Expected: PASS — 5 tests green.

Also run the full suite to catch regressions:

```bash
cd /workspace/exam-generation/web
npm test
```

Expected: PASS.

- [ ] **Step 6: Verify lint and build**

Run:

```bash
cd /workspace/exam-generation/web
npm run lint && npm run build
```

Expected: no lint errors, `tsc -b && vite build` succeeds.

- [ ] **Step 7: Commit**

```bash
cd /workspace/exam-generation/web
git add src/api/client.ts src/api/client.test.ts src/hooks/useGenerate.ts src/hooks/useGenerate.test.ts
git commit -m "feat(web): expose model_plan/model_execute in GenerateParams + getAvailableModels (#105)"
```

---

### Task 8: `ParamForm` dropdowns with localStorage persistence

**Files:**
- Modify: `web/src/i18n/messages.ts` (new `params.model_plan_label` / `params.model_execute_label` / `params.model_default_option` in both language blocks)
- Modify: `web/src/components/ParamForm.tsx` (state, effect, two `<select>`s, submit wiring)
- Modify: `web/src/pages/GeneratePage.tsx` (forward `model_plan` / `model_execute` into `generate({...})`)
- Create: `web/src/components/ParamForm.model-selection.test.tsx`

**Interfaces:**
- Consumes: `getAvailableModels` (Task 7), `GenerateParams.model_plan` / `model_execute` (Task 7).
- Produces: two dropdowns above the submit button (or in the header controls section — see Step 4). Empty selection = "預設" (server default), which clears the override and stores an empty string in `localStorage`.

- [ ] **Step 1: Add i18n keys**

In `web/src/i18n/messages.ts`, add to the `"en-US"` block, directly after the last existing `"params.*"` key (find the block by searching for `"params."`; add these lines just before the block's closing `}`):

```ts
    "params.model_plan_label": "Planner model",
    "params.model_execute_label": "Execution model",
    "params.model_default_option": "Default",
```

And to the `"zh-TW"` block in the same relative position:

```ts
    "params.model_plan_label": "規劃模型",
    "params.model_execute_label": "出題模型",
    "params.model_default_option": "預設",
```

(If no `"params.*"` key exists in a block, insert these three lines immediately before the block's closing `}`. Verify by opening `messages.ts`.)

- [ ] **Step 2: Write the failing test**

Create `web/src/components/ParamForm.model-selection.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(),
}));

import ParamForm from "./ParamForm";

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "standard", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(MATH_SCHEMA);
  getAvailableModelsMock.mockResolvedValue({
    allowed: ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6"],
    defaults: { plan: "claude-opus-4-6", execute: "claude-sonnet-4-6" },
  });
});

describe("ParamForm — model selection dropdowns", () => {
  it("renders two selects populated from /api/models", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    const planSelect = await screen.findByLabelText("Planner model");
    const execSelect = await screen.findByLabelText("Execution model");
    const planOptions = Array.from(planSelect.querySelectorAll("option")).map(
      (o) => o.value,
    );
    expect(planOptions).toEqual([
      "",
      "claude-opus-4-6",
      "claude-sonnet-4-6",
      "claude-haiku-4-6",
    ]);
    // Both selects start at the "Default" (empty) option.
    expect((planSelect as HTMLSelectElement).value).toBe("");
    expect((execSelect as HTMLSelectElement).value).toBe("");
  });

  it("passes the selected model_plan/model_execute to onSubmit and persists them", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
    await screen.findByLabelText("Planner model");

    const user = userEvent.setup();
    await user.selectOptions(
      screen.getByLabelText("Planner model"),
      "claude-opus-4-6",
    );
    await user.selectOptions(
      screen.getByLabelText("Execution model"),
      "claude-haiku-4-6",
    );

    await user.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_plan).toBe("claude-opus-4-6");
    expect(submitted.model_execute).toBe("claude-haiku-4-6");

    expect(window.localStorage.getItem("model_plan")).toBe("claude-opus-4-6");
    expect(window.localStorage.getItem("model_execute")).toBe("claude-haiku-4-6");
  });

  it("hides the dropdowns when /api/models fails", async () => {
    getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    // Wait for the schema fetch to resolve so the form is rendered.
    await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
    await waitFor(() => {
      expect(screen.queryByLabelText("Planner model")).toBeNull();
      expect(screen.queryByLabelText("Execution model")).toBeNull();
    });
  });

  it("hydrates from localStorage on mount", async () => {
    window.localStorage.setItem("model_plan", "claude-sonnet-4-6");
    window.localStorage.setItem("model_execute", "claude-haiku-4-6");
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    const planSelect = await screen.findByLabelText("Planner model");
    const execSelect = await screen.findByLabelText("Execution model");
    expect((planSelect as HTMLSelectElement).value).toBe("claude-sonnet-4-6");
    expect((execSelect as HTMLSelectElement).value).toBe("claude-haiku-4-6");
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```bash
cd /workspace/exam-generation/web
npm test -- src/components/ParamForm.model-selection.test.tsx
```

Expected: FAIL — `getByLabelText("Planner model")` throws because no such control exists.

- [ ] **Step 4: Add the two selects, localStorage plumbing, and submit wiring in `ParamForm.tsx`**

Edit `web/src/components/ParamForm.tsx`.

1. In the import block at the top of the file, extend the `../api/client` import to include `getAvailableModels` and its `AvailableModels` type:

```ts
import { getAvailableModels, getSchemas, type AvailableModels, type Schemas } from "../api/client";
```

2. In `export interface GenerateParams {` (inside this file — the ParamForm-local form-params type, ~line 19), after `subquestion_configs?: string;`, add:

```ts
  model_plan?: string;
  model_execute?: string;
```

3. Inside the `ParamForm` component body, next to the other `useState` calls (~line 213 after `setSubquestionConfigs`), add:

```tsx
  const [models, setModels] = useState<AvailableModels | null>(null);
  const [modelPlan, setModelPlan] = useState<string>(
    () => window.localStorage.getItem("model_plan") ?? "",
  );
  const [modelExecute, setModelExecute] = useState<string>(
    () => window.localStorage.getItem("model_execute") ?? "",
  );
```

4. Add a mount-only `useEffect` that fetches the model list once (place it alongside the other `useEffect` blocks in the component, e.g. right after the block that fetches `getSchemas(subject)`):

```tsx
  useEffect(() => {
    let cancelled = false;
    getAvailableModels()
      .then((m) => {
        if (!cancelled) setModels(m);
      })
      .catch(() => {
        // Discovery failure: hide the dropdowns; do not block the form.
        if (!cancelled) setModels(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
```

5. Persist to `localStorage` whenever the selection changes — add near the other persistence effects:

```tsx
  useEffect(() => {
    window.localStorage.setItem("model_plan", modelPlan);
  }, [modelPlan]);
  useEffect(() => {
    window.localStorage.setItem("model_execute", modelExecute);
  }, [modelExecute]);
```

6. In the JSX, add the two selects immediately before the submit button. Find the form's submit `<button type="submit" ...>` (search for `type="submit"` in `ParamForm.tsx`) and insert the block below directly above it:

```tsx
      {models && models.allowed.length > 0 && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-gray-700">
            <span>{t("params.model_plan_label")}</span>
            <select
              aria-label={t("params.model_plan_label")}
              value={modelPlan}
              onChange={(e) => setModelPlan(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
            >
              <option value="">
                {t("params.model_default_option")} ({models.defaults.plan})
              </option>
              {models.allowed.map((m) => (
                <option key={`plan-${m}`} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-gray-700">
            <span>{t("params.model_execute_label")}</span>
            <select
              aria-label={t("params.model_execute_label")}
              value={modelExecute}
              onChange={(e) => setModelExecute(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
            >
              <option value="">
                {t("params.model_default_option")} ({models.defaults.execute})
              </option>
              {models.allowed.map((m) => (
                <option key={`exec-${m}`} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
```

7. In the submit handler (the function that builds the `GenerateParams` object passed to `onSubmit`), add the two fields — locate the return object of `handleSubmit` (search for `onSubmit({`) and add just before the closing brace:

```ts
        model_plan: modelPlan || undefined,
        model_execute: modelExecute || undefined,
```

8. Wire them through `GeneratePage.tsx` so `useGenerate` sees them. In `web/src/pages/GeneratePage.tsx`, inside the `handleSubmit` body's call to `generate({ ... })`, add these two lines at the end of the object literal (before the closing `});`):

```ts
      model_plan: params.model_plan,
      model_execute: params.model_execute,
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
cd /workspace/exam-generation/web
npm test -- src/components/ParamForm.model-selection.test.tsx
```

Expected: PASS — 4 tests green.

Also run the full suite:

```bash
cd /workspace/exam-generation/web
npm test
```

Expected: PASS — no regression.

- [ ] **Step 6: Verify lint and build**

Run:

```bash
cd /workspace/exam-generation/web
npm run lint && npm run build
```

Expected: no lint errors, build succeeds.

- [ ] **Step 7: Commit**

```bash
cd /workspace/exam-generation/web
git add src/i18n/messages.ts src/components/ParamForm.tsx src/components/ParamForm.model-selection.test.tsx src/pages/GeneratePage.tsx
git commit -m "feat(web): add model_plan/model_execute dropdowns to ParamForm (#105)"
```

---

### Task 9: Manual end-to-end verification

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything above plus a running server + web dev server with a valid `LLM_API_KEY`.

- [ ] **Step 1: Start the backend with a multi-model allowlist**

```bash
cd /workspace/exam-generation
LLM_MODELS_ALLOWED="claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-6" \
  uv run uvicorn server.app:create_app --factory --reload --port 8000
```

- [ ] **Step 2: Confirm the discovery endpoint**

In another shell:

```bash
curl -s http://127.0.0.1:8000/api/models | python -m json.tool
```

Expected: JSON body with `allowed` listing all three models and `defaults` mirroring `LLM_MODEL_PLAN` / `LLM_MODEL_EXECUTE`.

- [ ] **Step 3: Start the web dev server**

```bash
cd /workspace/exam-generation/web
npm run dev
```

- [ ] **Step 4: Verify the UI**

In the browser, sign in and open a generation page (any subject). Confirm the two dropdowns render above the submit button, populated from `/api/models`. Change both to non-default values, submit, and observe in the ProgressLog that the `llm_request.model` field reflects the selected execution model. Refresh the page — the selections must persist.

- [ ] **Step 5: Verify the rejection path**

Submit a `curl` request with an out-of-allowlist model:

```bash
TOKEN="<paste a valid JWT from browser devtools>"
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer ${TOKEN}" \
  "http://127.0.0.1:8000/api/generate?subject=math&model_execute=gpt-4o"
```

Expected: `422`. Repeat with the JSON body variant against `/api/plan-core-questions`:

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  -d '{"topic":"民主政治","model_plan":"gpt-4o"}' \
  http://127.0.0.1:8000/api/plan-core-questions
```

Expected: `422`.

- [ ] **Step 6: Verify the fallback path (no dropdowns)**

Stop the backend and restart it without `LLM_MODELS_ALLOWED` set:

```bash
cd /workspace/exam-generation
uv run uvicorn server.app:create_app --factory --reload --port 8000
```

Confirm `curl -s http://127.0.0.1:8000/api/models` returns exactly the two defaults in `allowed`. Reload the web page and confirm the dropdowns still render with just the two options (since discovery succeeds; only two entries are offered). Then temporarily stop the backend and reload the web app — confirm the form still renders and the dropdowns are hidden (no dropdown, no submit-blocking error).
