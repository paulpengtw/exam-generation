# run-claim tests target Postgres in CI because SQLite cannot exercise SKIP LOCKED or native enums

The run-claim step uses `SELECT … FOR UPDATE SKIP LOCKED` to safely hand a queued
生成執行 to exactly one host when multiple workers compete. The existing CI suite
runs against SQLite.

## Decisions

**Run-claim tests run against Postgres 16 in CI.** SQLite does not support
`SKIP LOCKED` and does not have native enum types. A test that substitutes SQLite
for Postgres in the claim step is not a test of the claim step; it is a test of a
different, simpler database that cannot reproduce the race conditions the claim
mechanism is designed to prevent.

**A Postgres 16 service container is added to `.github/workflows/ci.yml`.** Tests
that exercise claim races, stale requeue, the attempt limit, per-teacher limits,
cancel races, and the `ALTER TYPE … ADD VALUE` enum migrations are marked `postgres`
and run against that container. A `postgres` pytest marker and a `DATABASE_URL`
fixture gate them.

**All other tests keep SQLite.** The existing suite continues to run unchanged. Only
the tests that specifically exercise Postgres-only behavior are marked and routed to
the Postgres container.

## Consequences

A `postgres` marker on a test signals that it relies on Postgres-specific behavior
and must not be run against SQLite. Unmarked tests remain SQLite-only and fast.

The claim-race tests — two concurrent claimers never claim the same run, stale
requeue with a fake clock, the attempt limit, the per-teacher limit, cancel races,
and the enum migration — now exercise the actual behavior that ships to production.

## See also

- ADR 0034 — there is no Host protocol; in-backend host and worker service run the same loop
- openspec change `detached-generation-runs` proposal.md (Decision D10) and tasks.md (tasks 2.1–2.4, 3.2)
