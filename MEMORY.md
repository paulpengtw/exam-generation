# Project Memory

Durable gotchas and decisions for all agents and developers working on this repo.

---

## Gotchas

1. **Playwright browser binary is not installed by `uv sync`.**
   `playwright` is a Python package dependency, but its Chromium binary is a
   separate download that `uv sync` does not perform.  Running the test suite or
   the server without it causes every renderer construction to fail.
   Use `bash scripts/setup.sh` to install both (added in issue #659).
   See also: `scripts/setup.sh`, `README.md` Option A.

2. **After `git worktree move`, `.venv` shebangs break.**
   When a worktree is relocated with `git worktree move`, the virtual environment
   at `.venv/` retains scripts with shebangs pointing at the old path.
   `uv run pytest` (and similar commands) then fail with:
   `Failed to spawn: pytest / No such file or directory`.
   Fix: `rm -rf .venv && uv sync` (or `bash scripts/setup.sh`).

3. **Worktree venvs created with bare `uv sync` lack fastapi/sqlalchemy; server tests fail at collection.**
   `uv sync` without flags installs only the default dependency group, omitting optional
   extras such as `web` (fastapi, sqlalchemy, uvicorn).  Any test under `tests/server/`
   that imports those packages will fail with `ModuleNotFoundError` at collection time.
   Always use `uv sync --all-extras --all-groups` (what `bash scripts/setup.sh` does),
   or match what CI runs: `uv sync --all-extras --all-groups`.

4. **NS few-shot directories are named by the 題組's headline 題型, not each 小題's 題型.**
   `data/natural_sciences/few_shot/Constructed-response/` contains 39
   Simple/Complex multiple-choice 小題, and the Complex-multiple-choice folder
   contains Constructed-response 小題.  Any corpus audit or rubric check must
   bucket by `subquestions[*].題型`, never by directory
   (found while building the #651 labelled set; the first pass dropped 39 of 257 entries).

5. **Aborting a web generate stream leaks a Playwright renderer on staging; two aborts stop all generation until the backend restarts.**
   `generate_question_stream` acquires one of the two pooled renderers right after emitting `started` and only returns it in its `finally` after awaiting the worker; on a real client disconnect that cleanup is interrupted, so the renderer is never put back. Symptoms: every later `GET /api/generate` shows `event: started` and then only `: ping` frames, `/health` stays fast, nothing else arrives. Recovery today is a backend redeploy/restart. Do not kill long staging streams mid-run during smoke tests unless you can restart the service afterwards. Diagnosed in issue #689 (2026-09-10); fix tracked in #700. Capture tooling: `scripts/capture_sse_689.py`.
