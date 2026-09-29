# Automating the staging release build-ID step

**Date:** 2026-09-29
**Related issues:** #891, #886, #770, #778, #741, #733, #892

---

## TL;DR / Recommendation

Every staging frontend deploy currently requires a human to run
`prepare → publish` and re-open the gateway before generation works again.
The recommended fix is a **shell script placed in `/docker-entrypoint.d/` of the
frontend image** (option C1-entrypoint below): the official nginx Docker image
runs every executable `*.sh` in that directory on every container start —
confirmed from the nginx/docker-nginx entrypoint source.  The script
**backgrounds** the prepare→drain→publish→reopen work (`nohup … &`) so nginx
starts immediately and the Railway healthcheck (default 300 s timeout) is not
held hostage to a long drain.  The failure mode is narrower than the pre-deploy
variant (the image must have built and the container must have started) but
not fully absent: if the container starts, the background script publishes,
then nginx crashes, the gateway holds the new build ID while nothing serves
it.  This scenario requires the new container to have started and then failed,
which the Railway healthcheck catches and routes around — but there is a window.
Rollbacks re-run the entrypoint (inferred from the entrypoint source; not
Railway-documented behaviour).

**One-time human setup steps (done once; zero per-deploy manual steps after):**
1. Add `jq` and `curl` to the frontend Dockerfile final stage.
2. Add the script to the image via `COPY scripts/release_auto_publish.sh /docker-entrypoint.d/50-release-publish.sh` + `RUN chmod +x`.
3. Set `DRAIN_TELEMETRY_TOKEN` on the **staging backend** service (empty = drain endpoint disabled; `server/config.py` L77).
4. On the **staging frontend** service, add reference variables:
   `GATEWAY_CONTROL_TOKEN=${{gateway.GATEWAY_CONTROL_TOKEN}}` and
   `DRAIN_TELEMETRY_TOKEN=${{backend.DRAIN_TELEMETRY_TOKEN}}` plus
   `GATEWAY_INTERNAL_URL` and `BACKEND_INTERNAL_URL`.
5. Configure Watch Paths `/web/**` on the staging frontend service (Railway UI).
6. Validate on the next staging frontend deploy.

Watch Paths (§4 A) and a content-hash build ID (§4 B) are useful complements
that reduce how often the script runs; they do not remove the need for the
script.  Production should keep the manual prepare → publish → reopen flow.

---

## 1. Repo as it stands — prepare/publish requirements

### 1a. Build ID derivation

`web/buildIdentity.ts` computes the production build ID as:

```
sha256hex(RAILWAY_GIT_COMMIT_SHA + "\0" + JSON.stringify({
  VITE_ENVIRONMENT, VITE_IS_STAGING, VITE_SENTRY_DSN, VITE_SENTRY_RELEASE
}))
```

