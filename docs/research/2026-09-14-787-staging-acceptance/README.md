# #787 staging acceptance — passed

Verified 2026-09-14 16:38–16:40 Asia/Taipei with ego-browser TaskSpace 14 and the existing supervisor session. PR #791 merged to staging at 08:34:38 UTC. Deployment 6433367393 succeeded at 08:36:47 UTC. The actual frontend asset `/assets/index-BnnhL0dA.js` reported release `07fe50a3ccadffe49d29ad808266d7c778fa582e`, matching the merge commit. Both PR CI jobs (Python and web) succeeded.

Each check used the real form → resolve → 發送前確認 → 確定發送 path. A browser observer changed only the outgoing generation body's `per_question_params[0].math_thinking`; API responses were unchanged.

| Change | Visible UI message | Result |
| --- | --- | --- |
| Set to `[]` | `Invalid request: per_question_params[0].math_thinking: Value error, math_thinking must contain 1 to 3 values` | One POST, 422 JSON |
| Delete field | `Incomplete request: per_question_params[0].數學思考 (unresolved)` | One POST, 422 JSON |

Exactly two generation requests were observed in total through 08:40:03 UTC, more than one minute after submission. Neither opened an SSE stream or reconnected. History total remained 51 before and after both checks.

The browser's wait for the second message timed out, but subsequent inspection found the expected message and response already present; no repeat submission was made. Screenshots confirm both errors are visible.

[evidence.json](evidence.json) contains only selected HTTP error fields, release/asset, timing, UI messages and History counts. No tokens, headers, raw Pydantic input/ctx, or generated question content are retained. The fetch observer captured no Sentry envelopes; it makes no claim about live telemetry. Input/ctx exclusion is covered by PR #791's passing automated Sentry-boundary checks.

- [Pydantic error](pydantic-error.png)
- [Resolver error](resolver-error.png)

No application code or deployment configuration was changed during acceptance.
