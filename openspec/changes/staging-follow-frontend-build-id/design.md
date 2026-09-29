## Context

See proposal.md — Why for motivation.

The gateway already has a `_require_control_token` guard in `gateway/app.py` that
returns 404 when `control_token is None` and 403 on a token mismatch. The
`ReleaseController` in `gateway/release_controller.py` owns all state mutations:
`prepare_target` (L191–228) and `publish_target` (L230–281) show the artifact
bookkeeping pattern to mirror. `gateway/__main__.py` constructs the controller
with `environment` and wires it into `create_app`.

The frontend Dockerfile (`web/Dockerfile`) has two stages. The build stage
(`node:20-alpine`) runs Vite; the final stage (`nginx:alpine`) copies the built
`dist/` tree and the nginx config template. `web/buildIdentity.ts` emits
`dist/build-meta.json` (schema `exam-generation.build-meta/1`, field `build_id`)
into the dist directory at build time.

The nginx official entrypoint
(`https://github.com/nginx/docker-nginx/blob/master/entrypoint/docker-entrypoint.sh`)
runs every executable `*.sh` under `/docker-entrypoint.d/` synchronously under
`set -e` on every container start, then execs nginx. Scripts in that directory
MUST exit 0 on every code path or nginx will not start. `nginx:alpine` ships
`curl` (confirmed: the image includes `curl`). JSON parsing via plain `sh`/`sed`
(pattern `sed -n 's/.*"build_id": *"\([^"]*\)".*/\1/p'`) avoids a `jq`
dependency; if ambiguity arises about sed availability, falling back to `grep -oP`
or `awk` is the conservative choice.

## Goals / Non-Goals

**Goals:**
- After one-time operator setup, every staging frontend deploy automatically
  advances the gateway `released_build_id` with zero per-deploy manual steps.
- Production, local compose, and CI are completely unaffected (feature flag
  `GATEWAY_FOLLOW_FRONTEND=1` and env vars `GATEWAY_FOLLOW_URL` /
  `GATEWAY_CONTROL_TOKEN` must all be absent or unset for the old path).
- The follow endpoint is as narrow as possible: no new state machine states, no
  changes to admission logic, no new drain machinery.

**Non-Goals (explicitly excluded from this change):**
- The prepare → drain → publish → reopen cycle (the full design from
  `docs/research/2026-09-29-release-build-id-automation.md`). The research note
  recommended a background script that runs the full cycle; the user explicitly
  chose the narrower follow-endpoint approach instead. The full cycle remains
  the right path for production and is tracked separately.
- Maintenance pauses, Watch Paths, content-hash build IDs, Sentry reporting from
  shell, a gateway abort endpoint, production automation, or backend drain tokens.
- Any changes to admission state machine states (`open`, `paused`, `preparing`).

## Decisions

### Decision 1: Follow endpoint in `gateway/app.py`, controller method in `release_controller.py`

All state mutations go through `ReleaseController`; a `follow_build(build_id)`
method mirrors `publish_target` artifact bookkeeping (copying the current artifact
into `prepared_rollback`, building the new artifact from the supplied `build_id` and
the current `reader_version`/`release_revision + 1`). The app handler checks the
`follow_frontend` bool passed into `create_app` (see Decision 2).

**Alternative considered:** a simpler direct state write in the app handler,
bypassing `ReleaseController`. Rejected: `_write` enforces schema validation and
environment consistency; bypassing it risks writing an invalid record.

### Decision 2: Feature-flagged via a `follow_frontend: bool = False` parameter to `create_app`, read from env in `__main__.py`

`create_app` already receives `control_token`, `backend_url`, and
`release_controller` as keyword arguments from `gateway/__main__.py` — env vars are
read there, not inside `create_app`. The follow flag follows the same convention:
`__main__.py` reads `os.environ.get("GATEWAY_FOLLOW_FRONTEND", "") == "1"` and
passes `follow_frontend=True/False` to `create_app(...)`. Tests construct the app
with `follow_frontend=True` or `follow_frontend=False` directly, without needing to
patch `os.environ`. The route is always registered; if `follow_frontend` is `False`
the handler returns 404 (indistinguishable from the `_require_control_token` 404
pattern for other disabled endpoints).

**Alternative considered:** reading `os.environ` inside `create_app` at call time
(as originally drafted). Rejected: inconsistent with the existing `create_app`
convention and forces tests to monkeypatch the environment rather than passing a
parameter.

### Decision 3: Shell hook reads `build_id` with `sed`, calls `curl`, no new packages; no `set -e`

`nginx:alpine` ships `curl`. Plain POSIX `sed` extracts `build_id` from
`build-meta.json` without `jq`. The hook does NOT use `set -e`: the nginx entrypoint
runs hooks under its own `set -e`, so a non-zero exit from the hook would abort the
container before the script can reach `exit 0`. Instead, every command that can fail
is guarded with `|| …` and the script ends with an explicit `exit 0`. Retries use a
small inline loop (up to 3 attempts, `--max-time 8`, 2 s sleep between) rather than
`curl --retry`, so the `|| exit 0` semantics are preserved. Total elapsed time under
repeated failure ≤ ~26 s. On any failure the script logs and continues to `exit 0`.

