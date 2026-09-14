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

## 核心問題 planning diagnosis (#763, 2026-09-14)

- The original provider response for the staging `2 candidates, expected 3`
  incident is unavailable; the warning and HTTP 502 identify one rejection but
  do not distinguish short provider output from parser loss. See
  [the issue evidence](https://github.com/paulpengtw/exam-generation/issues/763#issuecomment-5659661585).
- A controlled, sanitized response reproduces parser loss through the real
  planning endpoint for all three subjects:
  `1. 如何測量每天用水量？\n2. 如何比較不同節水方式？\n3.為何？`.
  The old fallback discarded the third numbered line because its length was
  five characters; the other two remained and both attempts ended in HTTP 502.
  Actual two-entry JSON also reaches the count rejection, independently of
  parsing. This confirms the controlled failure cause, not the original event's
  unknown response shape.
- The shared planner now accepts explicit numbered lists without a minimum
  question length, strips numbering, and validates distinct nonblank strings.
  It does not turn arbitrary prose, numbers, or objects into candidates. An
  invalid first response gets stage/count correction instructions and at most
  one more planning call. Exhaustion retains the controlled HTTP 502 fallback.
  Regressions exercise
  [the endpoint](https://github.com/paulpengtw/exam-generation/blob/fix/763-core-question-planning/tests/server/test_plan_core_questions_routes.py),
  including successful recovery and exhaustion for all three subjects.
- Staging check at **2026-09-14 07:29:13 UTC**, independently of generation:
  `https://examgen-staging.cpeng.me/api/schemas?subject=natural_sciences` returned
  HTTP 200; `POST /api/plan-core-questions` without credentials returned HTTP 401.
  No authenticated staging session was available, so this is reachability/auth
  evidence only, not a verdict on deployed planner behavior. No generation
  request was made; the separate #762 transport result cannot mask this gap.
- The exhausted-planner warning uses the explicit `planner_diagnostic` marker
  on the `server.generate.routes` logger. Backend Sentry filters only that
  warning event; the logging integration's breadcrumb remains on the chained
  exception, and same-logger unmarked warnings plus unrelated errors remain
  reportable. Safe breadcrumb metadata is stage, attempt, and expected/actual/
  received candidate counts; raw provider messages and request identity stay
  out of the event.
- Follow-up review reproduced non-`ValueError` provider exceptions leaking into
  the generic HTTP 500 traceback and a non-string response bypassing validation.
  Provider exceptions now use content-free `provider_call` diagnostics without
  retrying; a non-string response uses `response_shape` and the same two-attempt
  validation budget. Focused endpoint/Sentry verification passed 38 tests;
  confirmation coverage includes pending/completed rerenders, authoritative pins,
  stale responses, and top-level/per-question submission across all subjects.

## LLM exchange persistence diagnostics (#789, 2026-09-14)

- The original warning does **not** prove an exchange was lost. A controlled
  reproduction on staging commit `850c455f79b804d0cb84f8ef44efdfa8fde952f9`
  held a real database commit open beyond the real ten-second
  `concurrent.futures.Future.result()` wait. The recorder returned with exactly
  `llm_exchanges insert failed:` (empty exception text); after releasing the
  commit, the authenticated exchanges API returned the row. The reproduced
  error is `builtins.TimeoutError`, and the reproduced outcome is a delayed
  commit. This does not establish the cause of the five historical events in
  [#789](https://github.com/paulpengtw/exam-generation/issues/789).
- Historical access check: the Sentry issue API and staging `/api/history`
  both returned HTTP 401 without credentials. This session has no Sentry,
  database, or staging-auth environment variables. The issue contains event
  IDs but no generation-log UUIDs or exception classes, and has no comments.
  GitHub deployment `6432290186` was successful at 07:19:59 UTC for frontend
  SHA `8941814b7973428a485d39c1a5d2b90fd52ddcad`; that temporal association does
  not identify the backend revision or the eventual state of any exchange.
  Classifying those five events still needs authenticated, content-free
  correlation evidence; do not label them confirmed lost or delayed rows.
- [The recorder's persistence adapter](https://github.com/paulpengtw/exam-generation/blob/fix/789-exchange-persistence-diagnostics/server/generate/persistence.py)
  keeps the ten-second production wait and never cancels or retries an insert
  merely because that wait expires. A `pending` warning receives a follow-up
  `committed`, `failed`, or `cancelled` outcome when the scheduled future
  finishes. Scheduling rejection is `not_scheduled`; ordinary successful
  inserts remain quiet. An exception alone is not proof of row absence,
  particularly when a connection fails during commit acknowledgement.
- Diagnostics carry `generation_log_id`, `agent`, `exchange_order`,
  `outcome`, `error_type`, and `error_module`. The module distinguishes
  `builtins.TimeoutError` from `sqlalchemy.exc.TimeoutError`. These identifiers
  use the existing record/event contract; they do not implement the operation
  and call identities planned in
  [#743](https://github.com/paulpengtw/exam-generation/issues/743).
  Exception strings, reprs, tracebacks, and SQL parameters must stay out of
  these logs under
  [ADR 0004](https://github.com/paulpengtw/exam-generation/blob/staging/docs/adr/0004-what-sentry-is-allowed-to-collect.md).
- Regressions exercise real thread-to-event-loop scheduling, gated SQLite
  commits, real database rejection, and authenticated API read-back in
  [the persistence integration tests](https://github.com/paulpengtw/exam-generation/blob/fix/789-exchange-persistence-diagnostics/tests/server/test_exchange_persistence_integration.py).
  Only the wait budget is shortened after the original ten-second reproduction;
  the tests do not fabricate a timeout future. Run with
  `choom -n 500 -- uv run pytest tests/server/test_exchange_persistence_integration.py -q`.
- [Concurrent stream acceptance](https://github.com/paulpengtw/exam-generation/blob/fix/789-exchange-persistence-diagnostics/tests/server/test_exchange_persistence_stream.py)
  uses two concurrent SS/NS requests, two workers per request, and three
  parallel agent slots per worker. The real LLM client emits observer events;
  only the external provider SDK response is stubbed. All four results and
  History records are available while twelve exchange commits remain gated.
  Releasing the gate either commits all twelve exchanges (six per log) or
  produces twelve real `IntegrityError` outcomes with no exchange rows, when
  a database trigger rejects the inserts. Log correlation and content exclusion
  are checked in both cases.
- Verification: the broader Python run passed **2,164 tests, one skipped**;
  the final focused run, including the subsequently added concurrent-stream
  acceptance cases and final timeout-race correction, passed **33 tests**.
  Repository-wide Python lint passed. A timeout racing with an already
  completed future is classified from that future's actual result, so a
  completed commit is not mislabeled as a failed insert.
