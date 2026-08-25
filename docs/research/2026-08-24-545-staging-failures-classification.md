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

## Web-extras installation and live run (2026-08-25)

`uv sync --extra web` completed successfully, installing sqlalchemy 2.0.49,
fastapi, starlette 1.0.0, slowapi 0.1.9, and the full web-extras tree.

All 8 originally-failing tests were then run with the extras present:

```
$ uv run pytest -v \
  tests/test_batch_dedup.py::test_server_generate_stream_accumulates_prior_scopes_across_math_workers \
  tests/test_interactive_item_generation.py::test_scoped_modification_merge_ignores_interaction_paths \
  "tests/test_natural_sciences_core_question_callback.py::test_generate_route_declares_callback_query_parameter" \
  "tests/test_natural_sciences_core_question_callback.py::test_natural_sciences_prompt_preview_reflects_requested_callback_state" \
  "tests/test_natural_sciences_core_question_callback.py::test_callback_toggle_does_not_change_seeded_natural_sciences_sampling" \
  "tests/test_social_studies_core_question_callback.py::test_generate_route_declares_callback_query_parameter" \
  "tests/test_social_studies_core_question_callback.py::test_social_studies_prompt_preview_reflects_requested_callback_state" \
  "tests/test_social_studies_core_question_callback.py::test_callback_toggle_does_not_change_seeded_social_studies_sampling"

8 passed, 1 warning in 4.47s
```

Result: **all 8 passed**. The ENVIRONMENT-ONLY classification is confirmed
by direct execution — no logic defects exist in the guarded test bodies.

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

## Collection errors repaired by commit af3ffdd (in scope for #545)

Commit af3ffdd also repaired approximately 47 pytest collection errors beyond
the 8 originally-named test failures.  These were in scope because the ticket's
end state is a fully green suite, but they went undocumented in the initial
classification.

### Root cause

The same missing web-extras (`sqlalchemy`, `fastapi`, `sentry_sdk`, `alembic`)
caused module-level import failures in files that import server modules at the
top of the file (outside any test function).  pytest aborts collection for a
file when its module-level code raises an exception, so each affected file
contributed a collection error rather than a skipped test.

### Files affected

**Top-level test files (5):**

- `tests/test_contract_forwarding_guard.py`
- `tests/test_coverage_mode_prompt_hint_ns.py`
- `tests/test_default_models_hotfix_379.py`
- `tests/test_paper_rescore_retirement.py`
- `tests/test_ts_contract_drift.py`

**tests/server/ (42 files):**

`test_auth.py`, `test_auth_routes.py`, `test_census_chart_specs.py`,
`test_db_engine_config.py`, `test_db_models.py`, `test_effort_routes.py`,
`test_effort_tier_routes.py`, `test_exchange_retention.py`,
`test_exchange_routes.py`, `test_figure_kind_request_params.py`,
`test_generate_routes.py`, `test_generate_service_coverage.py`,
`test_generate_teardown.py`, `test_generation_outcome_metric.py`,
`test_generation_record_annotations.py`, `test_generation_records_migration.py`,
`test_history_retention.py`, `test_history_routes.py`, `test_history_write.py`,
`test_iccs_pin_params.py`, `test_image_api_key_admission.py`,
`test_injectable_collaborators.py`, `test_llm_exchanges_migration.py`,
`test_math_curriculum_context_threading.py`, `test_math_drawn_group_count.py`,
`test_model_selection_routes.py`, `test_model_selection_service.py`,
`test_model_tier_routes.py`, `test_modification_routes.py`,
`test_observability.py`, `test_per_question_params.py`, `test_persistence.py`,
`test_plan_core_questions_routes.py`, `test_prompt_preview.py`,
`test_provider_key_admission.py`, `test_rate_limit.py`,
`test_session_renewal_routes.py`, `test_session_renewal_server_time.py`,
`test_session_renewal_tokens.py`, `test_ss_creative_planning_service.py`,
`test_subquestion_configs_error_event.py`, `test_utility_routes.py`,
`test_verification_trail_persistence.py`, `test_verification_trail_stream.py`

### Fix pattern applied

Module-level `pytest.importorskip("sqlalchemy", ...)` or
`pytest.importorskip("fastapi", ...)` inserted immediately after `import pytest`,
before any server import that would otherwise fail at collection time.  Files
that imported both sqlalchemy-dependent and fastapi-dependent modules received
a single `sqlalchemy` guard (sqlalchemy is the deeper dependency; fastapi alone
does not pull it in but the routes module does).

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
