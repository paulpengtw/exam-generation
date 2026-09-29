## Why

Every staging frontend deploy produces a new build ID, and today a human must
hand-edit `GATEWAY_RELEASED_BUILD_ID` or run `prepare → publish → reopen`
before generation works again. This blocks generation after every merge to
staging, which happens continuously during active development.

## What Changes

- **New gateway endpoint** `POST /gateway/release/follow` in `gateway/app.py`:
  atomically advances `released_build_id` and `release_revision` in the
  controller when called with the deployed build ID. Enabled only when the
  gateway service has `GATEWAY_FOLLOW_FRONTEND=1`; otherwise returns 404.
- **New frontend container-start hook** `/docker-entrypoint.d/50-follow-release.sh`
  in the web image's nginx:alpine stage: reads `build_id` from
  `/usr/share/nginx/html/build-meta.json` and POSTs it to the gateway follow
  endpoint on every container start. Inert unless both `GATEWAY_FOLLOW_URL` and
  `GATEWAY_CONTROL_TOKEN` are set, so production and local compose are unaffected.
- **DEPLOYMENT.md addition**: a "Staging: gateway follows the frontend build"
  subsection with operator setup steps and the new variable table rows.
- **Tests**: gateway unit tests for the new follow endpoint; a shell script test
  covering the entrypoint hook behaviour.

## Capabilities

### New Capabilities

_(none — this change does not introduce a new top-level capability)_

### Modified Capabilities

- `generation-release-control`: A new "staging follow mode" permits advancing
  `released_build_id` without drain evidence or route evidence, carving out an
  explicit exception to the requirement that publication requires positive drain
  evidence and route verification. The requirement is narrowed (not removed) and
  the staging-only limitation is stated.

## Impact

- `gateway/app.py`: new route `/gateway/release/follow`; new handler reads
  `GATEWAY_FOLLOW_FRONTEND` from the environment.
- `gateway/release_controller.py`: new `follow_build` method on
  `ReleaseController` mirroring the artifact-bookkeeping in `publish_target`
  (L248–281) but skipping drain and route evidence; uses `_require_string` and
  existing validation helpers.
- `web/Dockerfile`: copy `50-follow-release.sh` into the nginx:alpine final
  stage under `/docker-entrypoint.d/`; verify that `curl` or `wget` and the
  ability to parse JSON (plain `sh`/`sed` or `jq`) are available without adding
  packages.
- `web/buildIdentity.ts` and `dist/build-meta.json`: no change needed — the
  hook reads the already-emitted file.
- New staging-only Railway variables on the gateway service:
  `GATEWAY_FOLLOW_FRONTEND=1`. New variables on the frontend service:
  `GATEWAY_CONTROL_TOKEN=${{gateway.GATEWAY_CONTROL_TOKEN}}` and
  `GATEWAY_FOLLOW_URL=http://gateway.railway.internal:8000/gateway/release/follow`.
- Related issues: replaces manual procedure of #891; related to #886, #887,
  #888, #889, #733, #778. Background:
  `docs/research/2026-09-29-release-build-id-automation.md`.
