# #787 validation-error verification

Verified on 2026-09-14 with ego-browser TaskSpace 13. The staging reproduction used the supplied supervisor session. The fix was checked against a local Vite frontend and the real FastAPI application from `codex/787-validation-details`, based on staging commit `850c455`, with an isolated SQLite database and test account. The fix has not been deployed to staging.

## Reproduction and cause

One staging UI submission changed only the resolved `per_question_params[0].math_thinking` to `[]`. It returned HTTP 422 with JSON, showed `Stream open failed: HTTP 422`, and did not open SSE or reconnect.

The response was a standard Pydantic detail array, but its location was only `["body"]`: the batch validator had stringified the nested ValidationError. Its message included the nested field, diagnostic URL, and `input_value=[]`. Merely displaying this message would expose input values through frontend error reporting.

The fix preserves the nested validation locations in the backend and formats only `loc` and `msg` in the frontend. It does not copy Pydantic `input` or `ctx` into the displayed/reported error.

## Browser checks

| Submitted change | Visible result | HTTP / History |
| --- | --- | --- |
| `per_question_params[0].math_thinking = []` | `Invalid request: per_question_params[0].math_thinking: Value error, math_thinking must contain 1 to 3 values` | One POST, 422 JSON, no reconnect, History total 0 |
| Remove `per_question_params[0].math_thinking` | `Incomplete request: per_question_params[0].數學思考 (unresolved)` | One POST, 422 JSON, no reconnect, History total 0 |

Both checks followed the real form → resolve → 發送前確認 → 確定發送 flow. The browser observer changed the outgoing generation body, leaving the API response untouched. Neither response was an SSE stream. Observations were collected again after the normal reconnect interval.

During local control setup, two separate requests were rejected by missing image/Gemini configuration before reaching the completeness gate. Their string messages are recorded in `resolver.json`; an initial observer wrongly assumed every detail was an array and was corrected. Local placeholder provider settings then allowed admission; external provider SDK calls were disabled in the temporary QA harness. These setup steps did not change application code.

- [Pydantic screenshot](pydantic-error.png), [sanitized HTTP evidence](pydantic.json)
- [Resolver screenshot](resolver-error.png), [sanitized HTTP evidence](resolver.json)

No authentication tokens, request headers, raw input/ctx, or generated question content are stored here.

## Automated verification

The agreed seam is client → HTTP, as specified by #787. Frontend coverage uses the real fetch-event-source client and SSE parser with an HTTP test server; backend coverage uses real FastAPI validation, authentication, and History against an isolated database. Sentry is replaced only at its external capture boundary.

TDD cycle 1: the new malformed-body client test failed with the generic HTTP 422 message, then passed after the formatter change. Cycle 2: the backend test failed with only `loc=["body"]`, then passed after preserving nested errors. The backend test also covers two invalid fields, input isolation, and absence of History writes.

- `npm test -- src/api/generate-transport.test.tsx src/hooks/useGenerate.test.ts --maxWorkers=1`: 56 passed. Includes existing resolver/string/non-JSON/401 behavior, plus no reconnect after 1.1 seconds and exact Sentry error/context checks with private input/ctx sentinels.
- `.venv/bin/python -m pytest tests/server/test_generate_body_transport.py tests/server/test_per_question_params.py tests/test_generation_sampler_allowlist.py -q`: 67 passed. One existing Sentry SDK deprecation warning.
- `npm run build`: passed; bundle-size advisory remains.
- Changed-file ESLint, Ruff, and `git diff --check`: passed.

An independent review agent could not run because its usage limit was reached. The diff was inspected locally instead.
