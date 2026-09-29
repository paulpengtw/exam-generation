## ADDED Requirements

### Requirement: Staging follow mode advances released_build_id without drain evidence
A gateway instance with `GATEWAY_FOLLOW_FRONTEND=1` SHALL expose
`POST /gateway/release/follow`, authenticated by `X-Gateway-Control-Token`.
When called with a non-empty `build_id`:
- If `build_id` equals the current `released_build_id`, the endpoint SHALL
  return 200 and make no state change (idempotent; container restarts are
  harmless).
- If admission is `preparing`, the endpoint SHALL return 409 and make no state
  change; an operator is mid-release and the follow MUST NOT interfere.
- Otherwise, the endpoint SHALL atomically write `released_build_id = build_id`
  and increment `release_revision` by one, updating `artifacts.current` to the
  new build and setting `prepared_rollback` to the previous current artifact,
  mirroring `publish_target`'s artifact bookkeeping. Admission (`open` or
  `paused`) SHALL remain unchanged.
This endpoint MUST return 404 when `GATEWAY_FOLLOW_FRONTEND` is unset or not
`1`, exactly as other disabled control endpoints behave. Missing or invalid
`X-Gateway-Control-Token` SHALL return 403. An invalid or missing `build_id`
in the request body SHALL return 400.

#### Scenario: Follow endpoint is disabled by default
- **WHEN** the gateway starts without `GATEWAY_FOLLOW_FRONTEND=1`
- **THEN** `POST /gateway/release/follow` returns 404 regardless of token

#### Scenario: Bad or missing token is rejected
- **WHEN** `POST /gateway/release/follow` is called with a wrong or absent token
- **THEN** the endpoint returns 403 and makes no state change

#### Scenario: Same build ID is idempotent
- **WHEN** the posted `build_id` equals the current `released_build_id`
- **THEN** the endpoint returns 200 and the state file is unchanged

#### Scenario: New build ID advances the release
- **WHEN** the posted `build_id` differs from the current `released_build_id` and admission is open
- **THEN** `released_build_id` is updated, `release_revision` increments by one, `artifacts.current` is updated to the new build, `prepared_rollback` is set to the previous artifact, and admission remains open

#### Scenario: New build ID with paused admission
- **WHEN** the posted `build_id` differs from the current `released_build_id` and admission is paused
- **THEN** `released_build_id` and `release_revision` advance, `artifacts.current` and `prepared_rollback` are updated, and admission remains paused (unchanged)

#### Scenario: Follow is blocked during preparation
- **WHEN** admission is `preparing` and `POST /gateway/release/follow` is called
- **THEN** the endpoint returns 409 and the state file is unchanged

#### Scenario: Missing or empty build_id is rejected
- **WHEN** `POST /gateway/release/follow` is called with an absent or empty `build_id` field
- **THEN** the endpoint returns 400 and the state file is unchanged

### Requirement: Frontend image calls the follow endpoint on container start
The web image's nginx:alpine final stage SHALL include an executable script at
`/docker-entrypoint.d/50-follow-release.sh`. The nginx official entrypoint runs
every executable `*.sh` in that directory synchronously before exec-ing nginx,
so the script MUST always exit 0 and finish in well under 30 seconds. The
script SHALL be inert (log one line and exit 0) unless both `GATEWAY_FOLLOW_URL`
and `GATEWAY_CONTROL_TOKEN` are set, so production and local compose are
unaffected by default. When both are set, the script SHALL read `build_id` from
`/usr/share/nginx/html/build-meta.json`, POST it to `$GATEWAY_FOLLOW_URL` with
the `X-Gateway-Control-Token` header, apply short per-attempt timeouts and a
small number of retries (total elapsed time well under 30 s), log the outcome
with a clear prefix, and exit 0 regardless of outcome (nginx MUST start even
when the gateway is unreachable).

#### Scenario: Script is inert without environment variables
- **WHEN** the container starts without `GATEWAY_FOLLOW_URL` or `GATEWAY_CONTROL_TOKEN` set
- **THEN** the script logs one inert line and exits 0 without making any network call

#### Scenario: Script posts the build ID to the gateway
- **WHEN** both `GATEWAY_FOLLOW_URL` and `GATEWAY_CONTROL_TOKEN` are set
- **THEN** the script reads `build_id` from `build-meta.json`, POSTs it to the follow endpoint, logs the HTTP response, and exits 0

#### Scenario: Script exits 0 when the gateway is unreachable
- **WHEN** the follow endpoint cannot be reached within the retry window
- **THEN** the script logs the failure and exits 0, allowing nginx to start normally

## MODIFIED Requirements

### Requirement: Deployment requires positive drain evidence
Before a planned application switch, operators SHALL pause new admission and
verify that all affected instances have completed active generation work,
established generation streams and queued result delivery. An empty browser,
elapsed timeout, pipeline_end, lost connection or unavailable telemetry SHALL
NOT prove drain completion. If drain cannot be established, the planned switch
SHALL wait rather than forcibly terminate work. Initial installation of
admission and drain controls SHALL be treated as required preparation, not an
already-existing capability.

**Exception — staging follow mode:** When `GATEWAY_FOLLOW_FRONTEND=1` is set
on a gateway instance, the `POST /gateway/release/follow` endpoint MAY advance
`released_build_id` without pausing admission and without drain evidence or
route verification. The one guarantee weakened by this exception is
**drain-before-switch**: the accepted frontend build changes while admission
stays open and without proving that in-flight generation work has drained. Old
tabs continue to receive `426 CLIENT_UPDATE_REQUIRED` after a follow call, by
design — that is the exact-build gate working correctly, not a weakening. The
short race is separate: for a few seconds after the hook fires, new page loads
can still be served the old bundle by the old container while the gateway
already expects the new build ID, so those page loads see "update required"
once; a reload fixes it.

The justification for accepting this on staging is that the follow endpoint only
changes which frontend build the gateway admits. It does not switch backend
instances — Railway deploys the backend independently — and a policy change does
not cut off established generation streams. Even if a merge to staging changes
the backend alongside the frontend, backend instances are deployed separately,
not at the moment the hook fires. Production MUST NOT set
`GATEWAY_FOLLOW_FRONTEND=1`.

#### Scenario: Disconnected work is still cleaning up
- **WHEN** a client has disconnected but its worker or event delivery cleanup remains active
- **THEN** the affected instance is not considered drained

#### Scenario: One instance lacks trustworthy drain evidence
- **WHEN** one backend is uninstrumented, unreachable or still has work or queued results
- **THEN** the release gate remains closed rather than counting that instance as zero active work

#### Scenario: Staging follow mode skips drain
- **WHEN** a staging gateway with `GATEWAY_FOLLOW_FRONTEND=1` receives a valid follow request
- **THEN** `released_build_id` advances without drain evidence, admission is not paused (no 503 maintenance gap), and in-flight generation streams continue unaffected
