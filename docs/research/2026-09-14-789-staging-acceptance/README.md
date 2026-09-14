# #789 / PR #792 staging acceptance

PR #792's diagnostic implementation passes code review, the focused regression suite, a fresh real-ten-second before/after reproduction, and an in-memory check of the configured Sentry SDK boundary. The live smoke is qualified: three groups completed and persisted; the remaining social-studies stream was interrupted at 900 seconds, matching the existing #702 transport issue. No new exchange-persistence warning was observed. The five original warnings remain historically unclassified.

## Revision and deployment

- PR: https://github.com/paulpengtw/exam-generation/pull/792
- Issue: https://github.com/paulpengtw/exam-generation/issues/789
- PR head: `729c98dae0e663bd9227f0da177e507013aab14a`.
- Review base: `850c455f79b804d0cb84f8ef44efdfa8fde952f9`.
- Merge: `4ce2ea664bc7a44bf4fe37acf652aaa2044e58c2`, merged at 08:48:08 UTC on 2026-09-14.
- Railway GitHub deployment `6433568306` reported success at 08:49:34 UTC. The live frontend asset `/assets/index-DforW4uL.js` identifies the same merge as its Sentry release. Backend events do not provide a release tag; frontend release evidence alone is not an independent backend-build fingerprint.
- PR CI passed. The merge CI also passed both Python and web jobs: https://github.com/paulpengtw/exam-generation/actions/runs/34824576428

## Controlled persistence verification

An isolated checkout at the merge revision was tested using Python 3.12.12. No application code in the working repository was changed. `choom` is unavailable on this Mac; only one test lane ran.

```
.venv/bin/python -m pytest -q \
  tests/server/test_exchange_recorder.py \
  tests/server/test_exchange_persistence_integration.py \
  tests/server/test_exchange_persistence_stream.py \
  tests/server/test_exchange_routes.py \
  tests/server/test_persistence.py
```

Result: **33 passed in 28.38 seconds**. Changed-file Ruff and `git diff --check` also passed.

The suite checks successful writes, delayed commits, real SQLite rejection, cancellation, scheduling rejection, authenticated exchange reads, and concurrent stream/History continuation. In each concurrent-stream case, twelve exchange writes remain gated while four results and four History records finish; release either commits all twelve or produces twelve `IntegrityError` outcomes with no exchange rows.

`reproduce_wait.py` additionally uses the actual ten-second production wait on both revisions, with a real SQLite commit held until the recorder returns. The existing helper asserts that the exchange read API is empty before release and that the expected row exists afterward.

| Revision | Elapsed | Before-release warning | Eventual exchange rows |
| --- | ---: | --- | ---: |
| Before PR | 10.072 s | `llm_exchanges insert failed: `, no diagnostic metadata | 1 |
| After PR | 10.036 s | `llm_exchanges insert pending (TimeoutError)` | 1 |

The new warning reports `builtins.TimeoutError`, generation-log UUID, agent, and order. A subsequent `committed` warning carries the same identifiers. Neither warning contains a traceback or synthetic prompt/answer/credential sentinel. See `real-ten-second-reproduction.json`.

`check_sentry_transport.py` runs the production observability configuration with an in-memory transport, so no telemetry is sent. Both pending and committed events retain the six safe correlation/classification fields through the actual installed Sentry SDK. Neither event contains an exception object or any synthetic content. See `sentry-transport-check.json`.

Both standalone scripts should be run with the checkout as the current directory and its virtual environment, with the checkout on `PYTHONPATH`. They import the PR's existing integration helpers. The original source is read from Git at the review-base SHA.

## Live staging smoke

ego-browser TaskSpace 15 used the supplied staging login. Social-studies and natural-sciences requests were submitted through the real form, resolve, confirmation, and generation flow at 08:56:03 UTC, less than half a second apart. Both requested two groups of three subquestions, grade 7, text-only content, HTML image mode, and a 200-word passage limit. Verification remained enabled; social studies was pinned to geography. No request or response was modified.

