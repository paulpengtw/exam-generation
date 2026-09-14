# #761 staging recheck — 2026-09-14 10:15–10:19 UTC

**Result: acceptance remains blocked by the advertised execute default.**

The user supplied a fresh staging sign-in link for #761. Sign-in succeeded in
ego-browser. Authentication material was excluded from saved evidence, and no
environment files, provider credentials, or deployment settings were inspected.

## Current live evidence

`GET /api/models` returned HTTP 200. Comparing its response against every
default required by #761 produced one failure:

```text
#761 live model defaults: FAIL
execute: expected 'gemini-3.1-pro-preview', received 'claude-sonnet-4-6'
```

Plan and verify are `claude-opus-4-6`; all three effort defaults are `high`;
correct model/effort are empty. Gemini is first in the allowed roster. See
[models.json](models.json) and [models-check.txt](models-check.txt).

To check the fresh form, the eight specific model/effort localStorage preferences
were backed up in this tab's sessionStorage and temporarily removed. Existing
plan and execute preferences had been `medium`. The social-studies form then
opened with `high` for both, with no model-picker changes or other form edits.
The execute picker displayed the server's Sonnet default.

Clicking `產生` opened the confirmation screen. Captured browser requests:

| Endpoint | HTTP | Plan effort | Execute effort | Model overrides |
|---|---|---|---|---|
| `/api/generate/resolve` | 200 | high | high | omitted |
| `/api/generate/preview` | 200 | high | high | omitted |

The resolver drew four subquestions, seed `452144309`. This establishes the
untouched form's resolve/preview input, **not a completed generation**. No
`/api/generate` request was submitted: the server default already fails the
required provider split, and another default run cannot prove Gemini execution.
See [browser-requests.json](browser-requests.json), [form.txt](form.txt), and
[confirmation.txt](confirmation.txt).

## Integrated tests and remaining evidence gaps

GitHub's staging head remains `ad80b9bc0af2321ad22751dcbf3e8fcc4015d7ac`.
[CI run 34827756113](https://github.com/paulpengtw/exam-generation/actions/runs/34827756113)
was rechecked through GitHub and reports successful Python and web jobs on
that commit. The preceding report records 2,167 backend tests passed / 1 skipped
and 861 web tests passed. The suites were not rerun during this recheck because
the integrated commit is unchanged and no application code changed.

The earlier [acceptance report](../README.md) and
[PR evidence](https://github.com/paulpengtw/exam-generation/pull/793#issuecomment-5662312988)
remain applicable. Its two live runs disconnected around 900 seconds, and its
exchange evidence did not prove planner thinking or Gemini's effective SDK
`reasoning_effort=high`. Source inspection at the current staging revision
still shows the planner endpoint creates its client without an observer, and
the ordinary `llm_request` event parameters omit effective effort kwargs.
Those evidence gaps cannot be resolved merely by repeating the same browser run.

Staging's provider-key setup and absence of model/effort environment overrides
have not been confirmed by the operator. The endpoint proves the effective
default mismatch; it does not establish the source of that mismatch.

## Cleanup and next requirement

All eight original preferences were restored and checked for exact equality;
the temporary sessionStorage backup was removed. See [cleanup.json](cleanup.json).
The confirmation was discarded by returning to the subject chooser, and the
task browser space was closed.

Before #761 can pass, staging must advertise Gemini for execution under the
required no-model/effort-overrides setup. Then a completed untouched-form run
and the missing planner/effective-effort evidence must be captured. #761 and
#757 remain open. No GitHub comments or issue-state changes were made in this
recheck; this addendum is saved locally for review.
