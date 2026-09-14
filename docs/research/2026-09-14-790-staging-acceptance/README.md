# #790 — staging acceptance for 核心問題 planning (#763 / PR #788)

All seven acceptance criteria pass. Planning, confirmation display, submission
equality, explicit-value authority, exhausted-planning fallback, controlled
recovery/exhaustion, and single-event Sentry reporting were each verified and
are recorded separately below with their evidence boundary.

## Release and deployment

- Verification target: [#763](https://github.com/paulpengtw/exam-generation/issues/763) via [PR #788](https://github.com/paulpengtw/exam-generation/pull/788).
- PR #788 merged to `staging` as `850c455f79b804d0cb84f8ef44efdfa8fde952f9` at **08:04:38 UTC, 2026-09-14**.
- Staging runs `ad80b9bc0af2321ad22751dcbf3e8fcc4015d7ac`, which contains that merge. Railway deployment `6434119125` reported **success at 09:25:45 UTC**.
- Frontend fingerprint: the live asset `/assets/index-DSKsFHUB.js` embeds Sentry release `ad80b9bc0af2321ad22751dcbf3e8fcc4015d7ac`. Loaded after a hard navigation.
- **Backend caveat:** the API exposes no release tag. Its build is inferred from the single Railway deployment ref that also produced the fingerprinted frontend asset. That is not an independent backend fingerprint — the same limitation recorded in #789.
- Browser window: **09:50–10:12 UTC, 2026-09-14**. ego-browser TaskSpace 17, one space for the whole goal, closed at the end.

## Verdicts, recorded separately

| Check | Subject | Verdict | Environment / boundary |
| --- | --- | --- | --- |
| Automatic planning | math / SS / NS | **pass** | live staging browser + API |
| Confirmation display = submitted | math / SS / NS | **pass** | live staging browser + API |
| Explicit 核心問題 authority | math | **pass** | live staging browser + API |
| Rerender (pending + completed) | math | **pass** | live staging browser + API |
| Dismissed-confirmation late response | math | **pass** | live staging browser + API |
| Exhausted-planning confirmation UI | math / SS / NS | **pass** | browser-side interception (UI only) |
| Controlled recovery / exhaustion | planner + real endpoint | **pass** | isolated backend at the deployed revision |
| Sentry single-event reporting | real endpoint | **pass** | isolated backend, real SDK, in-memory transport |
| Generation admission | NS | **pass** | live staging API |
| SSE + completion | NS | **pass** | live staging API |

All topics and 核心問題 used in evidence are synthetic test content.

## Planning, display, and submission equality (live staging)

Each of the three subjects entered 發送前確認 with automatic planning and issued
**exactly one** `POST /api/plan-core-questions` (HTTP 200) returning **three
distinct, nonblank textual candidates**. The confirmation rendered
`candidates[0]` exactly once with the 預先產生 badge; candidates 1 and 2 never
appeared. The submitted top-level `core_question` and **every**
`per_question_params[i].core_question` equalled the displayed value.

| Subject | Planning calls | Candidates (distinct / nonblank) | Displayed | Top-level = displayed | Per-question rows all equal |
| --- | ---: | --- | --- | --- | --- |
| 數學 | 1 | 3 / 3 | candidate[0] ×1 | yes | 1 / 1 |
| 社會領域 | 1 | 3 / 3 | candidate[0] ×1 | yes | 2 / 2 |
| 自然科學 | 1 | 3 / 3 | candidate[0] ×1 | yes | 2 / 2 |

## Explicit value, rerender, and late responses (live staging)

- An explicitly supplied 核心問題 produced **zero** new planning calls; the
  displayed and submitted values equalled the supplied string, with no
  預先產生 badge.
- Rerendering the confirmation **while planning was pending** (two language
  toggles) started **no** additional planning request.
- Rerendering **after planning completed** likewise started none, and the
  displayed value was unchanged.
- A confirmation dismissed **while its planning call was still in flight** later
  received a valid HTTP 200 response. That late candidate never rendered and
  never entered the new submission, which retained its explicit value.

## Exhausted planning — confirmation UI (browser interception)

`POST /api/plan-core-questions` was failed with HTTP 502 in the browser only.
**This proves UI behavior alone and is not evidence of backend retry counts or
Sentry behavior.** In all three subjects the confirmation showed
**將於生成時決定**, **確定發送 stayed enabled**, the submitted body carried **no
`core_question` key at all**, every `per_question_params[i].core_question` was
`null`, and no stale 預先產生 badge or earlier candidate survived from the
preceding successful run in the same session.

## Controlled recovery and exhaustion (isolated backend)

Run against the deployed revision `ad80b9bc` in an isolated checkout with the
provider seam scripted and Sentry routed to an in-memory transport. The shared
staging provider was not altered and no fault-injection endpoint was added.
See `planner_acceptance_evidence.py` and `controlled-provider-evidence.json`.

| Case | Provider calls | Outcome |
| --- | ---: | --- |
| Insufficient output, then valid | 2 | success, three short candidates verbatim |
| Unparseable output, then valid | 2 | success |
| Insufficient twice | 2 | controlled failure, `stage=candidate_validation` |
| Unparseable twice | 2 | controlled failure, `stage=response_parse` |
| Short candidates on the first call | 1 | preserved verbatim |
| Numbered plain-text list (the #763 regression) | 1 | all three preserved |
| Duplicates only | 2 | controlled failure; not padded back to three |
| Non-text item (`42`) | 2 | controlled failure; never coerced into a candidate |

Recovery succeeds in exactly two calls and exhaustion fails in exactly two.
Four-character candidates such as `短問甲？` survive — the pre-#788 `len(line) > 5`
line filter is what turned three questions into two. No placeholders, duplicates,
or coerced values are ever inserted.

Through the real endpoint: exhaustion returned **HTTP 502** after **2** provider
calls; recovery returned **HTTP 200** with the three short candidates.

## Sentry (isolated backend, real SDK, in-memory transport)

One controlled exhausted request produced **exactly one exception event** and
**zero** marked warning issue events. The diagnostic survived as **one
breadcrumb** on that exception carrying `stage=candidate_validation`,
`attempt=2`, `expected_count=3`, `actual_count=2`, `received_count=2`.

Under ADR 0004, the telemetry contained no topic text, no candidate text, no
auth token, no teacher identity, and no request body. Unrelated warning and
error events from the same logger were still reported. The successful recovery
request emitted **zero** Sentry events.

Live staging Sentry (read-only, `cpengme/exam-generation-api-staging`) shows the
pre-fix pair — [`EXAM-GENERATION-API-STAGING-8`](https://cpengme.sentry.io/issues/7641495852/)
(exception) and its duplicate [`EXAM-GENERATION-API-STAGING-7`](https://cpengme.sentry.io/issues/7641495846/)
(warning, titled with the old `returned 2 candidates, expected 3` message) —
both last seen **05:11:00 UTC**, before the 08:04 merge, each still at count 9.
Neither recurred during this session. A controlled exhausted request cannot be
driven through live staging without altering the shared provider, which this
ticket forbids; the single-event correlation above is therefore from the
isolated seam.

## Generation admission, SSE, and completion (live staging)

One real natural-sciences submission was carried through 確定發送.

- Admission: `POST /api/generate` → **HTTP 200**, request body 3259 bytes.
  **No HTTP 414 is reachable here** — the generate request carries its payload in
  a POST body, not a GET query string, so its URI is 13 characters.
- SSE and completion: completed in **3m56s** with 4 subquestions; verification passed.
- Persisted record [`42deafc7-5303-4409-818e-1ddaf588bd98`](https://examgen-staging.cpeng.me/history/42deafc7-5303-4409-818e-1ddaf588bd98)
  (`ns_20260914_100712_001`, completed 10:11:53 UTC) stores the planner's
  `candidates[0]` in **both** `params_json.core_question` and
  `question_json.核心問題`.

This closes the chain end to end: planner candidate → displayed → submitted →
persisted parameters → the generated question's own 核心問題.

## Defects

None found. No follow-up ticket is warranted from this verification.

## Artifacts

| File | Contents |
| --- | --- |
| `browser-evidence.json` | Live-staging browser results for all three subjects |
| `controlled-provider-evidence.json` | Controlled recovery/exhaustion and Sentry results |
| `planner_acceptance_evidence.py` | The controlled-provider script (run from an isolated checkout at `ad80b9bc` with its venv and `PYTHONPATH=.`) |
| `sentry_planner_query.py` | Read-only live Sentry query for planner issues |
| `live-sentry-planner-issues.json` | Its output |