The observer retains HTTP/SSE counts, timing, agent/purpose/stage metadata only. It does not store authentication headers, prompt bodies, generated text, or answers. SSE `started` and `done` have empty data, so their counts are authoritative even though the JSON-event detail list omits them.

| Live request | Started | LLM requests / responses observed | Results / done | Final state |
| --- | ---: | ---: | ---: | --- |
| Natural sciences | 1 | 10 / 10 | 2 / 1 | Completed in 4m43s; two verified History records |
| Social studies | 1 | 14 / 13 | 1 / 0 | One verified History record; network interruption during the other group's re-verification |

Each completed record contains exactly three subquestions. History total increased from 51 to 55: three completed records plus one aborted-run record. Both submissions opened exactly one POST; neither reconnected.

- [NS group 1](https://examgen-staging.cpeng.me/history/19cdcdf8-5d5d-49b9-a48a-8cdf56258e6c)
- [NS group 2](https://examgen-staging.cpeng.me/history/b9b285ca-2d06-4484-a93e-33d3612cd1be)
- [SS completed group](https://examgen-staging.cpeng.me/history/0dcfa99b-5fad-4dcb-bcb6-701c4202981a)
- [SS aborted-run record](https://examgen-staging.cpeng.me/history/070c80f1-751b-47f8-8a99-2eaeed274a48)

The SS browser read failed with `TypeError: network error` at 09:11:03 UTC, exactly fifteen minutes after its 08:56:03 submission. No SSE `error` or `done` preceded the failed read. The UI showed `network error`; the capture's `captureError` is `TypeError`. Sentry recorded event `fa8f24e95fe24541b5f7718d3672e47f` in [EXAM-GENERATION-WEB-STAGING-7](https://cpengme.sentry.io/issues/7686623806/), also at 09:11:03. The backend persisted an aborted-run record at 09:12:03. No agent cancellation was performed.

This timing and behavior match the already-open [#702: Railway edge resets long SSE streams at 900 seconds](https://github.com/paulpengtw/exam-generation/issues/702). That issue predates #792 and covers long verify/correct loops. This run did not capture an HTTP/2 reset frame or access Railway logs, so the edge attribution is a strong match to the documented issue rather than a fresh protocol-level proof. Repository nginx configuration uses a 300-second read timeout; no 900-second application timer was found in the generation hook/routes. GitHub reported no deployment after #792 during the run.

Final authenticated Sentry read at **09:13:57 UTC** found **zero new exchange-warning events** after deployment. The original issue remained at five events, last seen 07:34:42 UTC. No new backend issue appeared in the live window. Absence of a warning alone is not proof of live exchange-row completeness.

## Historical evidence and limits

Authenticated Sentry reads confirm the five original events in [EXAM-GENERATION-API-STAGING-J](https://cpengme.sentry.io/issues/7730828215/). Each has the blank warning, no exception entry, and none of the new run/agent/order fields. Authentication was available for this check, but the missing correlation information remains absent from the stored events.

These checks prove that a delayed commit can produce the original symptom and that PR #792 distinguishes that condition correctly. They do not establish whether any of the five historical writes were delayed, lost, or rejected.

The live History and generation SSE contracts do not expose generation-log UUIDs. Without a fresh diagnostic giving such a UUID, the exchanges API cannot be correlated to the live test runs. Eventual exchange-row assertions in this report therefore refer to the controlled authenticated-API checks, not a claim of live exchange completeness. The Railway project page was unavailable to the current browser session (404/Login); no deployment settings were changed.

## Review

- Standards: no documented violations or actionable smells. Diagnostics satisfy ADR 0004's content exclusion and preserve best-effort generation.
- Spec: no implementation defects or scope creep. The historical attribution limit is accurately documented. The diff does not incorporate #743 identity changes.

No GitHub comments, issue state, application code, deployment settings, or production data were modified. Completed staging acceptance outputs and the aborted-run record are retained in History. The browser TaskSpace was closed after evidence collection.
