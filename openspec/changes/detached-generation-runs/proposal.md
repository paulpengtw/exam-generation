## Why

Railway cuts every HTTP request, including SSE streams with live pings, at 900 seconds ([Railway edge resets long SSE streams at 900 s](https://github.com/paulpengtw/exam-generation/issues/702), [Diagnose the 900-second cutoff and approve a remediation plan](https://github.com/paulpengtw/exam-generation/issues/805)). Today a generation lives only as long as its SSE connection:

- Question results are saved only when the stream reader takes them off the queue.
- The stream's cleanup cancels the whole run when the connection closes.

So any batch that takes longer than 15 minutes, or whose teacher leaves the page, loses work the teacher is paying for.

The goal, confirmed by the user on 2026-09-28: a generation that takes longer than Railway's 900 s request limit no longer fails. The teacher submits, the work runs detached from the browser, and the results appear in the system when they're ready.

## What Changes

- **BREAKING (API)** `POST /api/generate` no longer streams.
  - It records 受理 and returns a run identity plus the full question manifest immediately.
  - Progress and results are read from persisted state.
  - Old clients are rejected with a readable update request during a one-time cutover.
- A new **生成執行** (generation run) lifecycle. A run exists from 受理 until every question has a 終止原因, whether or not anyone is watching.
  - Leaving the page, losing the connection, closing the browser or logging out never cancels a run.
  - Only the owning teacher's explicit Cancel stops it.
- Each question's result is saved before it is delivered to any observer, exactly once per question.
- If the process running a run stops (crash, restart, deploy), the run resumes elsewhere.
  - Questions that already ended are kept; the in-flight question is redone.
  - Bounded attempts and a total time limit apply; after that, unfinished questions end as failed with a visible reason.
- Per-question 處理狀態, current 生成步驟 and 終止原因 are persisted and readable by the owner. This state is authoritative for everything a returning teacher sees.
- A duplicate-submission key, so a retried 確定發送 cannot create a second paid run.
- Admission limits:
  - one executing run per teacher;
  - at most five queued runs per teacher;
  - a per-host concurrency cap.
- Teacher surfaces:
  - the generation page fills in from persisted state;
  - a 「尚未結束」 section heads the history page, showing 「排隊中 · 前面還有 k 個」 for queued runs;
  - Cancel shows 「取消中」;
  - an in-app badge appears when a run ends.
- The live v2 event stream becomes an optional observation channel while run and viewer share a process. It is no longer required for correctness.
- Release control changes:
  - the admission gate keeps pausing new 受理;
  - once the new model has shipped one clean release, deployments no longer need to wait for in-flight generation to drain.
- Not in scope:
  - moving 人工審題修正 onto the run lifecycle;
  - per-question cancel;
  - splitting the run host into a separate Railway worker service. That is a follow-up deployment step; this change keeps the host code identical so the split needs no code change.

## Capabilities

### New Capabilities
- `generation-run`: The detached generation run. This covers:
  - 受理 and duplicate-submission handling;
  - execution independent of observers;
  - save-before-deliver;
  - exactly-once 終止原因;
  - explicit owner cancel;
  - recovery after host failure;
  - admission limits;
  - owner-only reading of persisted run state;
  - the teacher surfaces that show it.

### Modified Capabilities
- `generation-event-protocol`:
  - admission now creates a run and returns the manifest instead of opening a stream;
  - the manifest is allocated and persisted at 受理;
  - stream closure no longer ends or cancels the run, and recovery is now promised through `generation-run`.
- `per-question-live-progress`:
  - the client validates the manifest from the 受理 response;
  - persisted run state supplies terminal evidence and counts;
  - losing a live connection falls back to persisted state instead of marking outcomes unknown.
- `generation-release-control`:
  - admission suspension stops new 受理 only, while accepted runs keep executing;
  - positive drain evidence is required only until the detached model has completed one clean release;
  - the protocol cutover and rollback rules cover the detached model.

## Impact

- **Backend:**
  - `server/generate/routes.py`: the submit route becomes non-streaming, and new owner-only status and cancel routes are added.
  - `server/generate/service.py`: saving moves to question end, and run orchestration is separated from SSE transport.
  - `server/generate/persistence.py`
  - `server/models.py`: `GenerationLog` gains new status values and claim, heartbeat and cancel columns, and a per-question 處理狀態 table is added.
  - `server/app.py`: the lifespan starts the run host loop, controlled by `GENERATION_HOST_ENABLED`.
  - A new run module.
  - Alembic migrations, including `ALTER TYPE generation_status`.
- **Frontend:**
  - `web/src/hooks/useGenerate.ts`: submit then poll, and no abort on unmount.
  - `web/src/lib/generationEvidence.ts`
  - `web/src/pages/GeneratePage.tsx`
  - `web/src/pages/HistoryPage.tsx`
  - the navigation badge;
  - i18n messages.
- **Tests and CI:** a Postgres service in CI for run-claim tests, because SQLite has no `FOR UPDATE SKIP LOCKED` and no native enums.
- **Operations:**
  - DEPLOYMENT.md cutover runbook.
  - Railway `RAILWAY_DEPLOYMENT_DRAINING_SECONDS`: about 120 s until the per-question p95 duration is measured.
  - The drain-wait release step is retired after one clean release.
- **Prerequisite facts that need production database access:**
  - a duplicate check before adding the `(generation_log_id, question_id)` unique constraint;
  - per-question p95 duration.
- **Process:** decisions come from the user's 2026-09-28 HITL session.
  - The product guarantees are resolved in [決定斷線續跑的產品保證與停止邊界](https://github.com/paulpengtw/exam-generation/issues/735#issuecomment-5873107609).
  - The architecture, recovery-surface and release decisions are recorded as input on these tickets, which are still open:
    - [決定生成工作與狀態保存如何獨立於 SSE 連線](https://github.com/paulpengtw/exam-generation/issues/736#issuecomment-5873169549)
    - [決定重返批次時的恢復、權限與一致性契約](https://github.com/paulpengtw/exam-generation/issues/737#issuecomment-5873170071)
    - [決定續跑與恢復能力的發布、回滾及驗收](https://github.com/paulpengtw/exam-generation/issues/738#issuecomment-5873170541)
  - The user chose to create this change before those tickets are formally resolved. Any divergence found when they are resolved must be folded back with `/opsx:update`.

## ADRs

The following ADRs record decisions made for this change:

- [ADR 0033](../../../../docs/adr/0033-only-the-owner-cancels-a-generation-run.md) — only the owner cancels a 生成執行; observer disconnection does not
- [ADR 0034](../../../../docs/adr/0034-there-is-no-host-protocol.md) — there is no Host protocol: in-backend host and worker service run the same loop
- [ADR 0035](../../../../docs/adr/0035-run-claim-tests-target-postgres-in-ci.md) — run-claim tests target Postgres in CI because SQLite cannot exercise SKIP LOCKED or native enums
