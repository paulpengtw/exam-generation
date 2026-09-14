# generation-event-protocol Specification

## Purpose

Define the generation stream contract that lets clients attribute concurrent work, content revisions and terminal evidence to the correct question across math, social studies and natural sciences. Preserve question-shaped artifacts while making unsupported clients and incomplete evidence explicit.

## Requirements

### Requirement: Explicit generation protocol admission
New generation HTTP requests SHALL declare `stream_version=2`. A server implementing this contract SHALL reject absent or unsupported versions with HTTP 426 before dispatching generation work or calling a model, returning a JSON string `detail` that asks the caller to refresh or update, `code: CLIENT_UPDATE_REQUIRED`, and `supported_stream_versions: [2]`. It SHALL NOT start a run or emit an SSE acknowledgement for that rejection. The version SHALL be a transport parameter, not a drawable generation parameter. The independent 人工審題修正 stream SHALL retain its existing admission and format.

#### Scenario: An old tab starts a new generation
- **WHEN** a request omits `stream_version` on the new server
- **THEN** it receives HTTP 426 with a human-readable string `detail` and no worker or model call starts
- **AND** no v2 envelope is delivered to the old parser

#### Scenario: An unsupported version is requested
- **WHEN** a caller requests a stream version other than 2
- **THEN** the server reports the supported version before generation and does not silently reinterpret the request

#### Scenario: Direct CLI and modification use their own interfaces
- **WHEN** a CLI invokes a subject pipeline directly or a teacher starts 人工審題修正
- **THEN** the new generation HTTP version parameter does not become a CLI sampling pin or a modification-stream requirement

### Requirement: Preallocated run and question manifest
A validated execution SHALL use a unique `run_id`, using its GenerationLog UUID when one exists. Before batch planning or question work starts, the server SHALL allocate the entire manifest with immutable zero-based `index` and `question_id` values, and emit `started` as event sequence 1 with `protocol_version: 2`, accepted `total` and `questions: [{index, question_id}]`. Question IDs SHALL be `<subject_prefix><run_id>_<NNN>`, using `q_`, `ss_` or `ns_` and a one-based ordinal padded to at least three digits. A new submission SHALL receive new identities even with identical parameters. All consumers SHALL treat IDs as opaque strings; existing records and image files SHALL NOT be renamed.

#### Scenario: Two questions have not produced content yet
- **WHEN** a two-question run is accepted
- **THEN** started announces both unique IDs at indices 0 and 1 before either worker or the batch planner emits activity
- **AND** a failure before the first draft can still identify its question

#### Scenario: Identical requests are submitted in the same second
- **WHEN** the same subject and pins start two distinct executions
- **THEN** their run IDs, question IDs and new image-file identities differ
- **AND** direct invocations without a GenerationLog also allocate a unique run UUID

### Requirement: Program controlled subquestion identity
For a 題組, normalized 各小題配置 and any padded or truncated plan SHALL announce the fixed zero-based `subquestion_index`, `id: <question_id>-sq<NNN>` and `序號: subquestion_index + 1` before the corresponding work starts. Model-supplied IDs and ordinals SHALL NOT control routing. Retries and corrections SHALL preserve existing slots; dropping a 小題 SHALL NOT renumber survivors or move its image to another slot. Flat math SHALL have no fictitious 小題 identity.

#### Scenario: The model changes ordinals and a middle slot fails
- **WHEN** configured slots 0, 1 and 2 receive arbitrary model IDs and slot 1 is dropped
- **THEN** program-controlled IDs override model IDs and surviving ordinals remain 1 and 3
- **AND** plan, content, missing-item evidence and images refer to the same fixed slots

### Requirement: Uniform envelopes and complete event attribution
Every v2 generation event SHALL carry JSON data shaped as `{context, payload}`, with `context.run_id` and a run-wide `event_seq` increasing from 1 in send order. Resending the same event SHALL retain its sequence. Question-scoped events SHALL additionally carry matching `question_id` and `index`; 小題-scoped events SHALL carry `subquestion_index`; work and call events SHALL carry their applicable `operation_id` and `call_id`. Batch planning, batch start/end and textual progress SHALL retain batch scope. Timestamps, role names, proximity and ID string parsing SHALL NOT establish attribution. Any repeated identity inside payload SHALL match context. `result.payload` SHALL remain the complete question object whose `id` equals context.question_id.

#### Scenario: Concurrent questions use the same Agent role
- **WHEN** A and B both emit `stage` and LLM events for `sub_generator#1`
- **THEN** their question and 小題 context distinguishes every event, including text chunks, requests, responses, failures and retries
- **AND** the Agent role itself remains a role rather than being rewritten to contain a question UUID

#### Scenario: All generation event families use the contract
- **WHEN** the server emits started, pipeline, plan, stage, LLM request/thinking/content/response, observable call failures, question_update, any trail, result, error, done or progress
- **THEN** each event has the appropriate complete envelope and scope
- **AND** textual progress remains a batch log string within payload and supplies no phase evidence

#### Scenario: Results are persisted and rendered
- **WHEN** a result passes through storage or a question card
- **THEN** only its question payload enters the question-shaped data flow
- **AND** transport envelopes and full operational trails are not stored inside the exam artifact

