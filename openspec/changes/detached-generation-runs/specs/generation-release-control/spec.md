## MODIFIED Requirements

### Requirement: Admission suspension survives application rollback
Operators SHALL have a deployment admission control that rejects new generation submissions before a run is created, across every externally reachable entry point and backend instance, including direct API callers and old tabs. The control SHALL remain effective when either application side is rolled back; disabling only a frontend button SHALL NOT satisfy it. Suspended admission SHALL return a readable temporary-unavailability response, such as HTTP 503 with string detail, without creating a run. Runs already accepted SHALL continue to execute and resume while admission is suspended. Reads of run state and results, cancel requests and established observation streams SHALL NOT be treated as new generation by the suspension.

#### Scenario: Admission is paused across multiple instances
- **WHEN** old tabs and direct API clients submit new generation requests through different public routes
- **THEN** every route rejects before a run is created and no new run is queued
- **AND** already-accepted runs keep executing and their owners can still read and cancel them

#### Scenario: An application version is rolled back
- **WHEN** the frontend or backend image changes while admission is suspended
- **THEN** the independent admission control stays closed and cannot disappear with that application rollback

### Requirement: Deployment requires positive drain evidence
Before the one-time cutover to detached runs, operators SHALL pause new admission and verify that all affected instances have completed active generation work, established generation streams and queued result delivery. An empty browser, elapsed timeout, pipeline_end, lost connection or unavailable telemetry SHALL NOT prove drain completion. If drain cannot be established, the cutover SHALL wait rather than forcibly terminate work. After the detached model has completed one release without lost runs, later deployments SHALL NOT require generation drain evidence, because accepted runs resume after host replacement. Those deployments SHALL instead report the counts of queued and executing runs from persisted state. The host drain window SHALL be at least the measured per-question p95 duration, with about 120 seconds used until that measurement exists.

#### Scenario: Disconnected work is still cleaning up
- **WHEN** a client has disconnected but its worker or event delivery cleanup remains active before the cutover
- **THEN** the affected instance is not considered drained

#### Scenario: One instance lacks trustworthy drain evidence
- **WHEN** one backend is uninstrumented, unreachable or still has work or queued results
- **THEN** the cutover gate remains closed rather than counting that instance as zero active work

#### Scenario: A routine deployment after the first clean release
- **WHEN** a backend is replaced while a run is executing
- **THEN** the deployment proceeds without waiting for drain and the run resumes on an available host

### Requirement: Protocol rollout is atomic at public admission
The cutover to detached runs SHALL proceed through the following steps:
1. pause admission;
2. obtain positive drain evidence;
3. switch the frontend and backend;
4. verify compatibility;
5. reopen admission.

Backend instances can roll internally only while public generation admission remains closed. Reopening SHALL require all of the following:
- every public generation route reaches a server that accepts protocol version 3;
- valid new-client submission, reading and cancel behavior;
- old-client HTTP 426 rejection with no run created;
- the release policy marks older frontends unsupported, so open old tabs show the existing update request;
- the required cross-layer and export acceptance evidence.

An in-flight stream SHALL NOT change its protocol mid-response or be migrated to another generation execution. The previous streaming endpoint SHALL NOT be kept alongside the detached protocol.

#### Scenario: Mixed backend versions exist during rollout
- **WHEN** some nodes are updated and others still run the old generation contract
- **THEN** new public generation remains suspended until the full route and instance inventory passes compatibility checks

#### Scenario: An old tab submits after reopening
- **WHEN** the new release is open and an old tab submits with the previous streaming version
- **THEN** it receives a readable HTTP 426 update request before any run is created
- **AND** the tab's preflight shows 介面版本已更新，請重新整理頁面後再生成。

### Requirement: Incompatible rollback sacrifices new admission rather than evidence
A planned incompatible rollback of the frontend alone or the backend alone SHALL pause admission first. Before the cutover, it SHALL also drain existing generation. Admission SHALL remain paused until a compatible frontend, backend and version rejection are restored. A rolled-back frontend that can only reload the same incompatible page SHALL NOT be called recovered merely because the backend returns 426. A rolled-back backend that cannot execute detached runs SHALL leave accepted runs persisted, unmodified and queued, and SHALL NOT mark them failed or cancelled. Those runs SHALL resume when a compatible backend returns. Unexpected interruption SHALL preserve received content and established conclusions, SHALL resume accepted runs according to `generation-run`, and SHALL never trigger a new generation submission or inferred cancellation.

#### Scenario: Frontend rolls back to C0
- **WHEN** the detached-run server remains but the deployed frontend rolls back to a build without protocol version 3
- **THEN** admission stays paused until a compatible client build is restored
- **AND** accepted runs keep executing and remain readable once a compatible client returns

#### Scenario: Backend rolls back to S0
- **WHEN** the backend rolls back to a build that no longer executes detached runs
- **THEN** the independent admission control continues rejecting new generation
- **AND** accepted runs stay queued with their saved results intact and resume after a compatible backend is restored

#### Scenario: Failure interrupts a stream before drain
- **WHEN** an unplanned infrastructure failure cuts an active connection or stops the host executing a run
- **THEN** the run resumes on an available host, ended questions keep their results, and no new submission or cancellation is inferred
