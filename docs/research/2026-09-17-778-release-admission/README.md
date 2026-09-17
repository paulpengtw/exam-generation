# Release admission rehearsal — issue #778

This folder records the controlled, local readiness checkpoint for the live
release controller. It does not deploy anything and does not perform the final
teacher-facing A→B→A rollout.

## Reproduce

From the repository root:

```bash
uv run python scripts/release_admission_rehearsal.py \
  --output docs/research/2026-09-17-778-release-admission/evidence.json
```

The script starts two real local backend HTTP servers and two gateway HTTP
servers sharing the durable controller record. It records observed HTTP
responses and backend dispatch counters, then shuts down all local servers and
removes its temporary state directory.

## Coverage

The route inventory is the #740 public/alternate inventory: both GET/POST
generation spellings, policy/build metadata, preview, resolve, core-question
planning, modification, exchange/history reads, schemas, auth, health, and the
private `/internal/drain` path. The evidence also checks both
`web/nginx.conf` and `web/nginx.conf.template` for controller proxying,
`no-store` artifact headers, and `no-cache` HTML headers.

The recorded scenarios are:

- one current-build generation accepted and dispatched once;
- stale and missing build IDs rejected with 426 and zero generation/provider
  dispatches;
- paused and unavailable authority rejected with 503 and zero dispatches;
- an established stream completing while read-only routes continue;
- a policy publication rejected while an admission is pending, then accepted
  after that stream completes;
- release revision, route metadata, two backend identities, and exact dispatch
  counts recorded from the local server seams.

`evidence.json` is the machine-readable output from that run. Timestamps and
ephemeral local ports are expected to change when it is regenerated.
