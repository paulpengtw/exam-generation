# #766 staging acceptance evidence

The live body-transport and History round-trip checks passed. Two independent observations are tracked in [#787](https://github.com/paulpengtw/exam-generation/issues/787) (standard Pydantic error details disappear from the UI) and [#789](https://github.com/paulpengtw/exam-generation/issues/789) (blank LLM-exchange persistence warnings). This verification does not close parent #756's broader acceptance scope.

Tested 2026-09-14, 15:21–15:44 Asia/Taipei (07:21–07:44 UTC), with subsequent evidence inspection. ego-browser TaskSpace 12 used the existing authenticated staging supervisor session. A cache-bypassing reload loaded frontend release `8941814b7973428a485d39c1a5d2b90fd52ddcad`, the merge of PR #768. GitHub deployment `6432290186` succeeded at 07:19:59 UTC; asset `/assets/index-BRzyNnVX.js` reported that same Sentry release. Sentry access used the existing authenticated read-only `sentry-cli` configuration; no credentials were exported.

| UI run | JSON body bytes | Equivalent GET target bytes | Preview / generation | Visible result / duration |
|---|---:|---:|---|---|
| SS original | 10,222 | 20,314 | POST 200 / POST 200 | 2 題組 / 8m20s |
| NS original | 9,882 | 19,917 | POST 200 / POST 200 | 2 題組 / 4m47s |
| Math smoke | 1,641 | 2,920 | POST 200 / POST 200 | 1 question / 53s |
| SS History replay | 10,222 | 20,314 | POST 200 / POST 200 | 2 題組 / 8m42s |
| NS History replay | 9,944 | 19,995 | POST 200 / POST 200 | 2 題組 / 5m09s |

Every SS/NS 題組 has three 小題. The forms included repeated synthetic Chinese 文本出題指示 and per-小題 出題指示, explicit text-only/HTML media settings, question/option limits 100/25 and text limit 300. NS per-item Reporting Scales 2/3/4 remained present in both original and replay outputs. Multiple curriculum/context/competency values were drawn independently. All were compared, preserving array order and nested batch rows.

Both endpoints use short paths: `/api/generate/preview` (21 bytes) and `/api/generate` (13 bytes). Equivalent GET sizes use `URLSearchParams` with repeated array keys, omitting absent/null values, and measure path plus query in UTF-8. Preview targets would be eight bytes longer than the generation targets shown above. All large SS/NS requests exceed the prior 9,489/9,354-byte failures. No HTTP 414 occurred.

Each actual submission opened exactly one accepted generation request, producing one SSE `started`, the expected number of `result` events and one `done`, with zero SSE error events. The UI aborts fetch after `done`; the observer's resulting `AbortError` is an expected completed-stream cleanup. SS exhausted its three correction retries and saved unverified results in both runs; NS and math passed verification. These are transport/persistence acceptance results, not an assertion that the generated SS questions passed teacher verification.

## History records and exact comparisons

| Run | Saved records |
|---|---|
| SS original | [小題組 1](https://examgen-staging.cpeng.me/history/cfe53c47-b73e-4dd0-bdc5-0c4bf5f7d2db), [小題組 2](https://examgen-staging.cpeng.me/history/46595a62-3163-4723-8fdb-0c437f95f1e0) |
| SS replay | [小題組 1](https://examgen-staging.cpeng.me/history/8b5ec211-666f-4a11-ae33-1d3a7e2b2eca), [小題組 2](https://examgen-staging.cpeng.me/history/b96a683c-82ab-408a-95f6-c448e297455d) |
| NS original | [小題組 1](https://examgen-staging.cpeng.me/history/c2a0a542-c872-4b0f-884d-8c6e656b5c8b), [小題組 2](https://examgen-staging.cpeng.me/history/fb7fd9d6-bd56-413f-bc45-49ac6396d70e) |
| NS replay | [小題組 1](https://examgen-staging.cpeng.me/history/1ab3c3ce-ca78-484c-96fb-684f990ad353), [小題組 2](https://examgen-staging.cpeng.me/history/d320e8c7-7da0-43d9-832a-ecb4417c815e) |
| Math | [Completed](https://examgen-staging.cpeng.me/history/d00692d7-7ce5-475e-93ac-b4d7b8b35142) |

`compare.py` decodes JSON-string fields recursively and compares all submitted leaves, including every batch/slot row, seeds, curriculum, context/subcontext, types/counts, math thinking/core/science competencies, scales, limits, instructions, media and `drawn` provenance. All nine saved records have **zero changed or missing submitted values**. Both actual History → 重新帶入 flows returned `drawn=[]`, `cleared=[]`; all batch rows match exactly, and original/replay saved parameter objects are semantically identical.

Serialization additions are reported separately, never silently discarded:

| Original saved subject | Non-null defaults added | Null additions |
|---|---|---:|
| SS | top-level `allow_duplicate_figure_kinds=false`, `max_retries=3` | 19 |
| NS | same two, top-level `coverage_mode=balanced`, and `coverage_mode=balanced` in both batch rows | 17 |
| Math | same two, top-level `coverage_mode=balanced`, `core_question_callback=true`, `disable_reference_fewshot=false`, and row `coverage_mode=balanced`, `disable_reference_fewshot=false` | 23 |

All absent-to-null paths and every default are enumerated in `comparisons.json`. Re-entry omits some top-level defaults from the wire, and persistence restores them identically. NS re-entry sends the two previously materialized row coverage defaults, accounting for its 62 extra JSON bytes / 78 extra equivalent GET bytes. Explicit `image_generation_mode=html` was already sent and preserved throughout.

## Rejection and cancellation

- Anonymous POST preview and generation: **401**, `Missing Authorization header`; neither starts SSE. The supervisor session stayed signed in.
- Authenticated NS payload missing `per_question_params[1].subquestion_configs[2].learning_content`: both endpoints return **422**, `code=unresolved`, with that exact path, without SSE.
- Actual math UI with the resolved row's math thinking field omitted: **422** and visible `Incomplete request: per_question_params[0].數學思考 (unresolved)`. One request, no stream/reconnect.
- Standard Pydantic rejection (`math_thinking=[]`): **422**, no generation, but only generic HTTP 422 displayed. Tracked as #787; server error details remain available.
- Legacy compatibility: a complete **3,001-byte GET** returned **200** and streamed `started`/LLM activity through the same hook. Clicking History during generation navigated away and aborted fetch without a reconnect or `done`; no leave dialog was shown for this unchanged prefilled form. [History `f658a7ef-a6c8-4f4c-b60f-e0188e6efa69`](https://examgen-staging.cpeng.me/history/f658a7ef-a6c8-4f4c-b60f-e0188e6efa69) persisted `status=aborted`. This GET was deliberately cancelled; full GET completion remains covered by #768's automated tests.

## Sentry evidence

The live frontend's `dataCollection` disables HTTP bodies, cookies, query values and gen-AI inputs/outputs. Seventy observed frontend envelopes contained neither the synthetic instruction marker nor request-body fields; the stored observations include only envelope types and booleans. Compressed replay recordings were not decoded.

Using the configured CLI token through Sentry's documented read-only APIs, the test window yielded five backend warnings and two expected frontend rejection events. None contained the test instruction/topic or a request body. The backend request entries identify POST `/api/generate` and contain no headers, cookies or query values. Frontend events contain a User-Agent header; no authentication data was exported.

The backend spans query for 07:20–08:10 UTC found 1,725 spans, including 77 with model metadata. Actual `has:` queries returned **zero** for `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.prompt`, `gen_ai.system_instructions`, and `ai.response.text`. The attribute catalog lists built-in names regardless of collected values, so its names alone are not treated as evidence. Legacy transaction-detail lookups returned 404; the privacy findings use actual error events and span-presence queries instead.

[EXAM-GENERATION-API-STAGING-J](https://cpengme.sentry.io/issues/7730828215/) contains five `llm_exchanges insert failed:` warnings between 07:28:54 and 07:34:42 UTC. There is no exception type/stack and no backend release tag. A timed-out future is a hypothesis; eventual exchange loss is unproven. Follow-up #789 requests diagnosis without logging content. These warnings did not prevent the observed SSE or History completion.

API references: [event details](https://docs.sentry.io/api/events/retrieve-an-event-for-a-project/) and [span queries](https://docs.sentry.io/api/explore/query-explore-events-in-table-format/).

## Reproducible artifacts

- `p1-capture.json`–`p4-capture.json`: sanitized request parameters, HTTP/SSE metadata and History parameters. No auth headers/storage, prompt responses or generated question bodies.
- `capture.mjs`: browser observer. The first SS/NS observers counted `result`/empty `started`/`done` without retaining their event objects; their counts and final History independently confirm completion. Later observers retain selected content-free event objects too.
- `compare.py` → `comparisons.json`: standalone offline equality checks and exact default differences.
- `sentry-evidence.json`, `sentry-trace-evidence.json`: selected event/request metadata and span count queries; no raw Sentry events or token.
- `follow-up-pydantic-errors.md`, `follow-up-exchange-warnings.md`: filed as #787 and #789.

Run `python3 docs/research/2026-09-14-766-staging-body-transport/compare.py` to recompute the passing parameter/transport assertions. No application code, deployment, provider configuration or Sentry issue state was changed. #759 was not modified. No check remains blocked by deployment or login.
