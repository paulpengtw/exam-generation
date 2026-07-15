# Spec: Per-request LLM plan/execute model selection (issue #105)

## Why

Models are fixed at server boot (`Config.model_plan` / `model_execute` env only). Users cannot trade cost vs quality per request, and comparing model behavior requires a redeploy.

## Decision

Env-driven allowlist visible to all users; two dropdowns (規劃模型 / 出題模型). No free-text overrides, no profiles.

## Design

### Backend

- `GenerateParams` (`server/generate/models.py`): add `model_plan: str | None = None`, `model_execute: str | None = None`; matching `Query` params on `GET /api/generate` in `server/generate/routes.py`.
- Validation: env `LLM_MODELS_ALLOWED` (comma-separated) on `ServerConfig`; unset ⇒ allowlist = the two configured defaults. A submitted model outside the allowlist → HTTP 422 before any upstream call. Validate in the route/Pydantic validator using the config allowlist.
- Threading: `service.generate_question_stream` → subject `generate_one` paths → `LLMClient.generate*(model=...)` (the client already accepts per-call `model`). `model_plan` also applies to `/api/plan-core-questions` (same request fields on `PlanCoreQuestionsRequest`).
- Discovery: `GET /api/models` → `{"allowed": [...], "defaults": {"plan": ..., "execute": ...}}`.

### Frontend

- `web/src/api/client.ts`: `getAvailableModels()`.
- `web/src/hooks/useGenerate.ts`: `model_plan?` / `model_execute?` in `GenerateParams` + `buildQueryString`.
- `web/src/components/ParamForm.tsx`: two `<select>`s populated from `/api/models`, defaulting to server defaults, persisted in localStorage; a "預設" option clears the override.
- `ProgressLog` already displays `request.model`, so the override is visible in the live trace with no changes.

## Error handling

- Unknown model → 422 with a `detail` naming the allowlist.
- `/api/models` failure in the UI → hide the dropdowns (fall back to defaults) rather than blocking the form.

## Testing

- pytest: override forwarded to `LLMClient` (fake client records model); allowlist rejection 422 with no upstream call; absent params = defaults (regression).
- Vitest: `buildQueryString` emits the params only when set; ParamForm renders options from a mocked `/api/models`.

## Out of scope

Third-party provider abstraction; per-子題 model overrides; cost accounting; image-model override; dynamic upstream discovery.
