# Spec: Generation history — save + browse past questions per user (issue #30)

## Why

`generation_logs` records that a request happened, but the generated question JSON and images are not persisted per user. Users cannot revisit, re-download, or re-run past generations.

## Decision

Scope for v1: browse + detail view + JSON re-download + **regenerate** (pre-fills the Generate form from stored params — no silent re-submit, so users can tweak before spending tokens).

## Design

### Data model (Alembic migration)

New table `generation_records`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users, indexed | |
| `generation_log_id` | UUID FK → generation_logs, nullable | link to the run |
| `subject` | str(30) | math / social_studies / natural_sciences |
| `question_id` | str(100) | |
| `params_json` | JSON | the submitted `GenerateParams` (for regenerate) |
| `question_json` | JSON | full `ExamQuestion` dump incl. verification metadata |
| `image_files` | JSON | list of PNG filenames under `OUTPUT_DIR` (top-level + per-小題) |
| `created_at` | datetime | |

Images stay on disk in `OUTPUT_DIR` (they are already written there); records reference filenames. No base64 in the DB.

### Write path

`server/generate/service.py`: after a question completes successfully (post verify/correct, post render), insert one record per question inside the existing worker DB session pattern. Failures to record log a warning, never fail generation.

### API

- `GET /api/history?limit&offset&subject` — user's records, newest first: id, subject, question_id, created_at, a short preview (核心問題 or first 題目 line), verified flag.
- `GET /api/history/{id}` — full `question_json` + `params_json`, with `image_base64` embedded per existing detail-view conventions.
- `GET /api/history/{id}/download` — the question JSON as an attachment.
- Ownership enforced (404 for other users' records).

### Frontend

- New `/history` route + nav link on GeneratePage header.
- HistoryPage: paginated list (subject chip, preview, date, verified badge) → detail view reusing `QuestionCard` for rendering, with Download JSON.
- **Regenerate:** button on detail view navigates to `/generate/<subject>` with the stored params injected into the form state (router state or query prefill); the user reviews and clicks Generate themselves.

### Retention

Env `GENERATION_HISTORY_RETENTION_DAYS` (default 0 = keep forever); pruning at startup mirrors the #113 exchange pruning. Pruning deletes DB rows only; `OUTPUT_DIR` file cleanup stays manual (files may be shared with batch outputs).

## Error handling

Missing image files at detail time → render without images (no 500). Stored params referencing values later removed from schema CSVs → form prefill sets what it can and leaves the rest at defaults, with a notice.

## Testing

- pytest: record written on successful generation (mocked pipeline); list pagination + ownership; detail embeds images when files exist and degrades when missing; download content-disposition.
- Vitest: HistoryPage renders list from mocked API; regenerate navigation carries params into ParamForm state.

## Out of scope

Editing stored questions; sharing between users; ODT re-export from history (JSON only in v1; card rendering covers review needs); cross-user admin views.