**Assumption A**: `curl` is present in `nginx:alpine`. Verified against docker hub
image manifest for nginx:alpine; documented as assumption in case a digest pin in
the Dockerfile uses a divergent image.

**Assumption B**: `sed` in `nginx:alpine` supports the `s/…/…/p` pattern used for
JSON extraction. This is POSIX-compliant and present in BusyBox sed.

### Decision 4: `release_revision` increments by 1 on every follow call

The follow method sets `release_revision = current_revision + 1` and derives the
new artifact from the supplied `build_id` plus the current `reader_version` and
`supported_recovery_formats` (unchanged). This mirrors `publish_target`'s artifact
construction (`_target_artifact`, L234–242 in `release_controller.py`).

**Rollback behaviour (labelled assumption):** starting an older frontend image
re-posts the older build ID with a higher revision than the one that was there when
the older image was built. This is consistent with the policy — revision must
increase — but the older build ID is now tagged with a higher revision than it had
originally. This is inferred from the nginx entrypoint behaviour; Railway does not
document that container restarts rerun the entrypoint.

### Decision 5: 409 when `admission == "preparing"`

An operator-initiated `prepare_target` has set admission to `"preparing"`. The
follow endpoint must not clobber an in-progress manual release. Returning 409 (no
write) is the safest failure mode and matches the semantics used by `gateway_admission`
when it refuses to open while preparing.

## Risks / Trade-offs

**Race: hook fires before nginx serves the new bundle**
The hook fires synchronously before nginx starts (the nginx entrypoint runs hooks
first, then execs nginx). For a few seconds after the gateway records the new build
ID, new page loads can still be served the old bundle by the old container while the
gateway already expects the new build ID. Those page loads see `426 CLIENT_UPDATE_REQUIRED`
once; a reload fixes it. (Old tabs that loaded before the follow are unaffected by
this race — they will get `426` permanently by design once the gateway moves to the
new ID, which is the exact-build gate working correctly.) This race is accepted for
staging.

Mitigation: none needed on staging. Production does not use this mechanism.

**Rollback posts older build ID with higher revision (labelled assumption)**
If a rollback deploys an older image, the hook posts the older `build_id` again with
a revision higher than when that image was first deployed. The follow endpoint
accepts this (revision always increments). Old tabs that held the newer build ID see
`426` and must reload. This is the expected and safe behaviour.

Mitigation: labelled as an assumption derived from the nginx entrypoint, not
Railway-documented behaviour; stated in DEPLOYMENT.md.

**Internal Railway hostname reachability (open question)**
The hook uses `http://gateway.railway.internal:8000/gateway/release/follow`. It is
assumed that the running frontend container can reach `*.railway.internal` hostnames
and that the gateway's internal port is 8000 (consistent with `PORT=8000` per #886).
If the internal network is unavailable, the hook logs and exits 0 (nginx starts
regardless); the operator falls back to the public gateway URL as `GATEWAY_FOLLOW_URL`.

## Migration Plan

### One-time operator setup (staging only)

1. Deploy the code changes (gateway follow endpoint + frontend hook script).
2. On the Railway **staging gateway** service, add `GATEWAY_FOLLOW_FRONTEND=1`.
3. On the Railway **staging frontend** service, add:
   - `GATEWAY_CONTROL_TOKEN=${{gateway.GATEWAY_CONTROL_TOKEN}}` (Railway reference
     variable — single source of truth for the token)
   - `GATEWAY_FOLLOW_URL=http://gateway.railway.internal:8000/gateway/release/follow`
4. Trigger a staging frontend redeploy (or wait for the next merge).
5. Validate: `GET /release/policy.json` shows the new `released_build_id`, and a
   generation request is not blocked by `CLIENT_UPDATE_REQUIRED`.

After these five steps, every subsequent staging frontend deploy updates the gateway
automatically — zero per-deploy steps.

### Rollback

Remove `GATEWAY_FOLLOW_FRONTEND=1` from the gateway and the two vars from the
frontend. The follow endpoint reverts to 404; the hook is inert without its env
vars. No state mutation is needed.

## Open Questions

1. **Internal hostname reachability**: Does the Railway staging frontend container
   reach `gateway.railway.internal`? Fallback: use the public staging gateway URL
   as `GATEWAY_FOLLOW_URL` instead of the internal hostname. This does not affect
   the code; only the variable value changes.

2. **nginx:alpine curl TLS**: Does `curl` in `nginx:alpine` support the TLS
   certificate chain needed for a public HTTPS gateway URL? Relevant only if the
   fallback to the public URL is used. The internal URL (`http://`) bypasses TLS
   entirely.
