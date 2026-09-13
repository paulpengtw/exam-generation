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

5. **Aborting a web generate stream held its renderer until the worker exited; fixed in #700 option 2 (per-render lease).**
   Original root cause (#689): on client disconnect, anyio cancellation interrupted `generate_question_stream`'s `finally` before `renderer_pool.put` ran, permanently leaking the renderer.  Option 1 (#700, 2026-09-10) shielded the cleanup with `anyio.CancelScope(shield=True)`, but still held the renderer for the full worker lifetime — a gpt_image run aborted mid-image held it for 150–230 s, stalling the next run's `started`→`pipeline_start` for the same duration.
   Option 2 (2026-09-10, branch `fix/700-lease-renderer-per-render`): replaced the stream-level hold with a **per-render lease** (`server/generate/renderer_lease.py`, `RendererLease`).  Workers borrow a renderer from `app_state.renderer_pool` only for the duration of a single `html_renderer.render()` call, returning it immediately after.  A worker that never renders (e.g. gpt_image runs) never touches the pool.  The pool no longer caps concurrent generations at two.  Client-visible `stage` events (agent "renderer", stage "acquire", status "start"/"end") are emitted only when the pool is empty and the lease must wait.  `RENDERER_POOL_WAIT_WARN_THRESHOLD_S` (in `server/generate/service.py`) controls the WARNING log threshold.  Diagnosed in #689; staging evidence in issue #700; capture tooling: `scripts/capture_sse_689.py`.

6. **`plan_all_batch_briefs` runs off the event loop via `asyncio.to_thread`; fixed in #701.**
   Root cause: `spec.plan_all_batch_briefs(...)` was called synchronously on the event loop in `generate_question_stream`. For 社會領域 with `creative_planning=True`, this blocks the event loop for ~14 s (one synchronous Opus planning call), freezing pings, /health, and every other concurrent request. Fixed in #701 (2026-09-10) by wrapping the call in `await asyncio.to_thread(functools.partial(...))`. Two client-visible `stage` events (agent "planner", stage "batch_briefs", status "start"/"end") bracket the call. A `ctx.cancel_event.is_set()` guard before worker submission prevents workers from starting if the client disconnected during planning. The planner/batch_briefs stage keys are added to both locales in `web/src/i18n/messages.ts`.

7. **Inside SQLAlchemy's async greenlet, traceback/task stacks do not reach the calling coroutine; read greenlet.getcurrent().parent.gr_frame instead (issue #585).**
   On the production asyncpg + AsyncSession checkout path, SQLAlchemy dispatches
   pool events inside a greenlet (`sqlalchemy.util.concurrency.greenlet_spawn`).
   There, `traceback.extract_stack()` returns only SQLAlchemy runtime-generated
   frames (`<string>:_connection_for_bind:2`), and `asyncio.current_task().get_stack()`
   reaches only the outermost coroutine frame, not nested helpers that are suspended
   mid-await below it.  Walking `greenlet.getcurrent().parent.gr_frame` (and upward
   via `f_back`) recovers the suspended coroutine frames — including the nested
   function that leaked the session.  Also skip filenames starting with `"<"` on
   all stack-walk paths.
   Fixed in `server/db_attribution.py` `_origin_frames()`.
