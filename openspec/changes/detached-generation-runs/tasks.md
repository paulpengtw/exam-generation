## 1. Save at question end (slice 1: no behaviour change)

- [ ] 1.1 Write failing tests through `_worker_one_body` (stub-context style of `tests/server/test_858_worker_split_units.py`, fake session factory) asserting the record is saved before `RESULT` is published and that a `RESULT` never dequeued is still saved. Verify: new tests fail on current code.
- [ ] 1.2 Move `persist_generation_record` from the consumer loop in `generate_question_stream` into `_worker_one_body`. Move it to the normal exit, before `RESULT` is published, using `asyncio.run_coroutine_threadsafe(...).result(timeout)`. Drop the sidecars from the queue envelope. Verify: 1.1 passes, and the existing persistence suites (`test_persistence.py`, `test_verification_trail_persistence.py`, `test_figure_policy_trail_persistence.py`, `test_reference_example_record_persistence.py`, `test_generation_publisher.py`) pass unchanged.
- [ ] 1.3 Add bounded retry with backoff (reusing the recorder retry loop) and a Sentry report when retries are exhausted. Verify: a test with a failing session factory shows N retries, then a Sentry capture, and the question is not reported as saved.
- [ ] 1.4 Write the production duplicate pre-check query for `generation_records(generation_log_id, question_id)` into DEPLOYMENT.md, and hand it to someone with production access. Verify: the query is committed and its result is recorded in the change notes before 1.5 ships.
- [ ] 1.5 Add an Alembic migration with a unique constraint on `(generation_log_id, question_id)`, and make the insert insert-or-ignore. Verify: a test saving the same question twice leaves one row, and `alembic upgrade head` succeeds on SQLite and Postgres.

## 2. Groundwork (slice 2)

- [ ] 2.1 Add a Postgres 16 service container to `.github/workflows/ci.yml`, plus a `postgres` pytest marker and a fixture using `DATABASE_URL`. Verify: CI runs a marked smoke test against Postgres, and unmarked tests still use SQLite.
- [ ] 2.2 Add migrations that give `generation_status` the values `queued`, `running` and `cancelled`, each with `ALTER TYPE … ADD VALUE` in its own transaction. Update `GenerationStatus` and `tests/server/test_db_models.py`. Verify: the enum test and a Postgres-marked migration test pass.
- [ ] 2.3 Add a migration adding `generation_logs` columns `heartbeat_at`, `attempts`, `claimed_by`, `started_at`, `cancel_requested`, `submission_key`, with a unique constraint on `(user_id, submission_key)`. Verify: the migration round-trips on Postgres, and the 人工審題修正 route tests still pass.
- [ ] 2.4 Add a migration and model for `generation_question_states`. Columns: identity, `index`, `processing`, `current_step`, `termination_reason`, `terminal_json`, `generation_record_id`, `error`, `updated_at`. Add a unique constraint on `(generation_log_id, question_id)`. Verify: model tests pass, and an exactly-once update (`WHERE termination_reason IS NULL`) test passes on Postgres.
- [ ] 2.5 Unify `FigurePolicyTrailRecorder` and `ReferenceExampleRecordRecorder` behind one incremental stager parameterised by column. Add the `attempt` field to entries. Verify: the existing trail persistence tests pass, plus a new test showing entries tagged by attempt.

## 3. 生成執行 module (slice 3, backend)

- [ ] 3.1 Implement `accept_run(params, user, submission_key)`. It writes the log (`queued`) and the waiting question states in one transaction, returns the run ID and manifest, returns the existing run for a repeated key, and rejects a sixth queued run. Verify: tests for the atomic write, the duplicate key and the queue limit pass.
- [ ] 3.2 Implement claiming with `SELECT … FOR UPDATE SKIP LOCKED`. It must enforce one running run per teacher, per-host limit N, stale-run requeue after 3 min, and 3 attempts followed by `recovery_exhausted` failure. Verify: Postgres-marked tests show two concurrent claimers never claim the same run, and stale requeue and attempt exhaustion work with a fake clock.
- [ ] 3.3 Implement run execution. It reuses `_build_run_context` and the 子題產生器 pipeline, skips questions already ended, and writes `current_step` at each 生成步驟. It records `termination_reason` and `terminal_json` exactly once, and runs a heartbeat task that enforces the 2 h ceiling (`time_limit`). Verify: tests for resume skipping ended questions, the first-recorded-wins outcome and the time limit (fake clock) pass.
- [ ] 3.4 Implement `cancel_run`. It sets `cancel_requested`, which the host checks on each heartbeat and at each 生成步驟 boundary, then sets `confirmed_cancel_event`. It is owner-only, and a no-op once every question has ended. Verify: tests for the cancel mid-run, cancel-versus-completion and non-owner rejection cases pass.
- [ ] 3.5 Implement `run_host_loop(stop_event, …)` and start it in the `server/app.py` lifespan behind `GENERATION_HOST_ENABLED`. Add a `server/worker.py` `__main__` entry point that runs the same loop. Verify: a test starts the loop, runs a stub run to completion and stops cleanly, and `python -m server.worker` starts locally.
- [ ] 3.6 Add the routes:
  - `POST /api/generate` returns 202 with `stream_version=3`; versions 2 or absent get 426; a limit breach gets 429.
  - `GET /api/runs`
  - `GET /api/runs/{id}`
  - `POST /api/runs/{id}/cancel`
  - optional `GET /api/runs/{id}/events`, available in-process only.

  Remove the streaming generate path. Verify: route tests for every status code, owner-only access, and an observer disconnect not affecting the run.

