# Live Release Admission (Issue #778) Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task with review checkpoints.

**Goal:** Connect the independent generation gateway, browser release metadata, and backend build admission to one live, fail-closed release authority, with inventory/drain evidence and reproducible two-instance acceptance evidence.

**Architecture:** Extend the existing file-backed `admission.json` record rather than introduce another pause control. A `ReleaseController` reads and atomically writes that record, exposes the release-policy contract at `/release/policy.json`, tracks the current/prepared rollback/transition artifacts, and rejects target publication unless pending admissions are zero and supplied route/drain evidence is fresh, complete, and compatible. The gateway rereads the record for every public generation request; the backend's `LiveControllerAuthoritySource` rereads the controller endpoint for defense in depth; nginx proxies policy metadata to the gateway and leaves HTML/static cache semantics explicit.

**Tech Stack:** Python 3.11, Starlette, FastAPI, httpx, pytest, Ruff, TypeScript/Vitest, nginx configuration, JSON evidence fixtures.

**Spec:** `openspec/specs/generation-release-control/spec.md`; issue #778 acceptance criteria; `docs/research/2026-09-15-740-route-inventory.md`; `docs/research/2026-09-15-741-drain-rehearsal.md`; `docs/research/2026-09-15-770-release-detection.md`; `docs/research/2026-09-17-771-build-admission.md`.

## Global Constraints

- Preserve the already-merged #740/#741/#770/#771/#742 behavior and all existing public route exclusions.
- There is one pause/admission switch only: the controller record used by the gateway. Application restarts/rollbacks cannot create or reopen it.
- No positive release-policy cache: every gateway admission, policy response, and backend authority read rereads current state.
- Missing, malformed, stale, unreachable, nonzero, incomplete, or contradictory evidence fails closed.
- Never deploy or contact real environments; all controlled evidence uses local ASGI/HTTP fixtures.
- Keep generated `web/dist` out of the worktree after web verification.

## Task 1: Define and test the live policy/controller contract

**Files:** `gateway/state.py`, new `gateway/release_controller.py`, new `tests/gateway/test_release_controller.py`, new `tests/gateway/test_release_policy.py`.

- Add strict `exam-generation.release-policy/1` parsing/serialization with environment, monotonically increasing `release_revision`, nonempty `released_build_id`, `admission` (`open|paused|preparing`), `supported_recovery_formats`, and artifact/readiness metadata.
- Extend the existing admission state without breaking legacy state tests; malformed or missing policy data remains unavailable/paused.
- Add a controller seam for `read_policy`, `prepare_target`, `publish_target`, and `retire_artifact`. Publishing requires fresh positive drain snapshots for every inventory instance, zero controller pending admissions, complete route artifact/reader matches, and a strictly larger revision. Retirement requires explicit retirement evidence and never removes the current/prepared/transition records early.
- Test revision monotonicity, state persistence across a new controller instance, no-op/failed evidence, asset retention, and rollback/reopen independence.

## Task 2: Integrate gateway admission and the backend live adapter

**Files:** `gateway/app.py`, `gateway/__main__.py`, `server/generate/release_authority.py`, `server/config.py`, `server/app.py`, new/updated gateway and server tests.

- Add `LiveControllerAuthoritySource` (with the existing no-cache HTTP behavior) and select it for `RELEASE_AUTHORITY_URL`; validate the complete policy contract and optional expected environment.
- Add live `/release/policy.json` (and controller build metadata) routes backed by the same state record, with `Cache-Control: no-store`.
- Gate every exact GET/POST `/api/generate` route at the gateway before body forwarding/provider work; return 426 for missing/stale build and 503 for paused/preparing/unavailable authority. Track pending admission leases through forwarding so a target cannot switch during an admission decision/stream handoff.
- Keep existing streams and all read-only/non-generation routes untouched, including `/internal/*` privacy and control-token behavior.
- Test fresh reads, zero dispatch/provider work, policy transitions while pending, established streams, direct backend routes, and restart/rollback persistence.

## Task 3: Wire deployed proxies, Compose, configuration, and operations

**Files:** `web/nginx.conf`, `web/nginx.conf.template`, nginx/Vitest tests, `docker-compose.yml`, `DEPLOYMENT.md`, `scripts/release_control.py`, `scripts/admission_gate.py`, related tests.

- Route browser policy/build metadata through the gateway/controller in both nginx configurations; preserve no-store artifact headers, no-cache HTML headers, and immutable asset headers. Ensure `/api/`, `/auth/`, and `/health` continue to use the gateway.
- Set Compose/backend authority variables to the gateway policy endpoint and document controller environment/state-volume requirements, route inventory, rollback gate behavior, and evidence commands.
- Extend release-control operations with route/version inventory checks and controller transition commands that consume #741 drain evidence, including pending admissions; never reopen after failed evidence.
- Add tests for both proxy configs, Compose wiring, CLI failure modes, and route inventory coverage.

## Task 4: Produce controlled #778 evidence

**Files:** new `scripts/release_admission_rehearsal.py`, new `tests/release_control/test_release_admission_rehearsal.py`, `docs/research/2026-09-17-778-release-admission/README.md`, committed evidence output.

- Exercise two independent backend instances behind gateway surfaces and every route in the #740 inventory, including alternate/trailing generation paths and direct API paths.
- Record actual route/version responses and backend/provider dispatch counters for current acceptance, stale/missing 426, paused/unavailable 503, existing stream/read-only continuity, nginx header checks, and a pending-request transition.
- Make the script repeatable with local fixtures and emit machine-readable evidence plus a concise README explaining setup, command, timestamp/route inventory, and exact observed counts. Do not claim final A→B→A teacher-facing rollout.

## Task 5: Verification and handoff

- Run `uv run ruff check src/ server/ tests/` and include `gateway/` if CI lints it; run the full `uv run pytest -q`.
- In `web/`, run `npx tsc -b --noEmit`, `npm run lint`, `npm test`, and `npm run build`; remove generated `web/dist` afterward.
- Re-run the known batch-planner flake in isolation only if it is the sole full-suite failure, and report both results.
- Inspect `git diff`, ensure no scratch files outside the evidence directory, commit implementation commits with `feat(778): ` and the required co-author line, and leave the tree clean without pushing or opening a PR.
