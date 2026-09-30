## MODIFIED Requirements

### Requirement: Uniform envelopes and complete event attribution

Every v2 generation event SHALL carry JSON data shaped as `{context, payload}`, with `context.run_id` and a run-wide `event_seq` increasing from 1 in send order. Resending the same event SHALL retain its sequence. Question-scoped events SHALL additionally carry matching `question_id` and `index`; 小題-scoped events SHALL carry `subquestion_index`; work and call events SHALL carry their applicable `operation_id` and `call_id`. Batch planning, batch start/end and textual progress SHALL retain batch scope. Timestamps, role names, proximity and ID string parsing SHALL NOT establish attribution. Any repeated identity inside payload SHALL match context. `result.payload` SHALL remain the complete question object whose `id` equals context.question_id.

#### Scenario: Concurrent questions use the same Agent role
- **WHEN** A and B both emit `stage` and LLM events for `sub_generator#1`
- **THEN** their question and 小題 context distinguishes every event, including text chunks, requests, responses, failures and retries
- **AND** the Agent role itself remains a role rather than being rewritten to contain a question UUID

#### Scenario: All generation event families use the contract
- **WHEN** the server emits started, pipeline, plan, stage, LLM request/thinking/content/response, observable call failures, model-switch notifications, question_update, any trail, result, error, done or progress
- **THEN** each event has the appropriate complete envelope and scope
- **AND** textual progress remains a batch log string within payload and supplies no phase evidence

#### Scenario: Results are persisted and rendered
- **WHEN** a result passes through storage or a question card
- **THEN** only its question payload enters the question-shaped data flow
- **AND** transport envelopes and full operational trails are not stored inside the exam artifact