([`web/buildIdentity.ts` L54–L70](https://github.com/paulpengtw/exam-generation/blob/770a6d4/web/buildIdentity.ts#L54-L70))

`RAILWAY_GIT_COMMIT_SHA` changes on every push; the four `VITE_*` keys are
part of the bundle content.  Consequently **every merge to staging recomputes
the build ID**, regardless of whether `web/` changed.  `process.env.BUILD_ID`
is accepted as a verbatim override after a placeholder check (same file, L56–L65).

The Dockerfile build stage passes `RAILWAY_GIT_COMMIT_SHA` as a build ARG;
the final stage is `nginx:alpine`.  The Vite plugin emits
`dist/build-meta.json` (schema `exam-generation.build-meta/1`, field `build_id`)
and `dist/release/policy.json` (schema `exam-generation.release-policy/1`,
field `released_build_id`) into the image at build time.
([`web/Dockerfile`](https://github.com/paulpengtw/exam-generation/blob/770a6d4/web/Dockerfile))

### 1b. nginx proxying shadows the static files

`web/nginx.conf.template` proxies both `/release/policy.json` and
`/build-meta.json` to `$backend` (the `BACKEND_HOST`, now the gateway), adding
`Cache-Control: no-store`.
([`web/nginx.conf.template` L32–L43](https://github.com/paulpengtw/exam-generation/blob/770a6d4/web/nginx.conf.template#L32-L43))

The Vite-emitted static copies in `/usr/share/nginx/html/` are therefore
**shadowed**: any request through nginx for those paths reaches the gateway,
not the static file.  This is intentional — the gateway is the live authority —
but it creates the circular dependency described in §1f.

### 1c. Gateway `__main__.py` — GATEWAY_RELEASED_BUILD_ID is first-boot only

`gateway/__main__.py` reads `GATEWAY_RELEASED_BUILD_ID` and calls
`controller.initialize(...)` **only when `admission.json` does not exist**.
([`gateway/__main__.py` L26–L40](https://github.com/paulpengtw/exam-generation/blob/770a6d4/gateway/__main__.py#L26-L40))

Once the volume has a valid record, this env-var path is permanently bypassed.
The environment variable is therefore useless as an ongoing mechanism.

### 1d. What prepare requires

`release_controller.prepare_target` accepts:
- `build_id` (str, nonempty)
- `release_revision` (int, must be **strictly greater** than the current revision)
- `reader_version` (str)
- `supported_recovery_formats` (list of str)

No external evidence is needed for prepare.  Admission moves to `"preparing"`;
new generation requests get `503`.
([`gateway/release_controller.py` L161–L208](https://github.com/paulpengtw/exam-generation/blob/770a6d4/gateway/release_controller.py#L161-L208))

### 1e. What publish requires

`release_controller.publish_target` requires all of:

1. **`pending_admissions == 0`**: the gateway's in-flight counter must be zero.
   ([`gateway/release_controller.py` L416–L420](https://github.com/paulpengtw/exam-generation/blob/770a6d4/gateway/release_controller.py#L416-L420))

2. **Drain evidence**: non-empty list of snapshots, one per backend instance,
   all captured within `max_drain_age_seconds` (default 15 s), all six counters
   zero, `quiescent: true`, no integrity errors, and no duplicate instance IDs.
   The snapshots come from `GET /internal/drain` on each backend.
   ([`gateway/release_controller.py` L422–L449](https://github.com/paulpengtw/exam-generation/blob/770a6d4/gateway/release_controller.py#L422-L449))

3. **Route evidence**: at least one route record, matching
   `expected_routes` exactly, and **every route's `build_id` /
   `release_revision` / `reader_version` must equal the prepared target's**.
   The script reads these fields from `released_build_id` etc. at each route's
   `policy_url`.
   ([`gateway/release_controller.py` L400–L413](https://github.com/paulpengtw/exam-generation/blob/770a6d4/gateway/release_controller.py#L400-L413))

**Publish leaves admission `"paused"`.** The code at L271 sets `"admission":
"paused"` unconditionally, with the comment: "Publishing never opens admission.
The operator must use the same persistent gate after a later positive readiness
check."  Reopening is a separate, explicit step.
([`gateway/release_controller.py` L248–L280](https://github.com/paulpengtw/exam-generation/blob/770a6d4/gateway/release_controller.py#L248-L280))

### 1f. Circular dependency for frontend updates

The inventory routes (per `DEPLOYMENT.md` L441–L443) are:
- `"frontend"` → `https://<frontend-domain>/release/policy.json` (proxied by
  nginx to the gateway)
- `"gateway"` → `https://<gateway-domain>/release/policy.json`

Both resolve through the gateway.  During `preparing` state the gateway's
`released_build_id` is still the **old** value; only after `publish` does it
update.  So the route evidence from these URLs reports the old build ID, not
the prepared target's new build ID, and `publish` via the standard script will
**always fail** for a frontend update until either:
- A non-proxied path serves the static policy file, or
- The evidence body is constructed by the caller without reading live URLs.

This is the core operational problem.

### 1g. Why exact-build enforcement exists

From the issue #733 resolution (closing comment, 2026-09-14):

> **Q1 resolution**: old tabs must update before starting new generation.

The 426 `CLIENT_UPDATE_REQUIRED` exists so a browser tab running an old bundle
cannot submit to a backend that has moved to a new (incompatible) contract.
Drain-before-switch prevents an already-admitted stream from seeing a mid-flight
policy change.

---

## 2. Railway mechanisms (primary-source verified)

All claims below are from Railway documentation unless marked "(inferred)".

### 2a. Watch Paths

Gitignore-style patterns that restrict which file-path changes trigger a
service redeploy.  Setting `/web/**` on the frontend service would prevent
backend-only or docs-only commits from rebuilding the frontend — reducing how
often the build ID changes, but not eliminating the per-deploy step.
([Railway docs — Deploying a Monorepo](https://docs.railway.com/deployments/monorepo))

### 2b. Pre-deploy command

Runs **between build and deploy**, in the application's own Docker image, inside
Railway's private network.  Has full access to environment variables.
Volumes are NOT mounted.
([Railway docs — Pre-Deploy Command](https://docs.railway.com/guides/pre-deploy-command))

Quote: "execute[s] within your private network" — so `railway.internal`
hostnames (gateway, backend) are reachable.  The image's filesystem (including
Vite-emitted `dist/build-meta.json`) is readable.

The Railway pre-deploy page does **not** state whether pre-deploy runs on
rollbacks, restarts, or re-deploys triggered by other means.  This is unverified.

### 2c. RAILWAY_GIT_COMMIT_SHA

Injected as a build ARG (available at `docker build` time) **and** as a runtime
environment variable.  Available "when the deploy originated from a GitHub
trigger."
([Railway docs — Variables Reference](https://docs.railway.com/reference/variables))

### 2d. Reference variables / cross-service variables

Syntax: `${{ServiceName.VAR}}`.  Railway evaluates these at deploy time from
whatever value the variable currently holds in the source service.  **A
reference variable reflects a static variable value configured by the operator,
not a build-time-computed value.**  There is no Railway mechanism for a build
process to set its own service variable, so a computed build ID cannot be
propagated from the frontend service to the gateway service via reference
variables.

For secrets that must be shared across services (§4 C1), use
`${{gateway.GATEWAY_CONTROL_TOKEN}}` and `${{backend.DRAIN_TELEMETRY_TOKEN}}`
on the frontend service.  This keeps a single source of truth: the value is
defined on the owning service and referenced elsewhere.
([Railway docs — Variables Reference](https://docs.railway.com/reference/variables))

### 2e. Railway public GraphQL API

`variableUpsert` and `variableCollectionUpsert` mutations can set service
variables; both support `skipDeploys`.  Authentication requires a project token
(`Project-Access-Token` header) or account/workspace token.  This could be
called from a post-deploy script or GitHub Actions to write the new build ID as a
Railway variable — but this is useful only for informational purposes (dashboards,
cross-service reference) because overwriting `GATEWAY_RELEASED_BUILD_ID` would
not affect the gateway's live policy once the volume has an `admission.json`.
([Railway docs — Manage Variables with the Public API](https://docs.railway.com/integrations/api/manage-variables))

### 2f. Railway webhooks

Railway sends a JSON payload to a configured webhook URL when a deployment
status changes.  The payload includes deployment ID, service, environment, commit
data, and status.  Success events are supported; the exact state names are in the
Railway Deployments reference.
([Railway docs — Webhooks](https://docs.railway.com/observability/webhooks))

### 2g. GitHub deployment_status integration

"Railway makes the deployment status available to GitHub."  A `.github/workflows/`
file can trigger on `deployment_status` with:

```yaml
on:
  deployment_status:
    states: [success]
jobs:
  post-deploy:
    if: github.event.deployment_status.state == 'success'
    # filter by github.event.deployment.environment == 'production' to target one env
```

([Railway docs — GitHub Actions Post-Deploy](https://docs.railway.com/guides/github-actions-post-deploy))

**Limitation**: GitHub Actions runners run on GitHub's infrastructure, not inside
Railway's private network.  They cannot reach `backend.railway.internal` for
drain evidence.  The drain endpoint is internal-only by design (gateway blocks
`/internal/*`).

### 2h. "Wait for CI"

Railway can hold a deployment in `WAITING` state until all GitHub Actions check
suites on the commit complete.  Two-hour timeout; a failed workflow skips the
deploy.  This goes in the **other** direction: it pauses Railway until GitHub
Actions finishes, not the other way around.
([Railway docs — Controlling GitHub Autodeploys](https://docs.railway.com/deployments/github-autodeploys))

### 2i. nginx `docker-entrypoint.d` — runs on every container start

The official nginx Docker image entrypoint (source:
[nginx/docker-nginx entrypoint on GitHub](https://github.com/nginx/docker-nginx/blob/master/entrypoint/docker-entrypoint.sh))
searches `/docker-entrypoint.d/`, sources `.envsh` files, and executes `.sh`
files (if executable) in sorted order, then `exec`s nginx.  **There is no
condition that limits this to the first start only**: the script runs on every
container launch, including restarts, rollbacks to an earlier image, and
Railway-triggered re-deploys.  The entrypoint uses `set -e`; a non-zero exit
from any script in that directory prevents nginx from starting, which causes the
Railway health check to fail.

---

## 3. GitHub Actions triggers (primary-source verified)

`deployment_status` fires "when a third party provides a deployment status."
`GITHUB_SHA` is the commit to be deployed; `GITHUB_REF` is branch or tag.
An `inactive` state does not fire the trigger.
([GitHub Actions docs — Events that trigger workflows, `deployment_status`](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#deployment_status))

---

## 4. Candidate designs

### A. Railway Watch Paths on `web/**` (reduces frequency, does not remove the step)

Configure Watch Paths on the staging frontend service to `/web/**`.  Merges that
touch only `docs/`, `server/`, `gateway/`, etc. would not trigger a frontend
redeploy and therefore would not change the build ID.

**Guarantees kept:** identical.  **Weakening:** none.
**Limitation:** any change to `web/` still produces a new build ID and requires
the automated script to run.  This is a complement, not a solution.

### B. Content-hash build ID from `web/` content (reduces frequency, does not remove the step)

In the Dockerfile build stage, compute a hash over `web/` source files (before
`npm run build`) and pass it as `BUILD_ID`.  Commits that don't change `web/`
content would produce the same build ID and the gateway would still accept them.

**Guarantees kept:** identical.
**Limitation:** `VITE_*` config changes are not in the `web/` file hash; a
config change would change the ID anyway.  Combined with Watch Paths, this
covers the majority of routine non-web merges.  Still requires the automated
script whenever the hash changes.

### C1. Script at container start via `/docker-entrypoint.d/` (recommended for staging)

**How it works:**

Place an executable shell script at
`/docker-entrypoint.d/50-release-publish.sh` in the frontend image.  The nginx
entrypoint (§2i) runs it synchronously before `exec`'ing nginx.  **The script
must background the slow work immediately** so that nginx starts without delay
and Railway's healthcheck (default 300 s) is not blocked.  The
`prepare → drain → publish → reopen` sequence is launched as:

```sh
nohup /bin/sh /etc/nginx/release_work.sh >>/var/log/release_publish.log 2>&1 &
```

The entrypoint script exits 0 after launching the background job; nginx starts;
Railway health-checks the HTTP port; traffic routes to the new container.  The
background job completes asynchronously.

**Entrypoint script steps (synchronous, fast):**

1. Read `NEW_BUILD_ID` from `/usr/share/nginx/html/build-meta.json` using `jq`.
2. GET `http://gateway.railway.internal:8000/release/policy.json` to read
   `CURRENT_RELEASED_BUILD_ID`, `CURRENT_ADMISSION`, `CURRENT_REVISION`, and
   `CURRENT_PREPARATION_SOURCE` (`preparation.target.source` if present).
3. **Admission-state guard (operator-pause protection):**
   - If `CURRENT_ADMISSION == "open"` and `NEW_BUILD_ID != CURRENT_RELEASED_BUILD_ID`:
     proceed (launch background job).
   - If `CURRENT_ADMISSION == "preparing"`:
     - If `CURRENT_PREPARATION_SOURCE` starts with `"auto:deploy:"` and
       `preparation.target.build_id != NEW_BUILD_ID`: an older automated run is in
       progress (superseded — see below).  Log
       `"superseding stale automated prepare"` and proceed (launch background job,
       which will re-prepare with a higher revision).
     - Otherwise (source absent, or source does not start with `"auto:deploy:"`,
       or target build_id already matches `NEW_BUILD_ID`): an operator is mid-prepare
       or this container's build is already targeted.  Log
       `"gate in preparing state set by operator or already current; not overriding"`
       and exit 0.
   - If `CURRENT_ADMISSION == "paused"` and `NEW_BUILD_ID != CURRENT_RELEASED_BUILD_ID`:
     the gate was deliberately paused by an operator.  Log
     `"gate is paused by operator; not overriding"` and exit 0.
4. If `NEW_BUILD_ID == CURRENT_RELEASED_BUILD_ID`: log `"build_id already current"`
   and exit 0 (idempotent).
5. Launch the background work script (`nohup … &`), log the PID, and exit 0.

**Background work script steps (asynchronous):**

The `source` marker is embedded in the prepare call's target object so that a
newer run can distinguish an automated preparation from an operator one.
`gateway/app.py`'s `gateway_prepare` handler reads `body.get("target")` and
passes it verbatim to `release_controller.prepare_target`.
`release_controller._normalise_target` does `target = deepcopy(raw)` before
updating known fields, so extra keys in `raw_target` are preserved in the stored
`preparation.target` record.
([`gateway/app.py` L218–L232](https://github.com/paulpengtw/exam-generation/blob/770a6d4/gateway/app.py#L218-L232),
[`gateway/release_controller.py` L326–L358](https://github.com/paulpengtw/exam-generation/blob/770a6d4/gateway/release_controller.py#L326-L358))

1. POST `/gateway/release/prepare` with target
   `{build_id: NEW_BUILD_ID, release_revision: CURRENT_REVISION+1, reader_version: ...,
   source: "auto:deploy:NEW_BUILD_ID"}`.  The `source` field is preserved verbatim
   in `preparation.target` so subsequent runs can detect it.
2. Poll `/internal/drain` on each backend until `quiescent: true` or a total
   timeout (~600 s).  During this period `admission == "preparing"` and new
   generation requests receive `503 SERVICE_PAUSED` — this is the intended
   maintenance behaviour; new tabs loading the new bundle see the paused state
   until publish completes.
3. Before publishing, re-read the current policy.  If `preparation.target.build_id`
   no longer matches `NEW_BUILD_ID` (a newer container has re-prepared), log
   `"superseded by newer prepare; exiting without publish"` and exit.  This prevents
   the old background run from clobbering a newer one.
4. Construct route evidence manually —
   `[{name:"frontend", build_id: NEW_BUILD_ID, ...}, {name:"gateway", ...same...}]`
   — and POST `/gateway/release/publish` with drain snapshots +
   constructed routes + `pending_admissions: 0`.
5. POST `/gateway/admission {state: "open"}` (staging-only auto-reopen, justified
   because step 3 of the entrypoint script confirmed admission was `"open"` before
   the cycle began).
6. Log success to stdout (visible in Railway deploy logs).  If `SENTRY_DSN` is set,
   report any failure via a Sentry capture.  (Sentry integration in background
   scripts is an open question; see §6.)

**Dockerfile changes required:**

```dockerfile
FROM nginx:alpine
RUN apk add --no-cache jq curl
COPY web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
COPY scripts/release_auto_publish.sh /docker-entrypoint.d/50-release-publish.sh
RUN chmod +x /docker-entrypoint.d/50-release-publish.sh
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

The build context is the repo root; `scripts/release_auto_publish.sh` is
`COPY`'d to the entrypoint directory directly.  The Railway pre-deploy command
setting in the Railway UI is **not needed** — the hook is baked into the image.

**Environment variables required on the staging frontend service:**
- `GATEWAY_CONTROL_TOKEN=${{gateway.GATEWAY_CONTROL_TOKEN}}` (reference variable — §2d)
- `DRAIN_TELEMETRY_TOKEN=${{backend.DRAIN_TELEMETRY_TOKEN}}` (reference variable — §2d)
- `GATEWAY_INTERNAL_URL=http://gateway.railway.internal:8000`
- `BACKEND_INTERNAL_URL=http://backend.railway.internal:8000`

Using Railway reference variables (§2d) keeps a single source of truth: the
value lives on the owning service (gateway or backend) and is not duplicated.

**One-time pre-setup step:** Set `DRAIN_TELEMETRY_TOKEN` on the **staging
backend** service if not already set.  `server/config.py` L77:
`drain_telemetry_token: str = ""  # DRAIN_TELEMETRY_TOKEN; empty = endpoint disabled`.
An empty value returns 404 from the drain endpoint, which the script treats as a
failure.

**Healthcheck:**
Railway's healthcheck docs state: "the healthcheck is only called at the start of
the deployment, to ensure it is healthy prior to routing traffic to it" and
"Only then will the new deployment be made active and the previous deployment
inactive."  The default timeout is 300 s.
([Railway docs — Healthchecks](https://docs.railway.com/reference/healthchecks))
A healthcheck path on the frontend (e.g. `GET /`) should be set in Railway's
service settings so Railway knows when nginx is ready.  Without one, when traffic
switches to the new container is "not stated" in the docs.  This is a one-time
operator setting.

**Guarantees kept:**
- Old tabs still get 426 once the background script publishes the new build ID.
- Drain is verified before publish (real HTTP evidence from each backend instance).
- `admission` is in `"preparing"` from prepare through publish; no generation
  passes during the transition.  New tabs loaded during this window see
  `503 SERVICE_PAUSED`, which is the intended maintenance behaviour.
- Deliberate operator pauses are preserved: the entrypoint script exits without
  launching the background job when it detects a non-automated, non-`"open"`
  admission state (step 3).
- Superseded automated preparations are handled: a newer container's background
  job re-prepares with a higher revision and the older job detects it was
  superseded before publishing (background step 3).

**Guarantee weakened (stated explicitly):**
- *Route metadata is self-asserted, not externally verified.*  Background step 4
  constructs route evidence from the known new build ID without reading it from a
  live serving URL.  Acceptable for staging where the script is the only automated
  caller of the publish endpoint.

**Race window (old-container overlap):**
Background publish → nginx already running → old Railway container eventually
shut down (after healthcheck passes on the new one and Railway routes traffic).
Between publish and old-container teardown the gateway has `released_build_id =
NEW` but the old container is still serving `X-Frontend-Build-ID: OLD`.  Those
requests get 426 (correct behaviour: old build = must reload).  The window is
bounded by Railway's container replacement latency.

**Failure mode — publish succeeds, nginx crashes afterward:**
The entrypoint script backs up and exits 0; nginx starts; the background script
publishes.  If nginx then crashes (after the background job has published), the
gateway holds `released_build_id = NEW` while no container serves the new build.
All clients get 426.  This is a narrower window than the pre-deploy variant
(requires container start + nginx crash after publish), but it is not absent.

*Mitigation:* Railway's healthcheck will mark the container unhealthy if nginx
exits, and Railway will keep or restore the old container.  An operator can
re-deploy the old image (inferred from the entrypoint source: the old image's
container start re-runs the entrypoint and re-publishes the old build ID; this is
not Railway-documented behaviour) or run prepare+publish manually with the old
build ID.

**Gateway redeploy:**
The volume persists across gateway redeploys.  A gateway redeploy does not
change `admission.json`.  No action needed.

**First boot (empty volume):**
On first boot `GATEWAY_RELEASED_BUILD_ID` initialises `admission.json` via
`controller.initialize()` (`gateway/__main__.py` L26–L40).  After that the
entrypoint script takes over on every subsequent deploy.  `GATEWAY_RELEASED_BUILD_ID`
can remain set as a bootstrap fallback.

### C1-pre-deploy variant: Railway pre-deploy command (weaker, listed for comparison)

The same work can be configured as a Railway pre-deploy command instead of the
entrypoint hook.  Railway runs it "between building and deploying," inside the
private network (§2b), with env vars available.  Because it runs synchronously
before the deploy, the same drain-blocking concern applies; a long drain would
block the deploy past Railway's pre-deploy timeout (not documented; inferred to be
shorter than the 300 s healthcheck window).

**Compared to entrypoint on every key axis:**

| Axis | Pre-deploy | Entrypoint (`/docker-entrypoint.d/`) |
|---|---|---|
| Runs on rollbacks | Not documented; unverified (§6) | Inferred from entrypoint source: runs on every container start (§2i) |
| Publish-then-failed-deploy | **Present**: if pre-deploy publishes and deploy fails, gateway has new build ID, nothing serves it; clients get 426 | **Narrower but present**: publish happens in a background process after nginx starts; if nginx then crashes, same outcome |
| Script fails → deploy blocked | Yes: non-zero pre-deploy exit blocks deploy; old container keeps running | Yes: if entrypoint script exits non-zero (e.g. gateway unreachable), nginx never starts; container fails healthcheck; Railway keeps old container |
| Drain blocks deploy | Yes: synchronous drain blocks pre-deploy; long drain → timeout | No: drain runs in background; nginx starts immediately |
| Old-container overlap window | Same: brief window between publish and old-container teardown | Same |
| Configured in | Railway UI (one-time operator action) | Dockerfile (code-reviewed, version-controlled) |

**Verdict:** the entrypoint approach is better on rollback coverage (inferred vs
unverified) and avoids the drain-blocking problem.  The failure mode is narrower
but not eliminated in either approach.  Recommend entrypoint.

### C2. GitHub Actions on `deployment_status` (not recommended for this use case)

A post-deploy workflow triggers on Railway's `deployment_status` events (Railway
creates these; see §2g).  It can reach the public gateway URL for prepare/publish
calls but **cannot reach `backend.railway.internal` for drain evidence**.  The
drain endpoint is internal-only by design.  To make this work, drain evidence
would have to be either:
- skipped (requires controller code change to allow empty drain_snapshots), or
- obtained via a publicly exposed drain endpoint (security risk).

Without these, publish via the controller's current validation fails.  This
approach is not viable without additional code changes.

### C3. Dedicated webhook receiver service (viable but more infrastructure)

Deploy a small Python/shell service inside Railway that receives Railway webhook
events (§2f), then runs the same prepare+publish logic from §C1.  Has network
access to internal endpoints.  Adds a new service, Docker image, and Railway
config overhead.  The entrypoint approach achieves the same result with less
infrastructure.

### D. Gateway "follow-latest" mode (viable, requires gateway code change)

Add a non-proxied nginx path to the frontend service that serves the
Vite-emitted static `dist/release/policy.json` directly (bypassing the proxy to
the gateway):

```nginx
location = /_internal/release-policy.json {
    alias /usr/share/nginx/html/release/policy.json;
    add_header Cache-Control 'no-store' always;
}
```

Configure the inventory's route `policy_url` to `/_internal/release-policy.json`.
After the frontend deploys, this path serves the **new** build ID from the static
file.  The standard `release_control.py publish` can then read the correct
metadata from the route URL, resolving the circular dependency without
self-asserted evidence.

A stronger variant: add a `GATEWAY_FOLLOW_LATEST=1` mode where the gateway
startup script reads the frontend's build ID from this path via
`frontend.railway.internal`, then auto-prepare + auto-publish.

**Guarantees kept (with the nginx-path-only variant):**
- Route evidence is externally verified (the script reads it from the live URL).
- Drain evidence still required.

**Requires:** code change to `web/nginx.conf.template` and gateway code change
for the auto-publish variant.

### E. Railway reference variables or shared variables (not viable for build ID propagation)

`${{frontend.BUILD_ID}}` works only if the frontend service has a Railway
variable `BUILD_ID` set by an operator.  Railway has no mechanism for a Docker
build to write back its computed output as a service variable.  Even if the
operator pre-sets `BUILD_ID` before each deploy, that is the same manual step.
Reference variables cannot carry build-time-computed values automatically.
([Railway docs — Variables Reference](https://docs.railway.com/reference/variables))

---

## 5. Recommendation

**For staging:** implement option C1 entrypoint.  It requires zero per-deploy
human steps once set up, uses Railway's private network for genuine drain
evidence, handles rollbacks (confirmed via nginx entrypoint behaviour, §2i),
and does not have the publish-then-failed-deploy window of the pre-deploy
variant.  The only weakening — self-asserted route evidence — is explicitly
acceptable for staging.

Combine with option A (Watch Paths `/web/**`) so non-frontend merges do not
trigger a frontend redeploy at all.  Option B (content-hash build ID) is an
optional further refinement.

**For production:** keep the manual prepare → publish → reopen flow.  The
exact-build gate's guarantee exists specifically so an operator can decide when
the new build is safe to release (drain complete, routes verified externally,
gate opened deliberately).  The self-asserted route evidence of C1 is not
appropriate where a human approval step is the intent.  Option D's nginx-path
variant would also work for production if external route verification is desired
while still removing the manual Railway variable edit.

**Ordered one-time setup steps (all human; zero per-deploy steps after):**

1. **Add `jq` + `curl` to the frontend Dockerfile final stage.**
   `RUN apk add --no-cache jq curl`

2. **Write `scripts/release_auto_publish.sh`** (~60–80 lines of POSIX `sh`):
   read build ID from `/usr/share/nginx/html/build-meta.json`, check admission
   state (exit 0 if paused/preparing), check idempotency, poll drain, prepare,
   re-poll drain, publish, reopen.

3. **Add to the frontend Dockerfile:**
   ```dockerfile
   COPY scripts/release_auto_publish.sh /docker-entrypoint.d/50-release-publish.sh
   RUN chmod +x /docker-entrypoint.d/50-release-publish.sh
   ```

4. **Set `DRAIN_TELEMETRY_TOKEN` on the staging backend service** (if not already
   set; `server/config.py` L77 — empty = drain endpoint disabled).

5. **On the staging frontend service, add variables:**
   - `GATEWAY_CONTROL_TOKEN=${{gateway.GATEWAY_CONTROL_TOKEN}}`
   - `DRAIN_TELEMETRY_TOKEN=${{backend.DRAIN_TELEMETRY_TOKEN}}`
   - `GATEWAY_INTERNAL_URL=http://gateway.railway.internal:8000`
   - `BACKEND_INTERNAL_URL=http://backend.railway.internal:8000`

6. **Configure Watch Paths** on the staging frontend service to `/web/**`
   (Railway UI → Service settings → Watch Paths).

7. **Validate** on the next staging frontend deploy: check that `released_build_id`
   advances and a generation request reaches `/api/generate` without 426.
   This closes #891 acceptance criteria.

---

## 6. Open questions

- **Private networking from inside a running container — not explicitly documented
  for all service types.** The Railway pre-deploy page says commands "execute[s]
  within your private network."  The entrypoint approach depends on the same
  claim: scripts running inside an nginx:alpine container must be able to reach
  `gateway.railway.internal` and `backend.railway.internal`.  Neither the
  pre-deploy page nor a Railway networking reference explicitly confirms
  `*.railway.internal` hostname resolution from within a running container.
  *Conservative fallback*: use the public gateway URL instead of the internal
  one for control-plane calls; this requires the control token to be transmitted
  over the public internet (acceptable since it is already a secret env var).

- **Whether pre-deploy runs on rollbacks.** The Railway pre-deploy page does not
  state whether the pre-deploy command runs when a deployment is triggered by a
  rollback, a restart, or a re-deploy.  Not verified from a primary source.  The
  entrypoint approach avoids this uncertainty: the nginx entrypoint is confirmed
  to run on every container start (§2i).

- **Background failure visibility.** The background work script runs detached from
  the Railway deploy pipeline.  A failure (drain timeout, gateway unreachable,
  publish rejected) produces log lines in Railway's deploy log but does not fail
  the deploy or alert anyone.  The script should log with a distinctive prefix
  (`[release-publish]`) and, if `SENTRY_DSN` is available, send a capture on
  error.  Whether a bare `curl` Sentry POST or a lightweight wrapper is acceptable
  in a BusyBox/alpine shell, and what Sentry project to target, is not decided.

- **Drain endpoint with multiple Railway instances.** On staging there is
  currently one backend instance.  If Railway's horizontal scaling is enabled,
  the script needs to know all instance IDs.  For an automated flow, the
  inventory would need to be dynamically discovered or the controller's coverage
  check satisfied by a single instance.  Not investigated (out of scope for
  single-instance staging).

- **Gateway Railway-internal port.** The gateway listens on the port set by
  `PORT` (default 8000 per `gateway/__main__.py`).  On Railway this is confirmed
  as `PORT=8000` (per issue #886 comment).  The internal hostname format
  (`gateway.railway.internal:8000`) is inferred from Railway naming conventions;
  the exact internal port was not read from a primary source.

- **Release_revision overflow.** The controller requires a strictly increasing
  integer.  With automated deploys (potentially many per day), this poses no
  practical issue (integers), but a rollback scenario where the revision must
  advance past a forward deploy is handled correctly by reading the current
  revision from the gateway before incrementing.  Verified in code; not
  tested in production.

- **Whether the GitHub deployment event `environment` field matches the Railway
  environment name.** Railway creates deployment_status events (§2g confirmed),
  but whether `github.event.deployment.environment` is `"production"` (the
  Railway environment name) or the service name is not confirmed in a primary
  source.  Matters only for option C2 filtering.
