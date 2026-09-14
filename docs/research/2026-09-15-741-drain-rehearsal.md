# 2026-09-15 — Drain evidence rehearsal (issue #741)

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

The two-backend rehearsal test (`test_two_backends_one_busy_then_drained`) shows
that `drain-check` correctly polls until the simulated active_run counter drops
to zero.  The key observation:

- On the first poll, inst1 reports `quiescent: false` because `_active_runs = 1`.
- After 0.3 s (simulated by a background thread), `_dec` is called.
- On the second (or later) poll, inst1 reports `quiescent: true`.
- `drain-check` exits 0.

The test patches `time.sleep` to a no-op so it runs fast without real waits.

## `/internal/` privacy rule

`gateway/admission.py::is_private_path(path)` returns `True` for:
- `path == "/internal"` (exact)
- `path.startswith("/internal/")` (subtree)

The gateway proxy checks this before any admission or forwarding logic.

## Counter non-negativity guarantee

`DrainTelemetry._dec` clamps at zero:
```python
new = max(0, getattr(self, attr) - 1)
```

This prevents a race where a crash or GeneratorExit causes an unmatched
decrement: the counter stays at 0 rather than going to -1.

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

