# Verification Trail Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist each completed generation’s verification trail beside its question, expose it from history detail, and render it through the existing timeline while keeping downloaded question JSON trail-free.

**Architecture:** Add a nullable `verification_trail_json` JSON column to `GenerationRecord`. The generation worker already receives typed trail callbacks, so it will serialize each callback into a worker-local list and attach that list to the internal result envelope consumed by the persistence seam; the public SSE result remains question-shaped. History detail returns the column only on the detail route, while `HistoryDetail` passes the nullable value through `QuestionCard` to the existing `VerificationTrailTimeline`, which renders an explicit legacy/skip-verify empty state for `null`.

**Tech Stack:** Python 3.11, SQLAlchemy async ORM, Alembic, FastAPI, pytest, React, TypeScript, Vitest, Testing Library.

**Spec:** `docs/adr/0016-verification-trail-is-persisted-first-class.md` and GitHub issue #430.

## Global Constraints

- `verification_trail_json` is a nullable JSON sibling of `question_json`, never nested inside exportable question JSON.
- Completed runs persist their captured trail; `skip_verify`, failed, aborted, legacy-null, and missing-trail cases remain `null`.
- History list summaries stay unchanged; history detail exposes the trail field.
- The download endpoint continues to serialize question JSON plus request params only.
- Use the existing `VerificationTrailTimeline`; legacy `null` renders a localized “no trail recorded” state.
- Work directly in `feat/430-trail-persistence`, leave changes uncommitted, and do not fix unrelated staging lint errors.

---

### Task 1: Persistence model and completed-run capture

**Files:**
- Create: `tests/server/test_verification_trail_persistence.py`
- Modify: `server/models.py`
- Modify: `server/generate/persistence.py`
- Modify: `server/generate/service.py`
- Modify: `tests/server/test_verification_trail_stream.py` or the new persistence test file

**Interfaces:**
- `GenerationRecord.verification_trail_json: Mapped[list | None]` is nullable JSON.
- `persist_generation_record(..., verification_trail_json: list[dict] | None = None)` stores the supplied list and defaults to `None`.
- The internal result envelope may carry `verification_trail` for persistence; `_serialize_event` must continue emitting only its `event` and `data` fields.

- [ ] **Step 1: Write the failing persistence seam test**

```python
def test_completed_generation_persists_the_expected_verification_trail() -> None:
    expected_trail = [{"code": "verification_trail", "question_id": "q1", "passed": True}]
    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="math",
            params=GenerateParams(subject="math"),
            payload={"id": "q1"},
            verification_trail_json=expected_trail,
            session_factory=_make_factory(rows),
        )
    )
    assert rows[0].verification_trail_json == expected_trail
```

- [ ] **Step 2: Run the focused test and verify the expected missing-parameter/attribute failure**

Run: `uv run pytest tests/server/test_verification_trail_persistence.py::test_completed_generation_persists_the_expected_verification_trail -q`

Expected: FAIL because the persistence function/model has no trail field yet.

- [ ] **Step 3: Add the nullable ORM field and persistence parameter**

Add `verification_trail_json` immediately beside `question_json`; pass it into completed `GenerationRecord` construction and leave failed/aborted constructors at their `None` default.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `uv run pytest tests/server/test_verification_trail_persistence.py::test_completed_generation_persists_the_expected_verification_trail -q`

Expected: PASS.

- [ ] **Step 5: Add the failing skip/failed/aborted null tests**

Assert `record.verification_trail_json is None` for `skip_verify=True`, `persist_failed_generation_record`, and `persist_aborted_generation_record`; do not infer an empty list.

- [ ] **Step 6: Run those tests and verify they fail before the service capture is wired**

Run: `uv run pytest tests/server/test_verification_trail_persistence.py -q`

Expected: the newly added tests fail for the missing aborted import/explicit null behavior or missing field before their minimal implementation is completed.

- [ ] **Step 7: Add a failing stream-to-persistence test**

Use the existing fake subject seam and a typed `VerificationTrailEntry`; invoke `generate_question_stream` with `user_id` and an injected session factory, then assert the inserted completed row contains exactly `[entry.model_dump(mode="json")]`.

- [ ] **Step 8: Capture trail callbacks per worker and pass the list only through the internal result envelope**

The callback must append `entry.model_dump(mode="json")` and still call `make_trail_emitter`. The result envelope uses `verification_trail=trail_entries or None`; `generate_question_stream` passes that value to `persist_generation_record`. Do not add it to `event["data"]`.

- [ ] **Step 9: Run the persistence and stream tests**

Run: `uv run pytest tests/server/test_verification_trail_persistence.py tests/server/test_verification_trail_stream.py -q`

Expected: PASS, with skip-verify persisting `None`.

---

### Task 2: Alembic migration

**Files:**
- Create: `alembic/versions/b7c2e1f4a9d8_add_generation_record_verification_trail.py`
- Modify: `tests/server/test_generation_records_migration.py`

**Interfaces:**
- Revision: `b7c2e1f4a9d8`.
- Down revision: `f4b1e3c7a901`.
- Upgrade adds nullable `sa.JSON()` column `verification_trail_json` to `generation_records`; downgrade drops only that column.