## 4. Frontend (slice 3)

- [ ] 4.1 Make `useGenerate` generate a submission key per 確定發送, submit, then poll `GET /api/runs/{id}` (about 3 s while visible, slower when hidden). Remove the abort on unmount and reset. Verify: `useGenerate.test.ts` covers the key reuse on retry, polling, and unmount not cancelling.
- [ ] 4.2 Add a persisted-state adapter feeding `generationEvidence`, so cards, the 生成進度列 and 已結束 X/N / 收到最終結果 Y counts combine live and persisted evidence without double counting. Verify: vitest cases from the modified `per-question-live-progress` scenarios pass, including counts after returning and connection loss.
- [ ] 4.3 Add the Cancel control with an immediate 取消中 state. Verify: a component test shows 取消中, then the cancelled 終止原因 from polled state.
- [ ] 4.4 Add the 「尚未結束」 section to `HistoryPage` with 「排隊中 · 前面還有 k 個」, and move ended runs into the normal list. Verify: `HistoryPage` tests for queued, executing and ended runs pass.
- [ ] 4.5 Add the navigation badge for newly ended runs, with a per-browser last-seen marker wrapped in try/catch. Verify: a component test shows the badge appears after a run ends and clears once viewed.
- [ ] 4.6 Add the i18n strings (尚未結束, 排隊中, 取消中, the queue-limit message, the recovery-exhausted and time-limit reasons) for every locale. Verify: the i18n completeness test passes.

## 5. Cutover and operations (slice 3 release)

- [ ] 5.1 Update DEPLOYMENT.md with the one-time cutover runbook, the rollback path (admission paused, accepted runs stay queued) and `GENERATION_HOST_ENABLED`. Verify: the runbook reviewed against the modified `generation-release-control` scenarios.
- [ ] 5.2 Publish a release policy marking pre-detached frontends unsupported, and confirm that old tabs show 介面版本已更新，請重新整理頁面後再生成。 Verify: a staging check with an old build shows the message and no run is created.
- [ ] 5.3 End-to-end check on staging with stubbed models:
  - a run longer than 900 s completes;
  - closing the tab mid-run and returning shows correct states and results;
  - a deploy mid-run resumes without regenerating ended questions;
  - Cancel works, and the per-teacher limits apply.

  Verify: record the results in the change notes.
- [ ] 5.4 Update CONTEXT.md:
  - add 生成執行, 排隊中, 取消中, 尚未結束;
  - redefine 受理;
  - note that 處理狀態 is persisted per question.

  Add ADRs for:
  - observers never cancel, only an explicit owner cancel does;
  - no Host protocol;
  - claim tests run on Postgres.

  Verify: the files are reviewed and linked from the proposal.

## 6. Tuning and worker split (slices 4–6)

- [ ] 6.1 Measure per-question p95 duration from production timestamps, and set `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` to it (about 120 s until measured). Verify: the value is recorded in DEPLOYMENT.md, and one deploy mid-run finishes the in-flight question without a redo.
- [ ] 6.2 Create the Railway worker service (same image, `python -m server.worker`) and set `GENERATION_HOST_ENABLED=false` on the backend. Verify: runs execute on the worker, and a backend redeploy leaves them untouched.
- [ ] 6.3 After one release with no lost runs, remove the drain-wait step from the release procedure and report queued and executing run counts instead. Verify: DEPLOYMENT.md is updated, and the next deploy proceeds without drain while a run resumes.
