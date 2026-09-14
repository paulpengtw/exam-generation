# Route inventory for the generation admission gateway (issue #740)

**Date:** 2026-09-15
**Author:** phwu@mail.naer.edu.tw

---

## Public entry-point inventory

| Entry point | Before #740 | After #740 |
|---|---|---|
| Frontend nginx `/api/`, `/auth/`, `/health` | Proxied to `BACKEND_HOST` (backend:8000 or Railway backend domain) | Proxied to `BACKEND_HOST` (now gateway:8000 or Railway gateway domain) |
| Compose `backend:8000` | Directly published on host port 8000 via `ports` | Internal only (`expose: ["8000"]`); no host port |
| Railway backend public domain | Receives all traffic from the frontend BACKEND_HOST | **Operator removes this after adding the gateway domain** (see DEPLOYMENT.md) |
| Gateway `:8000` | Did not exist | Receives all traffic; enforces admission on generation entry-points |

---

## Gated routes

Only requests that start a new generation job are blocked when paused:

| Method | Path | Rationale |
|---|---|---|
| `GET` | `/api/generate` | SSE generation stream (legacy tab and new protocol) |
| `GET` | `/api/generate/` | Trailing-slash alias |
| `POST` | `/api/generate` | Direct POST generation |
| `POST` | `/api/generate/` | Trailing-slash alias |

Classification is in `gateway/admission.py::is_generation_entry`.

---

## Explicitly non-gated routes (always proxied even when paused)

| Route | Rationale |
|---|---|
| `POST /api/generate/preview` | Resolver/confirmation preview — not a generation job, no SSE |
| `POST /api/generate/resolve` | Slot resolver — pure parameter completion, no generation |
| `POST /api/plan-core-questions` | Core-question planner — runs before generation, not a stream entry |
| `POST /api/generation-records/{id}/modifications` | 人工審題修正 correction stream — operates on an already-completed record, not a new generation |
| `GET /api/generation-logs/{id}/exchanges` | LLM exchange audit log — read-only |
| `GET /api/history*` | History and record reads — read-only |
| `GET/POST /auth/*` | Authentication — must remain available at all times |
| `GET /health` | Backend health probe — must remain available for infra monitoring |
| `GET /api/schemas` | Schema fetch — read-only reference data |

---

## Zero-dispatch evidence (tests)

The following test cases prove that a paused gateway never contacts the backend for generation requests:

| Test name | What it asserts |
|---|---|
| `test_a_fresh_state_dir_returns_503` | Fresh (no state file) → 503; `backend.requests_log` is empty |
| `test_b_multi_entry_rejection_while_paused` | Old-tab GET and direct POST both 503; zero backend generation requests |

Run command:

```
choom -n 500 -- uv run pytest tests/gateway/test_proxy.py::test_a_fresh_state_dir_returns_503 tests/gateway/test_proxy.py::test_b_multi_entry_rejection_while_paused -q
```

---

## Established-stream evidence

| Test name | What it asserts |
|---|---|
| `test_e_established_stream_survives_pause` | Open gate → start SSE stream → read `started` event → pause gate → new request is 503 → release backend → original stream delivers `result` and `done`; `generation_counter == 1` |

---

## Restart-survival evidence

| Test name | What it asserts |
|---|---|
| `test_f_restart_survival` | Pause → stop gateway → start new gateway on the same state dir → 503 with the same reason string |

---

## Limits

- Compose/Railway-level verification (confirming that the backend is genuinely unreachable from the public internet) requires `docker` or a Railway dashboard and was **not run** inside this sandbox.
- Drain evidence (confirming that in-flight streams complete before a deployment swap) is tracked in issue #741.
- The stream-version/426 upgrade is tracked in issue #742.
