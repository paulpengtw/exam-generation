# Issue #761: staging provider-split acceptance

Date: 2026-09-14. Environment: `https://examgen-staging.cpeng.me`.

Evidence attached to [PR #793](https://github.com/paulpengtw/exam-generation/pull/793#issuecomment-5662312988).

**Result: partial pass, with live completion blocked.** Model-picker routing,
fresh-form high effort values, and an Opus adaptive-thinking verifier response
were observed. Both attempts disconnected at approximately 900 seconds. #761
and its parent should remain open.

This record distinguishes the live picker-selected provider split from the
server's advertised defaults. The user authorized selecting Gemini from the
model picker after the initial models response showed a Sonnet execute default.
No deployment settings were changed, and no provider keys or environment files
were inspected.

## Scope and setup

- Task: [#761](https://github.com/paulpengtw/exam-generation/issues/761), parent
  [#757](https://github.com/paulpengtw/exam-generation/issues/757).
- Integrated source tested: `ad80b9bc0af2321ad22751dcbf3e8fcc4015d7ac`, the staging
  merge of [#793](https://github.com/paulpengtw/exam-generation/pull/793).
- Browser: ego-browser, using the user-provided login link. Authentication
  values are excluded from these artifacts.
- Eight named model/effort localStorage preferences were backed up and
  temporarily removed to observe fresh-form defaults. The original plan/execute
  effort preferences were `medium`. A fresh form selected `high` for both.
- Only the execute model picker was changed, to `gemini-3.1-pro-preview`.
  Plan and verify model pickers retained their server defaults. Verification
  remained enabled. All other form values remained as initially displayed.

## Initial findings

`GET /api/models` returned HTTP 200 with Gemini first in the allowed roster,
plan/verify `claude-opus-4-6`, all three effort defaults `high`, and an empty
correct model/effort. Its execute default was **`claude-sonnet-4-6`**. Thus this
environment does not satisfy the ticket's exact advertised-execute-default
criterion. The cause was not established by inspecting environment variables.

The browser's resolve, preview, and generation POST requests sent
`model_execute=gemini-3.1-pro-preview`, `effort_plan=high`, and
`effort_execute=high`; model-plan/model-verify overrides were omitted.

The core-question planner endpoint returned three candidates with HTTP 200.
Its request did not include model or effort overrides. The generation stream
also emitted the start/end of batch planning. Neither fact, by itself, proves
the planner's actual provider or returned thinking content.

## Tests

- Integrated-commit [CI run 34827756113](https://github.com/paulpengtw/exam-generation/actions/runs/34827756113):
  Python **2,167 passed, 1 skipped**; web **861 passed / 105 files**. Both jobs
  completed successfully. Exact log lines are saved in `ci-summary.txt`.
- Isolated local checkout of the same commit: `npm test -- --maxWorkers=2`
  passed all **861 tests / 105 files**.
- Local `uv run --no-sync --cache-dir /private/tmp/examgen-761-uv-cache pytest -q`:
  **2,160 passed, 8 skipped**, exit 0. Playwright's executable was absent;
  local Postgres checks encountered macOS sandbox restrictions. Postgres
  cleanup also emitted ignored atexit permission errors. The integrated CI
  jobs provide the unrestricted Linux check.
- Local Python was 3.12. `choom` is unavailable on this macOS host; the web
  suite used at most two workers alongside one backend suite.

## Evidence limitations found in the integrated source

- `server/generate/routes.py::plan_core_questions_endpoint` creates a planner
  client without an exchange recorder, and
  `server/generate/subjects.py::_ss_plan_all_batch_briefs` does the same for the
  creative planning client. Planner stage start/end events therefore do not
  constitute a persisted planner exchange or proof of thinking content.
- `src/llm_client.py::_call` emits observer request parameters for output limits,
  temperature, and adaptive thinking, but does not include the effective effort
  kwargs. Gemini's recorded request parameters therefore cannot independently
  establish `reasoning_effort=high`. The browser's `effort_execute=high` is
  separate evidence of the application's input.

## Run 1: full initial form with Gemini selected

Question ID: `ss_20260914_093004_001`; seed `1924000900`.

- Generation POST started at approximately 09:30:04 UTC, returned HTTP 200,
  and emitted Gemini text-generation and per-subquestion exchanges.
- All seven resolved subquestions were assembled. Subquestion 7 needed one
  automatic retry. Seven image calls completed.
- The verifier request used `claude-opus-4-6` with
  `thinking={"type":"adaptive"}`, `max_tokens=16384`, and no temperature.
- The verifier response included **14,742 characters of reasoning**. It returned
  `answer_match=true`, `passed=false`, identifying a cognitive-process mismatch
  in the final subquestion. The pipeline began a Gemini correction.
- The connection ended with `TypeError: network error`, without a terminal
  result/done event. Browser Resource Timing reports **900,136.7 ms** for the
  generate request. The UI displayed `network error` and an unverified draft;
  `/health` still returned HTTP 200 with `{"status":"ok"}`.
- The 900.14-second duration matches Railway's documented 15-minute HTTP
  request limit. This is a strongly supported diagnosis of the disconnect,
  rather than a server-log-confirmed cause. See
  [Railway specs and limits](https://docs.railway.com/networking/public-networking/specs-and-limits).
- History subsequently saved record `797fc68d-b899-4cfa-baaa-d24345db257c`
  at 09:49:40 UTC with `status=aborted`. Its persisted seed `1924000900` and
  Gemini model override match this attempt. No successful final question was
  saved for it.

This attempt proves Gemini generation and an Opus adaptive-thinking verifier
response, but **does not prove a completed generation**.

## Run 2: bounded completion check

The retry keeps the same model/effort selections, with two explicit form changes:
`content_type=純文字` and `sub_question_count=3`. Its seed is `1996737474`.
These changes reduce image work and the number of calls so the run can finish
within the platform's HTTP limit. It is a diagnostic completion check, not an
untouched-form acceptance claim.

- Generation began at 09:49:01 UTC. Batch planning and the shared-text Gemini
  call completed. Three Gemini subquestion calls started at about 09:50:31 UTC.
- None of those three calls emitted a response before the browser connection
  ended with `TypeError: network error` at **900,141.5 ms**. No verifier or
  terminal result/done event was captured for this attempt.
- The page was visible and focused while checked. The captured subquestion
  request size was comparable to run 1 (about 176,444 versus 175,479 serialized
  message characters), and `/health` remained HTTP 200 during the wait and
  after the disconnect. The cause of the delayed Gemini responses is not
  established by the available evidence.
- History had no new matching row immediately after the second disconnect.
  Its eventual persisted status is unverified. The browser request is over;
  no third generation attempt was submitted.

## Artifacts

- `models-initial.json`: models endpoint response.
- `form-initial.txt`: initial form with previously saved effort choices.
- `form-gemini-high.txt`: fresh effort defaults plus the Gemini picker choice.
- `run-1-browser-requests.json`: browser request bodies, with no credentials.
- `run-1-stream-summary.json`: model/parameter excerpts, reasoning lengths,
  verifier verdict, stage timings, and the disconnect.
- `run-1-disconnected-ui.txt`: the UI's network error and draft state.
- `run-1-history.json`: matching persisted aborted record and input parameters.
- `run-2-confirmation.txt`: explicit settings for the shorter retry.
- `run-2-browser-requests.json`, `run-2-stream-summary.json`, and
  `run-2-disconnected-ui.txt`: the shorter retry and its 15-minute failure.
- `ci-summary.txt`, `local-web-tests.txt`, `local-backend-tests.txt`: test evidence.

The saved-exchange endpoint requires a generation-log UUID, which neither the
generation stream nor History detail exposes in this integrated source. No
UUID was guessed and no database credentials were sought. The exchange excerpts
here come from the browser's live LLM events; database persistence is unverified.

Not all original #761 acceptance criteria are satisfied, so this report does
not recommend closing #761 or its parent.

Cleanup: all eight original model/effort preferences were restored and checked
for equality with the backup. The two test pages and their task space were
closed. No application code or deployment settings were changed.
