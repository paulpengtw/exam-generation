# Issue #545 — Per-Test Staging Failure Classification

**Date:** 2026-08-24  
**Staging baseline:** a20519f  
**Branch:** fix/545-staging-suite-repair  
**Verifier:** independent code inspection + `uv run python3 -c 'import <dep>'` probes  

## Environment probe results (baseline a20519f)

```
$ uv run python3 -c 'import sqlalchemy'
ModuleNotFoundError: No module named 'sqlalchemy'

$ uv run python3 -c 'import fastapi'
ModuleNotFoundError: No module named 'fastapi'
```

Both `sqlalchemy` and `fastapi` are declared under
`[project.optional-dependencies].web` in `pyproject.toml` and are absent
from the base `uv` environment (no `--extra web`).

## Import failure chains

| Dep | Chain |
|-----|-------|
| sqlalchemy | `server.generate.service` → `server.db` → `sqlalchemy` |
| sqlalchemy | `server.generate.modification_service` → `server.models` → `sqlalchemy` |
| sqlalchemy | `server.generate.models` (GenerateParams) — imports cleanly; indirect via service |
| fastapi | `server.generate.routes` → `fastapi` |

---

## Per-test classification

### Failure 1 — `test_server_generate_stream_accumulates_prior_scopes_across_math_workers`

**File:** `tests/test_batch_dedup.py` (guard at line 486)  
**Classification:** ENVIRONMENT-ONLY  
**Missing dep:** `sqlalchemy`  
**Import chain:** test imports `server.generate.service` → `server.db` → `sqlalchemy` (ModuleNotFoundError)  
**Guard placed:** `pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")`  
**Measured at baseline:** ModuleNotFoundError raised on first server import; no code regression.

---

### Failure 2 — `test_scoped_modification_merge_ignores_interaction_paths`

**File:** `tests/test_interactive_item_generation.py` (guard at line 313)  
**Classification:** ENVIRONMENT-ONLY  
**Missing dep:** `sqlalchemy`  
**Import chain:** test imports `server.generate.modification_service` → `server.models` → `sqlalchemy` (ModuleNotFoundError)  
**Guard placed:** `pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")`  
**Measured at baseline:** `_merge_scoped` is implemented correctly at `modification_service.py:92`; failure is import-only.

---

### Failure 3 — `test_generate_route_declares_callback_query_parameter` (NS)

**File:** `tests/test_natural_sciences_core_question_callback.py` (guard at line 331)  
**Classification:** ENVIRONMENT-ONLY  
**Missing dep:** `fastapi`  
**Import chain:** test imports `server.generate.routes` → `fastapi` (ModuleNotFoundError)  
**Guard placed:** `pytest.importorskip("fastapi", reason="requires [web] extras: uv sync --extra web")`  
**Measured at baseline:** `core_question_callback: bool = Query(default=True)` confirmed at `routes.py:204`; failure is import-only.

---

### Failure 4 — `test_natural_sciences_prompt_preview_reflects_requested_callback_state`

**File:** `tests/test_natural_sciences_core_question_callback.py` (guard at line 338)  
**Classification:** ENVIRONMENT-ONLY  
**Missing dep:** `sqlalchemy`  
**Import chain:** test imports `server.generate.service` (`build_prompt_previews`) → `server.db` → `sqlalchemy` (ModuleNotFoundError)  
**Guard placed:** `pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")`  
**Measured at baseline:** `server.generate.models` (GenerateParams) and `server.config` import cleanly; failure is from service's db dependency only.

---

### Failure 5 — `test_callback_toggle_does_not_change_seeded_natural_sciences_sampling`

**File:** `tests/test_natural_sciences_core_question_callback.py` (guard at line 407)  
**Classification:** ENVIRONMENT-ONLY  
**Missing dep:** `sqlalchemy`  
**Import chain:** test imports `server.generate.service` (`_sample_worker_params`) → `server.db` → `sqlalchemy` (ModuleNotFoundError)  
**Guard placed:** `pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")`  
**Measured at baseline:** `server.generate.subjects` (SUBJECTS) imports cleanly; failure is from service's db dependency only.

---

### Failure 6 — `test_generate_route_declares_callback_query_parameter` (SS)

**File:** `tests/test_social_studies_core_question_callback.py` (guard at line 278)  
**Classification:** ENVIRONMENT-ONLY  
**Missing dep:** `fastapi`  
**Import chain:** test imports `server.generate.routes` → `fastapi` (ModuleNotFoundError)  
**Guard placed:** `pytest.importorskip("fastapi", reason="requires [web] extras: uv sync --extra web")`  
**Measured at baseline:** same `routes.py:204` implementation as NS test; failure is import-only. (Same function name as failure 3 but in a different test module.)

---

### Failure 7 — `test_social_studies_prompt_preview_reflects_requested_callback_state`

**File:** `tests/test_social_studies_core_question_callback.py` (guard at line 285)  
**Classification:** ENVIRONMENT-ONLY  
**Missing dep:** `sqlalchemy`  
**Import chain:** test imports `server.generate.service` (`build_prompt_previews`) → `server.db` → `sqlalchemy` (ModuleNotFoundError)  
**Guard placed:** `pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")`  
**Measured at baseline:** `server.config` and `server.generate.models` import cleanly; failure is from service's db dependency only.

---

### Failure 8 — `test_callback_toggle_does_not_change_seeded_social_studies_sampling`

**File:** `tests/test_social_studies_core_question_callback.py` (guard at line 319)  
**Classification:** ENVIRONMENT-ONLY  
**Missing dep:** `sqlalchemy`  
**Import chain:** test imports `server.generate.service` (`_sample_worker_params`) → `server.db` → `sqlalchemy` (ModuleNotFoundError)  
**Guard placed:** `pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")`  
**Measured at baseline:** `server.generate.subjects` (SUBJECTS with `social_studies` key) imports cleanly; failure is from service's db dependency only.

---

## Summary

All 8 failures are **ENVIRONMENT-ONLY**.  No production code regression exists.
Each test transitively imports either `sqlalchemy` (via `server.db`) or `fastapi`
(via `server.generate.routes`), both of which are absent from the base `uv`
environment.  The fix adds `pytest.importorskip` guards so these tests skip
with an explicit reason rather than fail with an unrelated ImportError.

Guard inventory:
- 2 `fastapi` guards: failures 3, 6
- 6 `sqlalchemy` guards: failures 1, 2, 4, 5, 7, 8
