# generation-release-control Specification

## Purpose

Protect new and in-flight generation requests while frontend and backend versions change independently. Require verifiable admission suspension, complete draining and compatible release gates so that old tabs and rollbacks cannot silently receive unsupported progress contracts.

## Requirements

### Requirement: Admission suspension survives application rollback
Operators SHALL have a deployment admission control that rejects new generation before dispatch across every externally reachable entry point and backend instance, including direct API callers and old tabs. The control SHALL remain effective when either application side is rolled back; disabling only a frontend button SHALL NOT satisfy it. Suspended admission SHALL return a readable temporary-unavailability response, such as HTTP 503 with string detail, without new worker or model activity. Established generation streams and existing result reads SHALL not be treated as new generation by the suspension.

#### Scenario: Admission is paused across multiple instances
- **WHEN** old tabs and direct API clients submit new generation requests through different public routes
- **THEN** every route rejects before dispatch and neither backend starts new work
- **AND** already-established streams can still deliver their remaining content

#### Scenario: An application version is rolled back
- **WHEN** the frontend or backend image changes while admission is suspended
- **THEN** the independent admission control stays closed and cannot disappear with that application rollback

### Requirement: Deployment requires positive drain evidence
Before a planned application switch, operators SHALL pause new admission and verify that all affected instances have completed active generation work, established generation streams and queued result delivery. An empty browser, elapsed timeout, pipeline_end, lost connection or unavailable telemetry SHALL NOT prove drain completion. If drain cannot be established, the planned switch SHALL wait rather than forcibly terminate work. Initial installation of admission and drain controls SHALL be treated as required preparation, not an already-existing capability.

#### Scenario: Disconnected work is still cleaning up
- **WHEN** a client has disconnected but its worker or event delivery cleanup remains active
- **THEN** the affected instance is not considered drained

#### Scenario: One instance lacks trustworthy drain evidence
- **WHEN** one backend is uninstrumented, unreachable or still has work or queued results
- **THEN** the release gate remains closed rather than counting that instance as zero active work

### Requirement: Protocol rollout is atomic at public admission
The release SHALL proceed through pause, positive drain, frontend/backend switch, compatibility verification and reopening. Backend instances can roll internally only while public generation admission remains closed. Reopening SHALL require all public generation routes to reach compatible v2 servers, valid new-client v2 behavior, old-client HTTP 426 rejection with zero dispatch, and required cross-layer, export and shared-surface acceptance evidence. An in-flight stream SHALL NOT change its protocol mid-response or be migrated to another generation execution.

#### Scenario: Mixed backend versions exist during rollout
- **WHEN** some nodes are updated and others still run the old generation contract
- **THEN** new public generation remains suspended until the full route and instance inventory passes compatibility checks

#### Scenario: An old tab submits after reopening
- **WHEN** the new release is open and an old tab submits without stream_version 2
- **THEN** it receives a readable HTTP 426 update request before any model or worker call

### Requirement: Four client-server combinations have explicit outcomes
Compatibility acceptance SHALL cover C0/S0, C0/S1, C1/S0 and C1/S1, where C0/S0 are the fixed legacy reference and C1/S1 implement this change. C0/S0 SHALL be documented as the existing limited behavior, not certified as truthful new per-question progress. C0/S1 SHALL be rejected before streaming. C1/S0 SHALL preserve an accidentally started batch with legacy aggregate/content handling and no resubmission. C1/S1 SHALL validate v2 before per-question live presentation. Intentional public operation in an incompatible combination SHALL NOT count as a completed rollout.

#### Scenario: The same interleaved A and B case is used across versions
- **WHEN** all four combinations are exercised against their appropriate server behavior
- **THEN** C0/S1 produces no generation events, C1/S1 preserves original positions and terminal facts, and C1/S0 preserves attributed contents without inventing positions or terminal facts
- **AND** defects in the frozen C0/S0 baseline are documented, not hidden by claims that an unmodified old client was fixed

### Requirement: Incompatible rollback sacrifices new admission rather than evidence
A planned frontend-only or backend-only incompatible rollback SHALL pause admission and drain existing generation first. Admission SHALL remain paused until compatible frontend, backend and version rejection are restored. A rolled-back frontend that can only reload the same incompatible page SHALL NOT be called recovered merely because the backend returns 426. A rolled-back backend without the application version gate SHALL remain behind the independent closed admission control. Unexpected interruption SHALL preserve received content and established conclusions, mark unsupported outcomes unknown and never trigger automatic new generation or inferred cancellation.

#### Scenario: Frontend rolls back to C0
- **WHEN** S1 remains but the deployed frontend no longer supports v2
- **THEN** admission stays paused until a compatible client build is restored
- **AND** already-open compatible pages are not forcibly refreshed or cleared

#### Scenario: Backend rolls back to S0
- **WHEN** C1 remains but the backend no longer enforces v2 admission
- **THEN** the independent admission control continues rejecting new generation
- **AND** any accidentally established legacy stream is handled with the declared legacy fallback rather than automatic resubmission

#### Scenario: Failure interrupts a stream before drain
- **WHEN** an unplanned infrastructure failure cuts an active connection
- **THEN** known content and conclusions remain and missing terminal evidence becomes unknown
- **AND** this failure is not recorded as successful planned drain or confirmed cancellation

### Requirement: Conditional ADR migration and cross-layer acceptance precede reopening
A new ADR SHALL explain the conditions under which attributable versioned terminal evidence permits per-question progress. ADR 0009 SHALL retain its legacy/unattributable restrictions and link to the conditional replacement. Neither synchronizing specs nor merging an ADR alone SHALL activate the exception. Implementation, controlled cross-layer scenarios and release gates SHALL demonstrate the new behavior first. Integration SHALL explicitly supersede conflicting old count/live/draft-export rules where this contract applies while preserving 人工審題修正 and unrelated ai-working-surfaces behavior. Acceptance SHALL use reproducible controlled generation events and UI/export artifacts without requiring paid model generation.

#### Scenario: Planning artifacts are complete but implementation is not
- **WHEN** this change's deltas are synchronized into main specs
- **THEN** the change remains active and the ADR exception and deployment readiness are not claimed to be in effect

#### Scenario: Shared AI-working surfaces are integrated
- **WHEN** ai-working-surfaces is integrated before or after this change
- **THEN** v2 terminal and receipt counts, gated per-card live activity and draft exports remain authoritative in their declared profiles
- **AND** legacy attribution limits, modification semantics and unrelated motion/accessibility rules do not regress
