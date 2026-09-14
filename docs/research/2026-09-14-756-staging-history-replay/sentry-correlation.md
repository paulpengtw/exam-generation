# Correlation of the three shared Sentry reports

Investigated 2026-09-14. No application code, configuration, deployment, or
Sentry issue status was changed. No additional generation was started.

**Finding:** the latest events line up with the same natural-sciences acceptance
flow, but represent **two separate failures**. The second and third links are
the warning and HTTP exception emitted for one planner rejection. The first
link is the subsequent generation request being rejected with HTTP 414.

## Event timeline

Times below are Asia/Taipei (UTC+08:00); event timestamps in the accompanying
JSON are UTC.

| User link | Sentry issue | Latest event time | Observation |
|---|---|---|---|
| [Third](https://cpengme.sentry.io/share/issue/e7fd52273ad6458aad71a845e12789ea/) | EXAM-GENERATION-API-STAGING-7 / 7641495846 | 13:11:00.730 | Warning: `Planner returned malformed candidates: Planner returned 2 candidates, expected 3` |
| [Second](https://cpengme.sentry.io/share/issue/3166b8743d6f424d9baf44bef36fe510/) | EXAM-GENERATION-API-STAGING-8 / 7641495852 | 13:11:00.738 | Chained `ValueError` → `HTTPException`: `Planner upstream returned malformed candidates`; HTTP 502 |
| [First](https://cpengme.sentry.io/share/issue/b06330758404488b8a5aadaa545cbd45/) | EXAM-GENERATION-WEB-STAGING-A / 7690729333 | 13:11:05.764 | `Stream open failed: HTTP 414` in `/generate/natural_sciences` |

The local browser capture places POST `/api/generate/resolve` at
13:10:29.669 (200) and the GET `/api/generate` submission at 13:11:05.566
(414). The frontend Sentry exception was created 198 ms after that submission.

## Why the two backend issues are one failure

The second report includes the complete application exception chain:

```text
plan_core_questions_endpoint
  → _ns_plan_core_questions
  → src/natural_sciences/planner.py::plan_core_questions
  → src/common/planner.py::plan_core_questions
  → _parse_candidates
  → ValueError("Planner returned 2 candidates, expected 3")
```

The source attached to that Sentry event shows the endpoint catching the
`ValueError`, logging the warning at `server/generate/routes.py:545`, then
raising HTTP 502 at line 546. The third report's formatted warning and
`ValueError` parameter match exactly. Their timestamps are 8 ms apart.

Local [observability.py](../../../server/observability.py) configures
`LoggingIntegration(event_level=logging.WARNING)`, which explains why the
warning becomes a separate Sentry issue. The second event identifies its
exception mechanism as `starlette`, handled. These are two reporting paths
for the same planner rejection, not evidence of two independent planner runs.

The parser found only two usable candidates after the planner's bounded retry
path. The shared report does not contain the raw model response or its model
ID, so it does not establish whether the response contained only two entries,
contained empty entries that were filtered, or took the parser's text fallback.
It also does not expose the first attempt's exact parse failure.

## Why HTTP 414 is separate

The frontend's automatic core-question planning effect catches planning failure
and sets `coreQuestionResolution="failed"`
([ParamForm.tsx](../../../web/src/components/ParamForm.tsx), lines 1601–1663).
It leaves the core question for generation to decide and allows the user to
submit the confirmed parameters. It does not turn HTTP 502 into HTTP 414.

The saved browser evidence shows that the ensuing natural-sciences generation
URL was **9,354 bytes** (path plus encoded query), carrying the two complete
question rows, six slot configurations, and drawn-field provenance. It
contained **no `core_question`**, either at the top level or in either row.
The planner failure therefore did not inflate this request with a generated
core question.

The first Sentry report points to `useGenerate.ts:609`, where the generation
stream's `onopen` handler turns the actual non-200 HTTP response into
`FatalStreamError`. The terminal catch captures that exception in Sentry.
Its 414 is a generation request-target/transport failure, distinct from
the planner's insufficient-candidate response. The exact deployed hop enforcing
the URL limit is not identified by these shared reports.

The evidence supports a common UI sequence:

```text
Natural-sciences confirmation
  → automatic core-question planning
  → too few usable candidates
  → warning (API-STAGING-7) + HTTP 502 (API-STAGING-8)
  → UI falls back and permits submission
  → complete generation parameters sent in GET URL
  → HTTP 414 (WEB-STAGING-A)
```

This is a temporal/workflow correlation between the frontend and backend
failures, not evidence that the malformed candidates caused the oversized URL.
The public share payloads omit trace/request identifiers and breadcrumbs, so
a shared distributed trace cannot be proven from them. The natural-sciences
backend stack, frontend route, and exact local submission timing support the
same-test-flow attribution.

The math QuestionCard rendering crash from the acceptance report is a separate
failure and is **not one of these three shared reports**.

## Evidence

- [sentry-event-summaries.json](sentry-event-summaries.json): selected public
  event IDs, issue names, timestamps, messages, and application frames. No
  authentication data or raw request headers were retained.
- [p3-capture.json](p3-capture.json): independently recorded natural-sciences
  resolve and generation requests/statuses from the acceptance run.
- [README.md](README.md): original acceptance outcome and request-size evidence.

The public shared-issue APIs were discovered from the pages' actual resource
requests and read without changing Sentry state. Only each share's latest
event was available; these findings do not assert that every historical event
in the three issue groups belongs to this run.
