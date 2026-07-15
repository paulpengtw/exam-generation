# Spec: Persist full LLM request/response logs per question (issue #113, P0)

## Why

The full LLM exchange (prompts, responses, tokens, model) is streamed live to `ProgressLog` and then lost. `GenerationLog` stores only `params_json`/`status`. Debugging generation failures or auditing prompt behavior post-completion is impossible.

## Decision

Store exchanges in a new DB table exactly as the issue proposes (no system-prompt dedup, no file logs), with a retention window because every generation call carries a ~93 KB curriculum system prompt.

## Design

### Data model (`server/models.py` + Alembic migration)

New table `llm_exchanges`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `generation_log_id` | UUID FK → `generation_logs.id`, indexed | |
| `exchange_order` | int | sequence of the call within the generation |
| `agent` | str(50) | `generator`, `sub_generator#3`, `verifier`, `corrector`, `html_designer`, `planner` |
| `purpose` | str(50) | the `purpose` string LLMClient already passes around |
| `request_body` | JSON | full messages array + system prompt + model params |
| `response_body` | JSON | full response content (text) + stop reason |
| `model_used` | str(100) | |
| `prompt_tokens` / `completion_tokens` | int nullable | from usage when available |
| `created_at` | datetime server default | |

### Capture path

`LLMClient` already emits `llm_request` / `llm_response` observer events with agent ids (including per-子題 `sub_generator#i` via `agent_override`). Add a **persistence observer** in `server/generate/service.py`: when the worker creates the observer chain for a generation, it also appends an exchange-recorder callback bound to the current `generation_log_id`. It buffers the `llm_request` event and writes one row when the matching `llm_response` (or error) event arrives. Writes are synchronous within the worker thread (its own sync session or `asyncio.run_coroutine_threadsafe` matching existing worker↔DB patterns) — generation latency impact is negligible relative to LLM calls.

CLI runs are unaffected (no observer registered, no DB dependency added to `src/`).

### API

`GET /api/generation-logs/{id}/exchanges` — auth-guarded, returns rows for a generation the user owns, ordered by `exchange_order`. Response mirrors table columns. No UI in this issue; the endpoint is the debugging surface (curl / future debug view).

### Retention

Env `LLM_EXCHANGE_RETENTION_DAYS` (default 30) on `ServerConfig`. On startup (after Alembic upgrade), delete rows older than the window. `0` disables persistence entirely.

## Error handling

- Persistence failures log a warning and never fail the generation.
- Response-without-request (or vice versa) writes a row with the missing side as `null`.

## Testing

- Unit: recorder observer converts a request+response event pair into one row (in-memory SQLite).
- Integration: a mocked generation via the service writes ≥1 exchange row FK'd to the generation log; verifier/corrector calls get distinct `agent` values.
- API: owner can list exchanges; other users get 404; ordering by `exchange_order`.
- Retention: rows older than the window are pruned at startup; `0` writes nothing.

## Out of scope

- UI to browse exchanges (pairs naturally with issue #30 history work later).
- System-prompt dedup/compression.
- Persisting image bytes (store the image path/filename only inside `request_body`).
