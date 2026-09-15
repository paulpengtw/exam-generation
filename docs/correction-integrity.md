# Correction integrity

This contract applies to automatic generation and 人工審題修正 for 社會領域,
自然科學, and grouped math. The invariant is the question entering each attempt,
including an already-partial group or a group with zero surviving 小題.

## Candidate acceptance

Each public subject `correct_question` returns a question. An omitted
`subquestions` key preserves the original rows while permitting valid top-level
edits. An explicit replacement must contain exactly one object per entering row,
in its original order. Correction never fills generation gaps or samples new rows.

Before frozen metadata is restored, each row must identify its original with a
string `id`, an integer `序號`, or both. Booleans and numeric strings are invalid
ordinals. One identifier suffices only when it is unique; a pair can disambiguate
repeated original identifiers. An empty id alone supplies no identity and cannot
replace a nonempty id. Position, sorting, and renumbering cannot repair identity.

Malformed structure or editable data rejects the whole candidate, including any
otherwise-valid shared edits. Nested answers and rubrics are validated rather
than silently dropped; 社會／自然 accept both `評分規準` and `評分標準`.
Accepted candidates are detached copies. Curriculum pins, instructions, demand
assignments, interactions, image ownership, and private generation slot metadata
remain associated with their original rows. Subject-specific editable fields
remain authoritative; math's shared `文本` stays frozen. Genuine flat math keeps
its existing content and serialization contract.

The optional per-call `on_decision` callback receives an immutable
`CorrectionDecision` after candidate validation. Its `outcome` is `accepted` or
`rejected`; rejection carries a safe `{code, path, message}` reason. Provider and
parse failures retain the entering question and are never reported as accepted.
Reasons contain static diagnostics, not provider output or exception text.
Callbacks and decision state belong to the individual call.

## Automatic generation and History

A rejected attempt consumes one correction retry and emits the existing
`corrector/correct/error` stage diagnostic with its question id, retry, and safe
reason. It publishes no successful correction completion or corrected draft and
renders no discarded image specification. The retained question receives a fresh
verifier pass within the existing retry limit. A later passing verdict does not
turn the rejected attempt into an applied correction.

Existing correction-trail entries carry optional `outcome` and `reason` fields.
A rejected entry contains the retained snapshot; an accepted entry contains the
accepted candidate before re-verification. These entries travel through the
existing trail event, persistence column, and History detail API. Absent optional
fields and image payloads are omitted. No question-JSON field or migration is
needed.

Live and History timelines show 修正未採用 / Correction rejected, the safe reason
message, and the retained snapshot for a rejection. They offer no applied-change
diff for that entry. Accepted entries and legacy entries without an outcome keep
their existing display; the UI does not infer decisions for historical records.

## Manual review

Both the initial 修改 call and verifier-driven retries consume the same public
decision. Rejection retains the entire scoped snapshot entering that call and
emits a stage error instead of a successful applied completion. Accepted content
is merged only through the admitted editable paths, preserving the existing
child-version linkage and out-of-scope fields.

Rejected image-source annotations alone do not newly set `image_stale`; an
existing stale flag survives. Accepted image-source edits keep the established
stale-image behavior. Manual review uses its existing stream and child History
record, without adding the automatic-generation verification trail.

## Regression boundaries

Use controlled provider responses through the public subject correctors, actual
generation HTTP/SSE and History reads, manual-review HTTP/SSE and child History,
and rendered timeline UI. Cover retained verification, acceptance after rejection,
exhaustion, concurrent sibling isolation, and visual ownership. Sampler allowlist,
completeness, and forwarding guards protect the unchanged generation contract.