### Requirement: Work attempts and application calls have distinct identities
Each concrete work attempt SHALL have a run-unique opaque `operation_id`; each application-issued LLM call SHALL have a run-unique opaque `call_id` belonging to that operation. Starts, ends and errors SHALL identify the work they describe. Retrying JSON extraction through a fresh application call SHALL change call_id but retain operation_id; regenerating a 小題 SHALL change operation_id while preserving its slot. Verification, correction, re-verification and distinct image-processing attempts SHALL use distinct operations. Retry causality SHALL explicitly identify the superseded operation or preceding call where applicable. Invisible SDK retries SHALL NOT be fabricated as application calls.

#### Scenario: JSON retry is followed by full slot retry
- **WHEN** call C1 returns invalid JSON, call C2 retries within operation O1, and the whole slot later retries as O2
- **THEN** C1 and C2 remain separate calls under O1, O2 receives fresh calls, and the parent question and slot stay fixed
- **AND** delayed O1 events cannot stand in for O2

#### Scenario: Independent operations overlap
- **WHEN** one question has two 小題 operations and an image operation active together
- **THEN** all three have separate identities and ending one does not end the others

### Requirement: Immutable content revisions and versioned review evidence
Each question SHALL have a server-assigned `content_revision` starting at 1 and increasing when actual content changes. The same revision SHALL identify the same immutable full snapshot. Changes to question text, answers, 小題, visual specifications or actual images SHALL advance the revision; transport encoding, export annotations, progress state and review verdicts alone SHALL NOT. `question_update` and `result` SHALL carry `context.content_revision`; content-specific review/correction evidence SHALL explicitly identify its target revision. The transport revision SHALL NOT be inserted into the question payload. Promoting unchanged content from draft to final SHALL NOT require a new revision. A review conclusion SHALL apply only to the content and images actually inspected at its stated revision.

#### Scenario: Images change after review
- **WHEN** revision 3 was reviewed and a changed image is committed with revision 4
- **THEN** revision 4 cannot inherit revision 3's verdict merely because the text stayed the same

#### Scenario: Verdict and export metadata change without content changes
- **WHEN** a review finishes or an export adds its own markers to an unchanged question
- **THEN** the question retains its content revision and export changes do not mutate it

### Requirement: Explicit immutable terminal evidence per question
Every normally ended question, final failure or confirmed cancellation SHALL emit one authoritative `question_terminal` summary. Its envelope SHALL identify the question, and payload SHALL include `termination_reason: normal|failed|cancelled`, `has_final`, `final_revision` (positive when true, null when false), `delivery_status: complete|partial|none|unknown`, fixed-identity `expected`, `delivered`, `missing` evidence, and `review` with `status: passed|failed|skipped|unknown` and `content_revision`. A definitive verdict or explicit skip in this summary SHALL refer to the final revision; absent matching evidence or absent final SHALL yield unknown, without presenting an old draft's verdict as a final verdict. Required images SHALL include explicitly requested or pipeline-adopted visual slots; renderer selection alone SHALL NOT create an image requirement. Unknown evidence SHALL include an explicit reason. Repeated delivery SHALL preserve the same summary; contradictory summaries SHALL NOT be treated as updates. `question_end`, empty activity sets, final and batch done SHALL NOT substitute for this summary. After termination the execution SHALL NOT start new work or publish a different final revision; delivery of the already-declared final remains allowed.

#### Scenario: A retryable call fails
- **WHEN** an application call fails but the slot or question can still retry
- **THEN** it emits attributable call/work evidence without prematurely terminating the parent question

#### Scenario: A question fails before producing final
- **WHEN** the server knows that A has finally failed without final content
- **THEN** A's terminal summary states failed, has_final false, final_revision null and delivery none
- **AND** any existing draft remains available separately from the absence of final

#### Scenario: A final has missing required content
- **WHEN** final content lacks an expected 小題 or a required image
- **THEN** the terminal summary states partial and identifies the actual missing slots
- **AND** a configured rendering backend alone does not create a required-image obligation

#### Scenario: Only the shared text survives
- **WHEN** no 小題 survives but the 題組 has final shared 文本
- **THEN** final remains a 題組 with partial delivery and explicit missing 小題, rather than losing its 文本

#### Scenario: Review is skipped or exhausted
- **WHEN** skip-verify is explicit or retries end with a failed review
- **THEN** review states skipped or failed respectively, at the relevant final revision, without claiming a pass
- **AND** absent review evidence states unknown

### Requirement: Independent sibling outcomes and stream closure
A terminal failure of one question SHALL NOT stop unrelated siblings from producing and delivering their results. The stream SHALL distinguish recoverable errors, per-question termination and genuinely batch-scoped failures. Batch done SHALL follow draining the generation events for settled workers and SHALL mean stream closure, not universal success. A disconnect or client abort SHALL NOT constitute proof of cancellation. The contract SHALL NOT automatically retry generation, replay missing events or promise execution recovery.

#### Scenario: One worker fails while another is still running
- **WHEN** A finally fails and B is still generating
- **THEN** the server delivers A's attributable terminal evidence while B continues and can deliver its own result and terminal

#### Scenario: A batch failure prevents work from starting
- **WHEN** a known batch failure prevents accepted questions from starting
- **THEN** the server provides per-question terminal evidence for outcomes it can actually establish
- **AND** it does not replace unknown outcomes or unconfirmed cancellation with inferred terminal summaries
