## Context

See proposal.md for motivation. Code baseline: `staging@49c2869`.

- **Saving depends on the reader.**
  - `generate_question_stream` (`server/generate/service.py`) builds an `asyncio.Queue` and runs each question in `_worker_one` threads. The only `persist_generation_record` call sits inside the queue-consumer loop that yields SSE events (L1311–1335).
  - Its `finally` block sets `cancel_event` (L1341–1342), so closing the HTTP stream cancels every question.
- **Run lifecycle lives in the route.**
  - `_generate` in `server/generate/routes.py` (L485–601) creates the `GenerationLog`, defines the failure and abort tombstones in an inner function, and writes the final status in its own `finally`.
  - A disconnected run is logged as `completed` (L508).
- **The frontend aborts on unmount.** `useGenerate.ts` aborts the request when the component unmounts or resets (L672–692).
- **Status is a native enum.** `GenerationLog.status` is the Postgres enum `generation_status` with values `started`, `completed`, `failed` (`server/models.py` L12).
  - 人工審題修正 also creates `GenerationLog` rows (`modification_routes.py` L372). Its "already running" check filters on its own `question_id`, which generation rows never set (L296–301).
  - History reads only `GenerationRecord.status`.
- **No constraints on records.** `generation_records` has no unique constraint. Saves are best-effort, and a failure is only logged (`persistence.py` L232–278).
- **CI runs SQLite only.** `ci.yml` runs `uv run pytest` against SQLite (`server/db.py` L14). SQLite has no `FOR UPDATE SKIP LOCKED` and no native enums.
- **Deploy tooling exists.** The admission gateway, release policy and drain telemetry are described in DEPLOYMENT.md (#741). The frontend already has a preflight update message (`messages.ts` L734).

## Goals / Non-Goals

**Goals:**
- One deep run module whose small interface hides claiming, heartbeat, resume, save-before-publish, exactly-once 終止原因 and cancel.
- The same host loop runs inside the backend now and in a separate Railway worker later, changed only by configuration.
- The run-claim logic is testable against real Postgres in CI.

**Non-Goals:**
- Moving 人工審題修正 onto the run module. Its interface must fit it later, without that being built now.
- Carrying live event replay or per-agent activity across processes.
- Provider batch APIs.
- A new message broker (Redis or similar).

## Decisions

### D1. Save at question end, before publish
- `_worker_one_body` saves the final record at normal exit, then publishes `RESULT`.
- The thread waits on the event loop with `asyncio.run_coroutine_threadsafe(...).result(timeout)`, the same bridge the trail recorders use.
- The sidecar trails stop travelling in the queue envelope.
- Retries reuse the recorders' backoff loop. When retries are exhausted, the error is reported to Sentry and the question ends `failed`.
- This ships first as a behaviour-preserving slice. Cancel-on-disconnect stays until D3.
- *Alternative:* fire-and-forget save. Rejected, because a result a viewer has seen could then be missing from the database.

### D2. Idempotent records
- A unique constraint on `generation_records(generation_log_id, question_id)`, with insert-or-ignore.
- 人工審題修正 rows use their own `GenerationLog`, so they cannot collide.
- A migration pre-check reports any existing duplicates. See Open Questions.

### D3. 生成執行 module with four entry points
The module is `server/generate/run.py` or similar:
- `accept_run(params, user, submission_key)` → `(run_id, manifest)`
- `read_run(run_id, user)` / `list_runs(user)`
- `cancel_run(run_id, user)`
- `run_host_loop(stop_event, *, clock, client_factory, session_factory)`

The loop requeues stale runs, claims the next eligible run, executes it with a heartbeat task, and backs off when the queue is empty. Execution reuses `_build_run_context` and the existing 子題產生器 pipeline, keeping the v2 publisher as an internal event bus.

*Alternatives considered*, drafted by four independent designs:
- **Minimal:** 3 entry points, but a Host seam that exposed `_RunContext`.
- **Flexible:** a `RunHost` with dead methods on each adapter.
- **Common-caller:** one-line routes plus a shared loop. This became the base.
- **Ports and adapters:** a 7-method `RunStore` with an in-memory fake that cannot reproduce `SKIP LOCKED`.

### D4. No Host protocol
Cancel travels through the database (D6), so the two hosts differ only in who calls `run_host_loop`:
- the backend's lifespan task;
- `python -m server.worker`.

A Host interface would have one real adapter, which makes it a hypothetical seam. `GENERATION_HOST_ENABLED` (default on) selects whether a service runs the loop, and doubles as the emergency stop. The real seams are the LLM client (already injectable), the clock (system or fake) and the optional live observer (in-process queue or none).

### D5. Claiming, heartbeat and recovery
- **Claim:** `SELECT … FOR UPDATE SKIP LOCKED` on `generation_logs` where either:
  - status is `queued` and the owner has no `running` run; or
  - status is `running` and `heartbeat_at` is older than 3 minutes (stale).
- **On claim:** set `claimed_by`, increment `attempts`, set `status=running`, and set `started_at` on the first claim.
- **Heartbeat:** every 30 s. The invariant is stale ≥ 3 × heartbeat.
- **Attempt limit:** once `attempts` reaches 3, unfinished questions become `failed` with reason `recovery_exhausted`.
- **Time limit:** each heartbeat also enforces the 2 h ceiling, measured from `started_at`, with reason `time_limit`.
- **Resume** skips questions whose 處理狀態 is `ended`.
- **Trail entries** from an abandoned attempt are kept. Each figure-policy and reference-example entry gains an `attempt` field.
- **Per-host concurrency** `N` is a setting, starting at 3. The loop claims only while fewer than N runs are executing locally.

### D6. Cancel through a database flag
- `cancel_run` sets `generation_logs.cancel_requested`.
- The executing host checks it on every heartbeat and at every 生成步驟 boundary. When set, it sets the existing `confirmed_cancel_event`, which already yields `termination_reason=cancelled`. Latency is at most one heartbeat (~30 s), and the UI shows 取消中 at once.
- For questions that ended first, the first recorded outcome wins.
- *Alternative:* an in-memory fast path for the in-process host. Rejected, because it reintroduces a difference between the hosts (D4).

### D7. Schema
- **`generation_status`:** add `queued`, `running` and `cancelled` with `ALTER TYPE … ADD VALUE`, each in its own migration step because Postgres cannot use a new enum value in the same transaction.
- **New `generation_logs` columns:**
  - `heartbeat_at`, `attempts`, `claimed_by`, `started_at`, `cancel_requested`;
  - `submission_key`, with a unique constraint on `(user_id, submission_key)`;
  - `kind`, or keep deriving it from the `params_json.kind` convention. The claim filter uses `status IN ('queued','running')`, which 人工審題修正 rows never enter.
- **New `generation_question_states` table:**

  | Column | Content |
  |---|---|
  | `generation_log_id`, `question_id`, `index` | identity; unique on `(generation_log_id, question_id)` |
  | `processing` | `waiting` / `running` / `ended` |
  | `current_step` | the current 生成步驟 |
  | `termination_reason` | the 終止原因 |
  | `terminal_json` | the full `question_terminal` payload: delivery, missing slots, review |
  | `generation_record_id` | FK to the saved record |
  | `error` | error reason |
  | `updated_at` | last change |

- `termination_reason` is written with `UPDATE … WHERE termination_reason IS NULL`, which gives exactly-once.
- **Updating `current_step`:** a small incremental stager writes it. This is where the two existing recorder classes can be unified (architecture review candidate 4).

### D8. HTTP surface
Protocol version: keep the parameter name `stream_version`, now with value `3`, so the gateway, preflight and 426 handling keep working unchanged. Every route below is owner-only.

| Method and route | Behaviour |
|---|---|
| `POST /api/generate` | Returns 202 `{run_id, protocol_version: 3, total, questions}`. A limit breach returns 429 with a readable `detail`. |
| `GET /api/runs` | Lists the owner's runs, including queue position. |
| `GET /api/runs/{id}` | Per-question state and final results. |
| `POST /api/runs/{id}/cancel` | Requests cancellation of the whole run. |
| `GET /api/runs/{id}/events` | Optional live SSE, available only when the run executes in this process. It never affects the run. |

The old streaming path is removed at cutover.

### D9. Frontend
- **Submit and poll:** `useGenerate` submits, then polls `GET /api/runs/{id}` about every 3 s while visible and slower when hidden. It stops aborting on unmount and reset.
- **Opening the live stream:** the page opens the live stream only when the backend advertises that it is available.
- **One evidence model:** persisted state feeds `generationEvidence` through an adapter that produces the same per-question evidence shape as live events (review candidate 3). Cards, the 生成進度列 and the counts then use one model.
- **Unfinished runs in history:** `HistoryPage` gains a 「尚未結束」 section fed by `GET /api/runs`.
- **Navigation:** the nav badge polls the same list. Its state is derived from the existing `completed_at` being newer than the last time the teacher viewed it, remembered per browser.
- **New i18n strings:** 尚未結束, 排隊中 · 前面還有 k 個, 取消中, the limit messages, and the recovery-exhausted and time-limit reasons.

### D10. Tests
- A Postgres 16 service container in CI.
- Tests marked `postgres` run the run module: claim races with two concurrent claimers, stale requeue with a fake clock, the attempt limit, the per-teacher limit, cancel races, and the enum migration.
- The existing suites stay on SQLite.
- The D1 tests go through `_worker_one_body`, in the style of `test_858_worker_split_units.py`.

## Risks / Trade-offs

- **[Risk] An in-flight question is redone after each host replacement, costing extra model spend.**
  - Mitigation: a drain window of about p95 per question lets most in-flight questions finish.
  - The attempt limit bounds the spend.
- **[Risk] In-process hosting ties generation load to the web process.**
  - Mitigation: the per-host limit N.
  - The worker split is the follow-up and needs configuration only.
- **[Risk] Some teachers now wait in the queue.**
  - Mitigation: the queue position is visible.
  - N and the per-teacher limits are settings.
- **[Risk] Richer live activity is lost after the worker split.**
  - Accepted by the user.
  - Persisted 生成步驟 still drives the 生成進度列.
- **[Risk] Adding enum values is irreversible in Postgres.**
  - Mitigation: the rollback path leaves new values unused rather than dropping them.
  - Pre-cutover rows never hold them.
- **[Trade-off] Cancel latency is up to about 30 s,** in exchange for a single host code path.
- **[Risk] Duplicate historical records block the unique constraint.**
  - Mitigation: the pre-check query.
  - Deduplication, if needed, is a separate reviewed step.
- **[Risk] This change precedes the formal resolution of three wayfinder tickets.**
  - Mitigation: fold any divergence back with `/opsx:update`.

## Migration Plan

Each slice ships on its own.

1. **Save at question end** (D1, D2). No behaviour change beyond saving results whose readers vanished.
2. **Groundwork:**
   - Postgres in CI;
   - the enum values;
   - the new log columns;
   - `generation_question_states`;
   - the migration pre-check.
3. **Detached runs inside the backend.** This includes the run module, host loop, routes, frontend, history section, badge and limits. It is released through the one-time cutover:
   1. Pause the admission gate.
   2. Wait for positive drain evidence, following the existing runbook.
   3. Deploy the frontend and backend, and publish a release policy that marks pre-detached frontends unsupported.
   4. Verify: a new-client submit, read and cancel, an old-client 426, and old-tab preflight.
   5. Reopen the gate.
4. **Set `RAILWAY_DEPLOYMENT_DRAINING_SECONDS`** to the measured per-question p95. Use about 120 s until then.
5. **Separate Railway worker service,** with the same image and `python -m server.worker`, and `GENERATION_HOST_ENABLED=false` on the backend.
6. **Retire the drain-wait release step** after one release with no lost runs. The gate stays as the pause switch for 受理.

**Rollback:**
- Before slice 3, every slice reverts independently.
- After slice 3, a backend rollback runs with admission paused. Accepted runs stay queued and resume on the next compatible deploy, per the modified release-control spec.

## Open Questions

- **Per-question p95 duration** from production `generation_records` timestamps. This sets the drain window in slice 4; the specs already allow about 120 s until then.
- **Result of the duplicate pre-check** on production `generation_records`. It only decides whether a cleanup step precedes the constraint.
- **Starting values** for per-host N and the poll intervals. These are settings tuned after launch.
- **The "Four client-server combinations" requirement** in `generation-release-control` describes the v2 rollout. It is left unchanged. The detached cutover's acceptance is carried by the modified "Protocol rollout is atomic at public admission" requirement. When archiving, check whether the old matrix should be retired as historical.
