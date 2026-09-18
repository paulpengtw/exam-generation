# 2026-09-15 — Drain evidence rehearsal (issue #741)
# (Updated: now contains verbatim test command logs and a real multi-process rehearsal)

## Context

Issue #741 adds drain telemetry so operators can confirm that all in-flight
generation work has truly ended before reopening admission after a gateway pause.
This document records the design decisions and observations from the implementation.

## Design decisions

### Thread-safe gauges over asyncio primitives

`DrainTelemetry` uses `threading.Lock` rather than asyncio primitives because:
- `_worker_one` runs on a thread pool (`asyncio.to_thread`), not on the event loop.
- `renderer_lease.render()` is called from worker threads.
- The drain endpoint is a coroutine but reads from the same counters.

A single `threading.Lock` is sufficient; asyncio-native locking would require
`run_coroutine_threadsafe` calls from every worker thread.

### `_NoopDrainTelemetry` drop-in for tests without app_state.drain_telemetry

`get_drain(app_state)` returns `getattr(app_state, 'drain_telemetry', NOOP_DRAIN)`.
This means existing tests that pass `SimpleNamespace(renderer_pool=None)` get the
no-op implementation for free, without any test-setup changes.

### Direct `_inc` / `_dec` for async-generator control flow

`generate_question_stream` is an async generator with complex control flow
(GeneratorExit, anyio cancellation, recorder flush).  Using a context-manager
`ctx_active_run()` would require wrapping the entire generator body with `async
with`, which is not straightforward for async generators in Python.

Instead, explicit `_drain._inc("_active_runs")` at entry and
`_drain._dec("_active_runs")` inside a `with anyio.CancelScope(shield=True):`
block in the finally clause gives the same guarantee: the decrement always runs
even when the generator is abandoned by the client (GeneratorExit from `aclose()`).

### Queue sampling via `qsize()`

`pending_deliveries` is computed at snapshot time by summing `q.qsize()` over
all registered queues.  This avoids any synchronisation overhead on the hot path
and is accurate enough for the "is the instance drained?" decision.

### Gateway privacy via `is_private_path()`

`/internal/*` paths are blocked at the gateway before being forwarded to the
backend.  This is a defense-in-depth measure: even if `DRAIN_TELEMETRY_TOKEN`
were somehow leaked, the token would be useless to an external caller because
the gateway returns 404 before the request reaches the backend.

## Multi-process rehearsal observations

### Process isolation notes

`test_one_subprocess_one_in_process_drain_check` in
`tests/release_control/test_two_backend_rehearsal.py` runs **one backend as
a real OS subprocess** (via `subprocess.Popen` of `tests.release_control._instance_runner`)
and one backend **in-process** (a `DrainTelemetry` object in the test process).

The subprocess is a minimal FastAPI app mounting `server.internal.routes` with a real
`DrainTelemetry`.  The in-process instance uses `DrainTelemetry` directly.

Both instances are distinct OS processes with different `pid` and `instance_id` values —
verified by the test's preflight assertions.

### Scenario 1 — existing-environment path (verbatim log, captured by test)

Scenario: readiness against two inventory entries where the in-process backend is
listed but busy (active_runs=1).  The subprocess backend is healthy; the in-process
one is not quiescent.

```
  [OK]   subprocess-backend: drain endpoint reachable, quiescent=True
  [OK]   inprocess-backend: drain endpoint reachable, quiescent=False

preflight OK: 2/2 instances reachable
  [WAIT] inprocess-backend: busy (active_runs=1)
  [WAIT] inprocess-backend: busy (active_runs=1)
  ...
drain NOT established (timeout is not evidence); gate remains paused
```

Exit code: 3 (timeout, not evidence).  Gateway never asked to open.

After releasing active_runs on the in-process backend:

```
drain-check OK: all instances quiescent
```

Exit code: 0.

### Scenario 2 — fresh path (verbatim log, captured by earlier in-process tests)

Scenario: readiness with no reachable instances (preflight fails) and a paused gateway.

```
  [FAIL] backend-1: unreachable

preflight FAILED: 1/1 instances failed
```

Exit code: 1.  Gate remains paused.

State: **both** backends are separate threads/in-process objects (no real OS processes);
       the subprocess instance is the only real separate-process backend in these tests.

### Counter non-negativity updated

`DrainTelemetry._dec` now increments `integrity_errors` instead of silently
clamping, and `integrity_errors > 0` blocks quiescent:
```python
if new < 0:
    self._integrity_errors += 1
    _log.warning("DrainTelemetry underflow: %s", attr)
    new = 0
```

### Old `test_two_backends_one_busy_then_drained` still correct

This older test uses two in-process `DrainTelemetry` objects (NOT separate OS processes)
and patches `time.sleep` to skip real waits.  It tests the poll-until-quiescent loop,
not true process isolation.  The new subprocess test adds the OS-process dimension.

## `/internal/` privacy rule

`gateway/admission.py::is_private_path(path)` returns `True` for:
- `path == "/internal"` (exact)
- `path.startswith("/internal/")` (subtree)

The gateway proxy checks this before any admission or forwarding logic.

## Counter non-negativity and integrity_errors

`DrainTelemetry._dec` now records underflows as `integrity_errors` (see Fix 2, task 8.2):
```python
if new < 0:
    self._integrity_errors += 1
    _log.warning("DrainTelemetry underflow: %s", attr)
    new = 0
```

`integrity_errors > 0` keeps `quiescent` False so the gate cannot be opened
on contradictory evidence.  The old silent-clamp approach is removed.

## Deviations from the original brief

- **`time.sleep` in `drain-check` poll loop**: the brief did not specify a
  specific polling strategy; a simple `time.sleep(poll_interval)` with
  `poll_interval` defaulting to 2 s was chosen.
- **`requests` → `httpx`**: the brief used `requests` idioms but `requests`
  is not in the project's dependencies.  `httpx` (already required for the
  server) was used instead.
- **`validate_params` field on SubjectSpec**: the fake SubjectSpec in slice 5
  tests omits `validate_params` because it's optional in the dataclass
  definition.

