## MODIFIED Requirements

### Requirement: Explicit generation protocol admission
New generation HTTP submissions SHALL declare the current generation protocol version, `3`, which denotes detached-run submission. A server implementing this contract SHALL reject absent or unsupported versions, including the previous streaming version `2`, with HTTP 426 before creating a run or calling a model. The rejection SHALL carry a JSON string `detail` asking the caller to refresh or update, `code: CLIENT_UPDATE_REQUIRED`, and `supported_stream_versions: [3]`. It SHALL NOT create a run, return a run identity or deliver any event for that rejection. The version SHALL be a transport parameter, not a drawable generation parameter. The independent 人工審題修正 stream SHALL retain its existing admission and format.

#### Scenario: An old tab starts a new generation
- **WHEN** a request omits the version or declares `2` on the new server
- **THEN** it receives HTTP 426 with a human-readable string `detail` and no run, worker or model call starts
- **AND** no v2 envelope is delivered to the old parser

#### Scenario: An unsupported version is requested
- **WHEN** a caller requests a protocol version other than 3
- **THEN** the server reports the supported version before creating a run and does not silently reinterpret the request

#### Scenario: Direct CLI and modification use their own interfaces
- **WHEN** a CLI invokes a subject pipeline directly or a teacher starts 人工審題修正
- **THEN** the generation HTTP version parameter does not become a CLI sampling pin or a modification-stream requirement

### Requirement: Preallocated run and question manifest
A validated execution SHALL use a unique `run_id`, using its GenerationLog UUID when one exists. At 受理, before responding and before batch planning or question work starts, the server SHALL allocate and durably record the entire manifest with immutable zero-based `index` and `question_id` values. The acceptance response SHALL return `run_id`, `protocol_version: 3`, accepted `total` and `questions: [{index, question_id}]`. A live observation stream, when offered, SHALL begin with `started` as event sequence 1 carrying the same manifest. Question IDs SHALL be `<subject_prefix><run_id>_<NNN>`, using `q_`, `ss_` or `ns_` and a one-based ordinal padded to at least three digits. A new submission SHALL receive new identities even with identical parameters, except a duplicate submission with the same submission key, which SHALL receive the original run's identities. A resumed attempt of the same run SHALL reuse its original run and question identities. All consumers SHALL treat IDs as opaque strings; existing records and image files SHALL NOT be renamed.

#### Scenario: Two questions have not produced content yet
- **WHEN** a two-question run is accepted
- **THEN** the acceptance response announces both unique IDs at indices 0 and 1 before either worker or the batch planner emits activity
- **AND** a failure before the first draft can still identify its question

#### Scenario: Identical requests are submitted in the same second
- **WHEN** the same subject and pins start two distinct executions with different submission keys
- **THEN** their run IDs, question IDs and new image-file identities differ
- **AND** direct invocations without a GenerationLog also allocate a unique run UUID

#### Scenario: A run resumes after host failure
- **WHEN** a run's host stops and another host resumes it
- **THEN** the resumed attempt keeps the same run ID and question IDs and does not allocate a new manifest

### Requirement: Independent sibling outcomes and stream closure
A terminal failure of one question SHALL NOT stop unrelated siblings from producing and delivering their results. The contract SHALL distinguish recoverable errors, per-question termination and genuinely batch-scoped failures. When a live observation stream is offered, its done event SHALL mean closure of that stream, not universal success. Closing, losing or aborting an observation stream SHALL NOT constitute cancellation and SHALL NOT stop, pause or fail the run. The stream contract SHALL NOT replay missing events. Recovery of a run's execution and of its viewable state SHALL be provided by the `generation-run` capability and its persisted run state, not by the event stream.

#### Scenario: One worker fails while another is still running
- **WHEN** A finally fails and B is still generating
- **THEN** A's terminal evidence is recorded and delivered while B continues and can deliver its own result and terminal

#### Scenario: A batch failure prevents work from starting
- **WHEN** a known batch failure prevents accepted questions from starting
- **THEN** each accepted question receives a recorded 終止原因 with a stated reason
- **AND** unconfirmed cancellation is never recorded as cancelled

#### Scenario: The observer disconnects mid-run
- **WHEN** the only live observer's connection closes while B is generating
- **THEN** B continues, and its outcome is readable from persisted run state rather than from a replayed stream
