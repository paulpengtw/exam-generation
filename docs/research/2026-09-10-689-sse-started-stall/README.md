# Issue #689 — SSE stream emits `started` then only pings: staging evidence (2026-09-10)

Captures made with `scripts/capture_sse_689.py` against `https://examgen-staging.cpeng.me`
(staging at commit 93b6ba2, which includes #683) over HTTP/2 through the Railway edge.
Scenario: 社會領域, seed 554, `gpt_image`, three 小題 with two 小題 images, `skip_verify`,
the same request as `scripts/verify_figure_kind_diversity_staging.sh`. The script records
every SSE line with its client arrival time, compares each `stage`/`pipeline` event's
arrival against the server-emitted `ts`, and polls `/health` once a second to detect a
blocked event loop. The `starve` scenario kills two runs at their first
`image_agent render_image start` and immediately starts a third.

## Data table

| run | request start (UTC) | `started` | `pipeline_start` | gap | total | pings | delivery delay median / max | max `/health` latency | terminal | server-side record |
|---|---|---|---|---|---|---|---|---|---|---|
| control | 05:09:21 | 0.68 s | 14.60 s | 13.9 s | 279.4 s | 18 | 0.093 s / 0.888 s | 13.60 s (inside the gap) | done | completed 68a30e57 05:13:59 |
| A (killed at first image render, +123.3 s) | 05:14:52 | 0.35 s | 14.49 s | 14.1 s | 123.3 s | 7 | 0.085 s / 0.090 s | n/a | killed | aborted 26f822fc 05:16:56.01 (0.33 s after kill) |
| B (killed at first image render, +139.7 s) | 05:14:52 | 14.66 s | 30.18 s | 15.5 s | 139.7 s | 8 | 0.088 s / 0.096 s | n/a | killed | aborted 79c432fb 05:17:12.26 (0.18 s after kill) |
| C (started the moment B was killed) | 05:17:12 | 0.44 s | never | — | 900.3 s | 59 | — | 0.78 s | HTTP/2 RST_STREAM CANCEL from the edge at 900.3 s | aborted 6f739363 05:32:12 |
| probe, 16 min later | 05:34:03 | 0.48 s | never | — | 420.0 s (client timeout) | 27 | — | 0.76 s | client timeout | — |

## Verdict — a leaked Playwright renderer (neither candidate 1 nor candidate 2); fix in #700

`generate_question_stream` (`server/generate/service.py`) yields `started`, then does
`html_renderer = await renderer_pool.get()` on a pool of exactly two Playwright renderers
(`server/app.py`), unconditionally, even for `gpt_image` runs. The renderer is returned
only in the generator's `finally`:

1. `cancel_event.set()`
2. `await signal_task`  ← interrupted on client disconnect
3. flush the trail recorders
4. `await renderer_pool.put(html_renderer)`  ← never reached

On disconnect sse-starlette cancels its anyio task group. anyio re-arms cancellation every
event-loop tick and calls `task.cancel()` on any task still waiting inside the cancelled
scope, so the first `CancelledError` lands at `await queue.get()`, the `finally` starts,
and the next tick cancels step 2. The route's shielded `stream.aclose()` then runs on an
already-closed generator and returns at once. Each abandoned run leaks one renderer for
good; after two, every new run blocks at `renderer_pool.get()` right after `started` with
the event loop free, which is why pings keep flowing.

Server-side proof without Railway access: the `aborted` records for runs A and B were
written 0.33 s and 0.18 s after the client kill, while their image calls had about a
minute left. That write only happens after `await stream.aclose()` returns, so the cleanup
did not wait for the worker. Run C then saw only pings for 900 s and the probe still found
the pool empty 16 minutes later, far beyond `IMAGE_TIMEOUT_SECONDS` (300 s).

The 2026-08-26 records show the same shape: run 1 aborted 17:59:53, run 2 aborted
18:05:16, run 3 started about 18:08 and saw only pings until the client gave up at
18:23:14.

In-process reproduction: `tests/server/test_generate_disconnect_renderer_return.py`
(route seam, `http.disconnect` mid-stream; strict xfail for #700) shows the pool still
empty after the worker exits and the aborted write 0.000 s after the disconnect.

## Candidate 1 — a hung planning call (#701): real, but produces silence, not pings

`plan_all_batch_briefs` runs synchronously on the event loop between `started` and
`pipeline_start`; for 社會領域 with creative planning on it is one blocking planning LLM
call even for `count = 1`. In the control run the `/health` poll issued 1 s after `started`
took 13.6 s and returned exactly as `pipeline_start` arrived. Run B's `started` arrived at
14.66 s because run A's planning call was blocking the loop (A's `pipeline_start` arrived
at 14.49 s). A planning call that hung until `LLM_TIMEOUT_SECONDS` would therefore show as
no pings and no `/health` at all, so it cannot be run 3's cause. Tracked in #701.

## Candidate 2 — the ingress (#702): delivers events promptly, but resets streams at 900 s

Across the 279 s control run every server-emitted `stage`/`pipeline` event arrived
0.093 s after its server `ts` at the median and 0.888 s at worst, so the edge neither
buffers nor drops events. The ~225 s HTTP/2 cut reported on 2026-08-26 did not recur in
five runs. Run C was reset by the peer at 900.3 s with
`curl: (92) HTTP/2 stream 1 was not closed cleanly: CANCEL (err 8)` while pings were
arriving every 15 s and the client's own timeout was 1500 s; the backend wrote run C's
aborted record 0.1 s later. The frontend nginx `proxy_read_timeout 300s` is reset by each
ping and is not the limit. Tracked in #702.

## File index

| File | Description |
|------|-------------|
| `timeline_control.txt` | Condensed SSE timeline of the control run (LLM content omitted), with per-event delivery delay and slow `/health` polls |
| `timeline_starve_A.txt` | Run A, killed at its first image render |
| `timeline_starve_B.txt` | Run B, killed at its first image render |
| `timeline_starve_C.txt` | Run C, started immediately after A and B were killed: the reproduction of run 3 |
| `timeline_probe_after.txt` | Single probe run 16 minutes later, pool still empty |
| `summary_*.json` | Per-run summary written by the capture script |
| `history_before.json` | `GET /api/history` (GenerationRecord) snapshot before the experiment |
| `history_after_starve.json` | `GET /api/history` snapshot after run C |