- [ ] **Step 1: Add the failing migration assertions**

Extend the existing SQLite migration coverage to assert the column exists and is nullable after `upgrade head`, old rows contain `NULL`, and the column is absent after downgrade to `f4b1e3c7a901`.

- [ ] **Step 2: Run the migration test and verify it fails**

Run: `uv run pytest tests/server/test_generation_records_migration.py -q`

Expected: FAIL because the current Alembic head has no trail column/revision.

- [ ] **Step 3: Add the migration using the established batch-alter style**

Use `with op.batch_alter_table("generation_records") as batch_op: batch_op.add_column(sa.Column("verification_trail_json", sa.JSON(), nullable=True))` and drop the same column in `downgrade()`.

- [ ] **Step 4: Run the migration test and verify it passes**

Run: `uv run pytest tests/server/test_generation_records_migration.py -q`

Expected: PASS.

---

### Task 3: History detail and download contract

**Files:**
- Modify: `server/history/routes.py`
- Modify: `tests/server/test_history_routes.py`
- Modify: `web/src/api/client.ts`

**Interfaces:**
- Detail payload adds `verification_trail: list[VerificationTrailEntry] | null`.
- List payload does not add the trail.
- Download payload remains a copy of `question_json` with only `params_json` added.

- [ ] **Step 1: Add failing HTTP seam tests**

Seed a completed record with a known trail and assert `/api/history/{id}` returns the exact list; add a null-column assertion for skip/legacy records; add a download assertion that recursively checks no `verification_trail`, `trail`, or `correction_trail` key appears.

- [ ] **Step 2: Run the focused history tests and verify they fail**

Run: `uv run pytest tests/server/test_history_routes.py -q`

Expected: FAIL because detail omits `verification_trail` and the new exact assertion cannot find it.

- [ ] **Step 3: Add the trail field to detail only and leave download untouched**

Return `row.verification_trail_json` from `get_history_detail`; do not add it to `list_history` or `download_history`.

- [ ] **Step 4: Update the frontend API type and run backend history tests**

Run: `uv run pytest tests/server/test_history_routes.py -q`

Expected: PASS.

---

### Task 4: HistoryDetail timeline and legacy state

**Files:**
- Modify: `web/src/components/VerificationTrailTimeline.tsx`
- Modify: `web/src/components/QuestionCard.tsx`
- Modify: `web/src/pages/HistoryDetail.tsx`
- Modify: `web/src/i18n/messages.ts`
- Modify: `web/src/pages/HistoryDetail.test.tsx` and/or `web/src/pages/HistoryDetail.annotation.test.tsx`

**Interfaces:**
- `VerificationTrailTimeline` accepts `VerificationTrailEntry[] | null`; `null` renders its normal section heading plus localized no-trail copy, while `[]` retains the current no-render behavior for live runs with no entries.
- `QuestionCard.trail` accepts an optional nullable trail and passes it to the same timeline component.
- `HistoryDetail` passes `detail.verification_trail` to `QuestionCard`.

- [ ] **Step 1: Add failing frontend tests**

Add one test with a persisted entry that asserts the HistoryDetail card receives/displays the entry through the timeline, and one with `verification_trail: null` that asserts the localized “no trail recorded” copy and no broken empty timeline.

- [ ] **Step 2: Run the targeted Vitest file and verify it fails**

Run: `cd /workspace/exam-generation/web && npx vitest run src/pages/HistoryDetail.test.tsx`

Expected: FAIL because the API type/prop/render path has no persisted trail state.

- [ ] **Step 3: Add the localized no-trail key and nullable timeline path**

Use the existing English/Traditional Chinese message maps and keep the current live empty-array behavior unchanged.

- [ ] **Step 4: Pass the history field through QuestionCard to VerificationTrailTimeline**

Do not put trail data into `question_json`; only pass the separate detail field.

- [ ] **Step 5: Run targeted frontend tests and typecheck**

Run: `cd /workspace/exam-generation/web && npx vitest run src/pages/HistoryDetail.test.tsx src/pages/HistoryDetail.annotation.test.tsx && npx tsc -p tsconfig.app.json --noEmit`

Expected: PASS and exit code 0.

---

### Task 5: Full verification and handoff

**Files:**
- No additional source files; inspect all changes above.

- [ ] **Step 1: Run all requested backend tests**

Run: `uv run pytest tests/server -q`; if the pipeline files were touched, also run `uv run pytest tests -q`.

- [ ] **Step 2: Run all requested frontend tests and typecheck**

Run: `cd /workspace/exam-generation/web && npx vitest run src/pages/HistoryDetail.test.tsx src/pages/HistoryDetail.annotation.test.tsx && npx tsc -p tsconfig.app.json --noEmit`.

- [ ] **Step 3: Verify Alembic upgrade/downgrade/upgrade on a scratch SQLite database**

Run with a temporary `DATABASE_URL`: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`; report the exact revision transitions and exit status.

- [ ] **Step 4: Inspect status and diff without committing**

Run: `git status --short` and `git diff --check`; report every created/modified file, test command summary, migration revision, and any pre-existing failures without creating a commit.
