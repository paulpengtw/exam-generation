# Async generation migration — Railway 900 s timeout and architecture options

**Date:** 2026-09-28
**Related issues:** #702, #805, #734, #735, #736, #737

---

## TL;DR

Railway enforces a hard 900-second (15-minute) maximum on every HTTP request,
including SSE streams with active pings — confirmed in production (#702, #805) and
in Railway's own docs and a staff statement.  The current architecture ties
generation work to the SSE connection lifetime, so any run that exceeds 15 minutes
is silently killed by the edge proxy with an HTTP/2 `RST_STREAM CANCEL`, and no
result is persisted.  The fix is to decouple work from connection: accept the
generation request, immediately return a `job_id`, run the work as a background
coroutine/thread in the same process (or later in a separate worker service), and
let the client retrieve results through a polling endpoint or a reconnectable SSE
backed by a per-job DB event log.  A WebSocket upgrade is the one protocol
workaround that bypasses the 900 s cap without a full job-queue redesign, but it
requires replacing `fetchEventSource` on the frontend.  Provider batch APIs
(Anthropic and OpenAI both cap at 24 hours) are not suitable for interactive UX.

---

## 1. Current architecture

### Stack

Python 3.11, FastAPI, SQLAlchemy 2 (`asyncpg` driver), PostgreSQL (Railway Postgres
add-on), `sse-starlette` for SSE, `uvicorn`, Playwright renderer pool.  Frontend:
React + Vite, `@microsoft/fetch-event-source`.

### Generation request flow, end-to-end

1. Frontend submits `GET /api/generate` (legacy) or `POST /api/generate` (current
   default since #762), reaching the **gateway** → **backend** chain
   ([docker-compose.yml](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/docker-compose.yml)).

2. The backend route creates a `GenerationLog` row with `status="started"` and
   returns an `EventSourceResponse` wrapping `event_generator()`.
   ([routes.py L490–L598](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/server/generate/routes.py#L490-L598))

3. `event_generator()` calls `generate_question_stream()`, an async generator that
   dispatches one `loop.run_in_executor(None, _worker_one, ...)` thread per
   question.  Each thread calls the LLM provider(s) synchronously; results are
   pushed onto an `asyncio.Queue`, which the async generator drains and yields as
   SSE events.
   ([service.py L929–L1370](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/server/generate/service.py#L929-L1370))

4. Default models: planning and verification via **`claude-opus-4-6`** (Anthropic
   API with extended thinking), execution via **`gemini-3.1-pro-preview`** (Gemini
   API via OpenAI-compatible shim), optional image generation via OpenAI
   (`gpt-image2`).
   ([src/config.py L12–L14](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/src/config.py#L12-L14))

5. When a `result` event is generated, `persist_generation_record()` writes the
   question to `generation_records` **inside the SSE loop while the connection is
   still open**.  On disconnect (`asyncio.CancelledError`), any questions whose
   `result` event was never yielded are not persisted.
   ([routes.py L542–L596](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/server/generate/routes.py#L542-L596))

6. The frontend SSE `onerror` handler throws on any network error, sets
   `status="error"`, and does not reconnect.
   ([useGenerate.ts L1495–L1518](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/web/src/hooks/useGenerate.ts#L1495-L1518))

### Existing DB models

| Table | Key columns | Purpose |
|---|---|---|
| `generation_logs` | `id`, `user_id`, `params_json`, `status` (started/completed/failed), `started_at`, `completed_at`, `error` | One row per SSE connection; updated to `completed` or `failed` when the stream ends |
| `generation_records` | `id`, `generation_log_id`, `question_json`, `verification_trail_json`, `status` (completed/failed/aborted) | One row per generated question; written when a `result` event flows through the stream |
| `llm_exchanges` | `id`, `generation_log_id`, `exchange_order`, `agent`, `request_body`, `response_body` | Per-LLM-call audit log |

No job-queue tables, no worker-process tables, no event-log/replay tables exist.

### Existing drain / shutdown infrastructure

The backend exposes a restricted `GET /internal/drain` telemetry endpoint that
reports live gauges (`active_runs`, `active_workers`, `open_streams`, etc.) for
operator-assisted drain-before-redeploy procedures.
([drain.py](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/server/generate/drain.py),
[internal/routes.py](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/server/internal/routes.py))
`uvicorn` is started with no `--timeout-graceful-shutdown` flag
([Dockerfile.backend](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/Dockerfile.backend)).

### Nginx proxy timeouts

Frontend nginx uses `proxy_read_timeout 300s` on the `/api/` block, which is
reset by every SSE ping so it is not the binding constraint.
([nginx.conf.template L24–L25](https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/web/nginx.conf.template#L24-L25))

---

## 2. Evidence of failure

### Issue #702 — Railway edge resets long SSE streams at 900 s (closed, wontfix)

A staging run on 2026-09-10 received an HTTP/2 `RST_STREAM(CANCEL)` from
`server: railway-hikari` at exactly **900.3 s** while pings were still flowing
every 15 s.  Curl: `(92) HTTP/2 stream 1 was not closed cleanly: CANCEL (err 8)`.
The backend wrote an `aborted` record 0.1 s later.  The investigation confirmed
**two edge hops**, both subject to the cap.  The issue was closed as **wontfix**
because the cap is a fixed Railway platform limit.  The timeline is captured at
[`docs/research/2026-09-10-689-sse-started-stall/timeline_starve_C.txt`](https://github.com/paulpengtw/exam-generation/blob/f446a820df0c3735260c3f4a783dcaefe557a817/docs/research/2026-09-10-689-sse-started-stall/timeline_starve_C.txt).
([#702](https://github.com/paulpengtw/exam-generation/issues/702))

### Issue #805 — 900-second cutoff, remediation plan needed (open)

A social-studies question (`ss_20260914_103304_001`, seed `401183334`) failed in
production on 2026-09-14 after **900,150.9 ms** with a browser network error — no
`result` or `done` event arrived, and a subsequent History query found no matching
record.  Two verification passes and the first correction had completed; the second
correction was in progress.  Multiple earlier attempts also disconnected at
approximately 900 seconds.  The issue cites the Railway docs and links to the #702
investigation as prior evidence.
([#805](https://github.com/paulpengtw/exam-generation/issues/805))

### Issue #628 — worker thread kept alive after disconnect (closed)

Before #856–#858, an aborted SSE stream left the underlying `_worker_one` thread
running (holding the now-removed global `_GEN_LOCK`), blocking subsequent
generations for 15+ minutes.  Cooperative cancellation via `cancel_event` was
added in the #856–#858 refactor, so this specific stall is fixed, but it
illustrates the fundamental coupling between connection lifetime and worker lifetime.
([#628](https://github.com/paulpengtw/exam-generation/issues/628))

### Wayfinder map #734 and decisions #735–#737 (open)

The open wayfinder map "斷線續跑與最新狀態／結果恢復" (#734) and its three
sub-decisions (#735, #736, #737) are the existing roadmap for exactly this
migration — product guarantees, work-lifecycle decoupling, and reconnect/resume
design.  None of the sub-decisions have been resolved yet; they are awaiting
human input.
([#734](https://github.com/paulpengtw/exam-generation/issues/734),
[#735](https://github.com/paulpengtw/exam-generation/issues/735),
[#736](https://github.com/paulpengtw/exam-generation/issues/736),
[#737](https://github.com/paulpengtw/exam-generation/issues/737))

---

## 3. Railway's actual limits

All quotes are from Railway's official documentation or confirmed staff statements.

### HTTP request duration

> "HTTP requests can run for up to 15 minutes if data keeps transferring (for
> example, keep-alive heartbeats), and are otherwise closed after 5 minutes with
> no data transferred."
> — [docs.railway.com/networking/public-networking/specs-and-limits](https://docs.railway.com/networking/public-networking/specs-and-limits)

A Railway employee (Brody) confirmed on the Railway Help Station:

> "The platform maximum HTTP request timeout is 15 minutes, any limit that is
> lower than that would be a self imposed limit at the application level."
> — [station.railway.com/questions/increase-max-http-timeout-1c360bf9](https://station.railway.com/questions/increase-max-http-timeout-1c360bf9)

**This limit is not configurable at the service or plan level.**

### WebSocket exception

> "Websocket connections are exempt from these duration and inactivity limits, and
> can stay open indefinitely, even while idle."
> — [docs.railway.com/networking/public-networking/specs-and-limits](https://docs.railway.com/networking/public-networking/specs-and-limits)

This is the one available protocol escape hatch on Railway for long-lived
connections — WebSocket upgrades are not capped at 900 s.

### Redeploy and SIGTERM grace period

> "Once the new deployment is online, the old deployment is sent a SIGTERM signal.
> By default, it is given **0 seconds** to gracefully shutdown before being
> forcefully stopped with a SIGKILL."
> — [docs.railway.com/reference/deployments](https://docs.railway.com/reference/deployments)

This is configurable via `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` (default `0`).
The overlap window before the old deployment is removed is controlled by
`RAILWAY_DEPLOYMENT_OVERLAP_SECONDS` (default `0`).
— [docs.railway.com/reference/variables](https://docs.railway.com/reference/variables#user-provided-configuration-variables)

Practical consequence: without raising `RAILWAY_DEPLOYMENT_DRAINING_SECONDS`,
any in-flight generation work is SIGKILL'd immediately on every redeploy.

### Worker services and private networking

Railway supports multiple services per project — the repo already runs backend,
frontend, and gateway as three separate services.  A dedicated worker service is
fully supported.  Services communicate via `SERVICE_NAME.railway.internal:PORT`
over WireGuard-encrypted private networking.
— [docs.railway.com/guides/private-networking](https://docs.railway.com/guides/private-networking)

### Cron jobs

Railway can run a service on a cron schedule; the service must exit when done.
"If a previous execution is still running when the next scheduled execution is due,
Railway will skip the new cron job."  Minimum interval: 5 minutes.
— [docs.railway.com/reference/cron-jobs](https://docs.railway.com/reference/cron-jobs)

### Volumes

Available; Hobby plan = 5 GB limit.  **"Replicas cannot be used with volumes"**
— horizontal scaling and persistent local state are mutually exclusive.
— [docs.railway.com/reference/volumes](https://docs.railway.com/reference/volumes)

---

## 4. Migration options

### Option A — In-process background task + job-status table + polling (shortest path)

Accept the request (create a `generation_jobs` row, return `job_id` immediately),
start an `asyncio.create_task()` or submit to a thread pool that is **not** tied
to the HTTP connection, and let the client poll `GET /api/jobs/{id}/status`.  The
existing `generation_records` table already stores per-question results that can be
fetched independently.

**Pros**: No new infrastructure.  Small diff — mainly a new endpoint, a job-state
table, and removing the connection-lifetime coupling from `generate_question_stream`.
**Cons**:
- Railway's default 0-second SIGTERM means an asyncio Task or executor thread is
  SIGKILL'd immediately on every redeploy.  `RAILWAY_DEPLOYMENT_DRAINING_SECONDS`
  must be raised to the expected generation ceiling (~20–30 min for long runs),
  which will delay rollbacks.
- No cross-process or cross-restart durability.  A crash or OOM loses the in-flight
  job with no automatic recovery.

### Option B — Separate Railway worker service + Postgres-based job queue

A `worker` Railway service runs the same Python codebase with a `CMD` that polls a
job table instead of serving HTTP.  The backend service only accepts requests,
inserts job rows, and returns `job_id`.

**Queue pattern**: `SELECT ... FOR UPDATE SKIP LOCKED` on the `generation_jobs`
table — no additional message broker required, Postgres already in place.  This is
the approach used by the Python libraries `procrastinate` and `pg-boss` (Node).
Relevant Python options in this stack:
- **procrastinate** (pure-Postgres, asyncio-native, supports asyncpg):
  [`procrastinate.readthedocs.io`](https://procrastinate.readthedocs.io) — native
  async, supports deferred and retry with exponential backoff.
- **`SELECT FOR UPDATE SKIP LOCKED`** rolled by hand in SQLAlchemy — trivial
  dependencies, full control.

Both approaches require marking jobs `running` at pickup, with a heartbeat timeout
that allows re-queuing if the worker dies mid-job.

**Pros**:
- Work survives client disconnect unconditionally.
- A SIGTERM'd worker can mark its job `interrupted`, and a new worker instance
  restarts it from the last-persisted per-question checkpoint.
- The 900 s connection cap is irrelevant — no HTTP connection stays open for the
  duration of work.

**Cons**:
- New Railway service: billing, deploy surface, and ops.
- Without per-question checkpointing in the existing DB, an interrupted multi-
  question batch must restart all questions (not only the incomplete ones).
- Questions that have already been written to `generation_records` before the
  interrupt must be made idempotent at re-run (idempotency key = `generation_log_id
  + question_index`).

### Option C — WebSocket upgrade (protocol bypass)

Railway exempts WebSocket connections from the 15-minute cap entirely.  Replacing
the SSE `EventSourceResponse` with a WebSocket handler, and replacing
`@microsoft/fetch-event-source` with a WebSocket client on the frontend, would
bypass the 900 s limit without the async-job redesign.

**Pros**: Small backend change; keeps the push-event model; bypasses the hard cap.
**Cons**:
- Front-end WebSocket reconnect handling is more complex than SSE's auto-reconnect
  behavior.
- Does not fix the SIGTERM-kills-in-flight-work problem on redeploy.
- Does not make work resumable after a network drop; on a reconnect, the client
  sees only events emitted after reconnect (no replay without an event store).
- For very long batches (> 20–30 min), the connection itself may drop from
  unrelated causes (mobile networks, browser background throttling).

### Option D — SSE with `Last-Event-ID` replay from DB

Add an `sse_events` table storing every event payload keyed by `(generation_log_id,
event_seq)`.  The SSE stream writes each event to the DB before yielding it; on
reconnect the client sends `Last-Event-ID` and the server replays from that point.
Tracked as a design option in #734–#736.

**Pros**: Keeps SSE; makes reconnect transparent; existing `generation_log_id` is
already propagated through the whole stack.
**Cons**:
- The 900 s Railway cap still applies to each connection segment; a generation
  that takes 16 minutes requires at least one forced reconnect.
- Event store adds storage pressure (each LLM streaming chunk is an event).
- Does not address SIGTERM: workers in-process die on redeploy.

### Option E — Provider Batch APIs

**Anthropic Message Batches API**: "Batches can take up to 24 hours to complete."
([platform.claude.com/docs/en/api/creating-message-batches](https://platform.claude.com/docs/en/api/creating-message-batches))

**OpenAI Batch API**: "Each batch completes within 24 hours (and often more quickly)";
50% cost discount.
([developers.openai.com/api/docs/guides/batch](https://developers.openai.com/api/docs/guides/batch))

Both APIs are designed for offline/batch workloads with up-to-24-hour latency.
The current interactive UX requires results in under 15 minutes.  These APIs are
**not suitable** as a replacement for the synchronous generation loop.

They could be used to pre-generate question banks offline (e.g., seeded batches
run nightly) at reduced cost, but that is a separate product decision outside the
scope of this issue.

---

## 5. Recommendation

### Target architecture

**Phase 1 — decouple work from connection (immediate blocker fix)**

1. Add a `generation_jobs` table:

   ```
   generation_jobs
     id            UUID PK
     user_id       UUID FK → users
     generation_log_id  UUID FK → generation_logs (nullable, set when log is created)
     params_json   JSONB
     status        ENUM (pending, running, completed, failed, cancelled)
     created_at    TIMESTAMPTZ
     started_at    TIMESTAMPTZ nullable
     completed_at  TIMESTAMPTZ nullable
     worker_heartbeat_at  TIMESTAMPTZ nullable  -- for stale-job detection
     error         TEXT nullable
   ```

2. Replace `POST /api/generate` semantics: create `GenerationLog` + `generation_jobs`
   row, return `{"job_id": "..."}` immediately (HTTP 202), do not open SSE from
   this endpoint.

3. Start an `asyncio.create_task(run_generation_job(job_id))` (or submit to the
   existing thread pool) that calls `generate_question_stream()` without a
   client-facing connection.  Per-question `generation_records` persist as before —
   this part of the existing code is unchanged.

4. Add `GET /api/jobs/{id}/status` → `{ status, completed_questions, total_questions,
   generation_log_id }`.

5. Add `GET /api/jobs/{id}/results` → list of `generation_records` for that log.

6. Keep the existing SSE endpoint as a **live-progress** view that a client
   **may** connect to but whose disconnect no longer cancels work.  Wire a
   short-lived reconnectable SSE to the same `asyncio.Queue`, or keep SSE as
   optional progress reporting (not required for correctness).

7. Set `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` to 1200 (20 min) on the backend
   Railway service so in-flight asyncio tasks get a SIGTERM window.  Add a
   SIGTERM handler in `lifespan` that sets a shutdown flag and awaits pending
   tasks before exiting.

**Files that change in Phase 1**:
- `alembic/versions/` — new migration for `generation_jobs`
- `server/models.py` — `GenerationJob` ORM model
- `server/generate/routes.py` — submit endpoint returns 202 + `job_id`; SSE
  becomes optional live-progress endpoint
- `server/generate/service.py` — `generate_question_stream` runs detached from
  connection lifetime
- `server/generate/persistence.py` — job-state transitions
- `server/app.py` — SIGTERM handler
- `web/src/hooks/useGenerate.ts` — switch from blocking SSE to submit + poll
  (or optional live SSE for progress during the 900 s window)

**Phase 2 — worker service for cross-redeploy durability**

Extract job pickup into a separate Railway service (`worker`) that polls:

```sql
SELECT id FROM generation_jobs
WHERE status = 'pending'
   OR (status = 'running' AND worker_heartbeat_at < NOW() - INTERVAL '5 minutes')
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

Mark it `running`, run the generation, update to `completed`/`failed`.  The worker
uses `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` and a cooperative shutdown loop.

This makes the system durable against crashes and OOM events, at the cost of one
additional Railway service and the ops surface that entails.

### Open questions for the user

1. **Per-question resumability**: Should a restarted job skip questions already in
   `generation_records` for this `generation_log_id`?  If yes, an idempotency
   check on `(generation_log_id, question_index)` is needed before each worker.

2. **UX after submit**: Should the UI show a job list (teacher sees all pending and
   completed generations) or should the current generation page poll and auto-
   display results as they are written?  The wayfinder sub-decisions #735–#736
   must answer this before the frontend work begins.

3. **SIGTERM ceiling**: A 20-minute SIGTERM drain window slows Railway rollbacks.
   Decide the acceptable trade-off between deploy speed and in-flight protection
   before Phase 1 ships.

4. **Cancellation**: The current cooperative `cancel_event` works for connection-
   initiated cancels; explicit user cancellation of a background job requires a
   separate `POST /api/jobs/{id}/cancel` endpoint and a mechanism to signal the
   running worker.

5. **Concurrency limits**: The existing gateway admission control pauses new
   generations; Phase 1 must preserve this gate to prevent a queue of background
   jobs from overwhelming the process.

---

## Sources

| Citation | URL |
|---|---|
| Railway HTTP specs and limits | https://docs.railway.com/networking/public-networking/specs-and-limits |
| Railway staff confirmation — 15 min not configurable | https://station.railway.com/questions/increase-max-http-timeout-1c360bf9 |
| Railway deployments — SIGTERM and SIGKILL | https://docs.railway.com/reference/deployments |
| Railway variables — draining and overlap seconds | https://docs.railway.com/reference/variables#user-provided-configuration-variables |
| Railway private networking | https://docs.railway.com/guides/private-networking |
| Railway volumes — replica restriction | https://docs.railway.com/reference/volumes |
| Railway cron jobs | https://docs.railway.com/reference/cron-jobs |
| Anthropic Message Batches API | https://platform.claude.com/docs/en/api/creating-message-batches |
| OpenAI Batch API | https://developers.openai.com/api/docs/guides/batch |
| Issue #702 — Railway 900 s confirmed | https://github.com/paulpengtw/exam-generation/issues/702 |
| Issue #805 — 900 s failure in production | https://github.com/paulpengtw/exam-generation/issues/805 |
| Issue #628 — worker thread leak | https://github.com/paulpengtw/exam-generation/issues/628 |
| Issue #734 — wayfinder map (recovery design) | https://github.com/paulpengtw/exam-generation/issues/734 |
| `server/generate/routes.py` (SSE handler) | https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/server/generate/routes.py |
| `server/generate/service.py` (generate_question_stream) | https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/server/generate/service.py |
| `server/models.py` (DB models) | https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/server/models.py |
| `web/src/hooks/useGenerate.ts` (SSE onerror) | https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/web/src/hooks/useGenerate.ts |
| `web/nginx.conf.template` (proxy_read_timeout) | https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/web/nginx.conf.template |
| `Dockerfile.backend` (uvicorn start command) | https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/Dockerfile.backend |
| `src/config.py` (default LLM models) | https://github.com/paulpengtw/exam-generation/blob/49c286938529cd77c0e36154d50e6fd99fe74bfd/src/config.py |
