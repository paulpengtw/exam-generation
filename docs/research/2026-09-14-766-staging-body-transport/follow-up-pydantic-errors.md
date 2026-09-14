Found during #766 live acceptance of #762 on staging release `8941814b7973428a485d39c1a5d2b90fd52ddcad` (2026-09-14).

The new POST generation endpoint correctly rejects invalid parameters before starting SSE, but the UI loses standard Pydantic validation details. A rejected nested `math_thinking: []` request displays only `Stream open failed: HTTP 422`, despite the response explaining that `per_question_params[0].math_thinking` must contain 1–3 values.

Reproduction through the real UI:

1. Resolve a valid single math question and open 發送前確認.
2. In a browser test, replace only `per_question_params[0].math_thinking` in the outgoing POST JSON with `[]`.
3. Submit once. `/api/generate` returns 422; no SSE `started`, generation, or reconnect occurs.
4. The displayed error is the generic HTTP 422 string. Reading the same payload's response directly returns a standard Pydantic `detail` array containing `type`, `loc`, and `msg`.

Control: deleting that field instead invokes the completeness gate. Its `{field, code}` response displays `Incomplete request: per_question_params[0].數學思考 (unresolved)` correctly. Thus canonical resolver errors work; the missing case is the Pydantic error format.

`formatHttpErrorDetail` in the deployed `web/src/hooks/useGenerate.ts` accepts strings or arrays containing `{field, code}` and returns null for standard `{loc, msg, type}` entries. The POST body-validation path now exposes that case. Related prior work: #315 / #351.

Expected: show a concise useful field/message for standard Pydantic errors, retaining the existing canonical-field, string, non-JSON fallback and 401 behavior. Do not display or report Pydantic's `input`/`ctx` payload in Sentry.

Acceptance: a client-to-HTTP check submits a malformed nested body, asserts the field/message is visible, and verifies one rejected request starts no generation or reconnect. Include both standard Pydantic and resolver error arrays.

This is a focused follow-up; large-body transport, canonical completeness rejection and History preservation passed their live checks. No application code was changed during acceptance.
