## Parent

[#756 — Verify saved random parameters reload unchanged on staging](https://github.com/paulpengtw/exam-generation/issues/756)

## What to build

A supervisor can resolve a batch, inspect its 提示詞預覽 in 發送前確認, submit every completed parameter, and later use History / 重新帶入 without hitting a URL-length limit or losing a 釘選 value.

During the 2026-09-14 staging acceptance run, two 題組 with three 小題 each resolved successfully for both 社會領域 and 自然科學, but opening generation returned HTTP 414. The request targets were 9,489 and 9,354 bytes respectively. The natural-sciences event is [EXAM-GENERATION-WEB-STAGING-A](https://cpengme.sentry.io/share/issue/b06330758404488b8a5aadaa545cbd45/). The completed payload includes batch rows, 各小題配置, and 預抽 provenance; it must fit the transport as a whole.

Carry the structured parameters in request bodies for the web generation and 提示詞預覽 flows. Preserve existing GET callers and the shared validation, 全量預抽, streaming, and History contracts. This is a transport change within the existing request lifecycle; it does not introduce the background execution or reconnect guarantees being decided in #734.

## Acceptance criteria

- [ ] A complete batch equivalent to each observed SS/NS request passes from 發送前確認 through 提示詞預覽 and generation without HTTP 414. Exercise Chinese instructions and a payload whose equivalent encoded query exceeds the observed failing lengths.
- [ ] All three subjects use the body-based web flow. Existing supported GET callers retain their behavior, and both transports use the same validation and generation behavior.
- [ ] Every completed 題組 row and 各小題配置 row reaches generation unchanged, including seeds, curriculum selections, contexts/subcontexts, types, counts, 數學思考/核心素養/科學能力, Reporting Scale where applicable, word limits, 出題指示, 文本出題指示, media settings, and 預抽 provenance. No field is dropped or shortened to fit the transport.
- [ ] Authentication, rate limiting, model/provider checks, and the field-addressed HTTP 422 completeness/conflict gate remain enforced before generation. Incomplete requests do not gain an implicit draw at this boundary, consistent with ADR 0019 and ADR 0022.
- [ ] Submission starts one generation request and preserves existing SSE events, abort/error handling, and persistence behavior. Changing transport does not introduce duplicate generation or new recovery semantics.
- [ ] History stores the complete submitted parameters. Reloading an SS/NS test record unchanged produces no fresh draw of a saved value and preserves the complete batch through the new transport. Record exact field comparisons; distinguish default serialization differences from changed values.
- [ ] Automated browser/client-to-HTTP checks cover a large complete payload, both transport variants, validation rejection, and saved-parameter reload. A staging smoke through the deployed proxy verifies the previously failing SS/NS payload sizes and records the deployment, statuses, and History identifiers without authentication data.
- [ ] Request bodies and generated content remain excluded from Sentry collection under ADR 0004.

## Blocked by

- None (can start immediately).
