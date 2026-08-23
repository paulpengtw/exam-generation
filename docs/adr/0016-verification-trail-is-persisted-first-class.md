# verification trail is persisted first-class, sibling to the question

## Context

Generation runs each question through a 驗證/修正 loop. At generation time,
verdicts and resulting question snapshots are already parsed and typed; a run
must retain every 驗證 verdict and every 修正 pass, including the resulting
snapshot when 驗證 passes first try. The record is observability about the run,
distinct from the exportable question artifact.

## Decision

We make the verification trail a first-class per-question record captured at
generation time, where verdicts and snapshots are already parsed and typed. We
never reconstruct it at read time from LLM exchange rows: doing so would
duplicate JSON-extraction logic and could silently break when prompt formats
shift.

We store it as a sibling of the question in its own column, never inside the
exportable question JSON. The code identifier for this record is
`verification_trail`; its verification entries are the spine of the trail, with
corrections hanging off the corresponding entries. The trail is observability
about the run, not part of the exam artifact teachers download.

## Consequences

Every question has a persisted verification/correction history, even when
verification passes first try, so reads can expose a stable run record without
replaying or reinterpreting model exchanges. Generation owns the parsing
boundary and the trail schema, while exports remain question-shaped and do not
carry operational history. Persistence and any read paths that intentionally
expose the trail must handle the additional first-class column.

## Explicitly Rejected Alternatives

Reconstructing the trail from `ExchangeRecorder` rows was rejected because it
would duplicate JSON-extraction logic at read time and silently break when
prompt formats shift. Embedding `correction_trail` inside question JSON was
rejected because the trail is observability about the run, not part of the exam
artifact teachers download.
