# there is no Host protocol: in-backend host and worker service run the same loop

The detached-run model needs a host that claims and executes 生成執行 items. Two
hosting configurations are planned: the backend's lifespan task (in-process) and a
separate Railway worker service (out-of-process). The question was whether these two
configurations require a shared abstraction — a Host interface or protocol.

## Considered Options

**Minimal with Host seam.** Three entry points plus a Host seam that exposed
`_RunContext`. Rejected because the seam leaked an internal type to callers who had
no use for it beyond the one real adapter.

**Flexible with dead methods.** A `RunHost` class carrying methods that only one
adapter ever implements. Rejected because unreachable methods on a live object are
both misleading and untestable.

**Ports and adapters.** A seven-method `RunStore` with an in-memory fake. Rejected
because the in-memory fake cannot reproduce `SELECT … FOR UPDATE SKIP LOCKED`
semantics, which means the behaviour that most needs testing cannot be tested against
the abstraction.

**One shared function.** `run_host_loop(stop_event, *, clock, client_factory,
session_factory)` is the host. The backend's lifespan task and `python -m
server.worker` both call it directly. They differ only in which process calls it,
not in what they call.

## Decisions

**There is no Host protocol.** Cancel travels through the database (ADR 0033), so
the two hosting configurations differ only in who calls `run_host_loop`. A Host
interface would have one real adapter, which makes it a hypothetical seam that adds
ceremony without enabling any test or future flexibility that matters now.

**`GENERATION_HOST_ENABLED` (default on) selects whether a service runs the loop.**
Setting it to `false` on the backend is the entire split to a worker service. It also
doubles as an emergency stop.

**The real seams are injectable:** the LLM client (already injectable), the clock
(system or fake), and the optional live observer (in-process queue or none). These
are the things that need to vary in tests and across configurations; the Host itself
is not one of them.

## Consequences

The worker split is a configuration-only change: same image, `python -m
server.worker`, `GENERATION_HOST_ENABLED=false` on the backend. No code change is
needed to make that split.

Because there is no Host protocol, there is also no Host interface to stub for unit
tests. Tests that need to exercise the loop drive it through `run_host_loop` directly,
using injectable fakes for the clock and session factory.

## See also

- ADR 0033 — only the owner cancels a 生成執行; observer disconnection does not
- ADR 0035 — run-claim tests target Postgres because SQLite cannot exercise SKIP LOCKED
- openspec change `detached-generation-runs` proposal.md (Decision D4)
