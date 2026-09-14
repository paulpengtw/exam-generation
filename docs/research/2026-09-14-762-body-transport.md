# #762: complete 預抽 batches over request bodies

The web client sends generation and 提示詞預覽 parameters as POST JSON at
`/api/generate` and `/api/generate/preview`. The existing `GenerateParams` wire
contract is unchanged, including JSON-string batch/configuration fields. GET
remains supported. Both transports share configuration admission, completeness,
prompt assembly and the existing SSE/persistence lifecycle. Legacy GET keeps its
configuration admission errors ahead of subject-specific model validation.

## Automated evidence

The public test boundaries were confirmed by the user: HTTP endpoints, web
submission/streaming/cancellation, and History save/reload. Each transport fix
followed a failing test and minimal implementation. The original frontend calls
reproduced HTTP 414 against a real HTTP server enforcing an 8,192-character URL
limit; the POST calls pass with the full payload unchanged. The hook uses the
real fetch-event-source client and SSE parser in these tests.

The backend tests use real authentication, SQLite, subject pipelines, SSE and
History endpoints; only the external OpenAI SDK is stubbed. Both transports
generate two SS/NS 題組 with three 小題 each, retrieve all submitted values via
History, resolve saved parameters with an empty `drawn` result, compare the
complete payload, and generate it again successfully.

| Fixture with the test's Chinese text instruction | Equivalent GET target | JSON body (UTF-8) |
| --- | ---: | ---: |
| 社會領域 | 27,281 bytes | 12,339 bytes |
| 自然科學 | 26,132 bytes | 11,780 bytes |

Measurements use `urllib.parse.urlencode(payload, doseq=True)` and
`json.dumps(payload, ensure_ascii=False)` on the checked-in fixtures plus the
instruction in the History test. They exceed the observed 9,489/9,354-byte
staging failures. JSON encoding whitespace can change the body length.

Exact History comparisons retain every submitted value. Existing serialization
adds `image_generation_mode="html"` and `coverage_mode="balanced"` to batch rows.
Resolving a saved request can expand absent fields to null defaults and reorder
JSON-string object keys. Comparisons decode the two JSON-string fields and omit
only null additions; list order, non-null values, seeds and provenance must match.

Additional checks cover all three web subjects, one submission/one stream,
cancellation, HTTP rejection without retry, authentication, shared GET/POST rate
allowances, model/provider/effort admission, malformed batches, and nested
unresolved/incompatible-parent 422 errors. A real Sentry preview transaction is
captured locally and checked for absence of both request data and a marker carried
in the request and prompt; collection settings remain unchanged under ADR 0004.

Tests: `tests/server/test_generate_body_transport.py` and
`web/src/api/generate-transport.test.tsx`, alongside the existing route, provider,
effort, cancellation, preview, History-prefill, Sentry and 全量預抽 guard suites.

## Separate live acceptance

The user assigned deployed staging verification to another agent via
[#766](https://github.com/paulpengtw/exam-generation/issues/766), blocked on #762
being merged and deployed. That ticket requires ego-browser, a hard refresh,
the deployed release identifier, actual 發送前確認 and History → 重新帶入 flows,
proxy statuses, exact parameter comparisons and sanitized History identifiers.
The automated results above do not claim that live staging acceptance has run.
