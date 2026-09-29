# only the owner cancels a 生成執行; observer disconnection does not

The detached-run model (openspec change `detached-generation-runs`) separates run
execution from any observer's connection. A 生成執行 runs from 受理 until every
question has a 終止原因, regardless of whether anyone is watching. This creates a
question: which actors may stop a run before every question has ended?

## Decisions

**Only the owning teacher's explicit Cancel action cancels a 生成執行.** Observer
disconnection, page unload, navigation, logout, browser close and the end of any
live observation stream are not cancellation and never affect the run. An observer
is not the owner.

**Cancellation applies to the whole run.** Per-question cancel is out of scope for
this change.

**Cancel travels through a database flag.** `cancel_run` sets
`generation_logs.cancel_requested`. The executing host checks it on every heartbeat
(~30 s) and at every 生成步驟 boundary, then confirms by setting
`confirmed_cancel_event` — the same event that already yields
`termination_reason=cancelled` for each unfinished question. Questions that have
already ended keep their results; the first-recorded 終止原因 wins.

**The interface shows 取消中 immediately.** The response latency (~30 s) is
accepted in exchange for a single host code path that requires no in-memory fast
path and no difference between the in-backend host and the worker service.

## Consequences

No Host protocol or cross-process signalling channel is needed for cancel (see ADR
0034). A cancel request that arrives after every question has already ended changes
nothing. A cancel that races a normal termination on the same question preserves the
first-recorded reason — the run does not become globally cancelled just because the
cancel flag was set.

The in-process live-stream observation path survives the split to a worker service
unchanged, because it never has authority to cancel the run.

## See also

- ADR 0034 — no Host protocol; in-backend host and worker service run the same loop
- openspec change `detached-generation-runs` proposal.md and specs/generation-run/spec.md
