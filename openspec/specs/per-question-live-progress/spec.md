# per-question-live-progress Specification

## Purpose

Let teachers inspect the true activity, received content and terminal outcomes of each question in a concurrent batch. Preserve useful results when event evidence is incomplete, without inferring identity, success, cancellation or review conclusions from unrelated events.

## Requirements

### Requirement: Stream mode is validated once per request
The client SHALL enable per-question live progress only after validating a v2 started manifest, including supported protocol version, run identity, unique IDs, contiguous valid indices and accepted total. Each submission SHALL have a separate connection generation so old callbacks cannot bind a new run. A recognized legacy start SHALL select a legacy reader; unknown protocol versions SHALL stop decoding and receiving the unsupported stream, retain received content and report uncertainty without automatic resubmission. Missing started SHALL NOT be reconstructed from other events. Presentation degradation SHALL NOT switch a v2 stream's remaining bytes into the legacy parser.

#### Scenario: Valid v2 starts a batch
- **WHEN** started passes all manifest checks for N questions
- **THEN** the client creates N fixed-position compact cards initially showing 等待生成

#### Scenario: A stale connection delivers started
- **WHEN** a previous request's callback delivers started or later events after a new submission
- **THEN** it does not change the new run, cards, activity or counts

#### Scenario: Unknown protocol or absent manifest
- **WHEN** the protocol is unsupported or started is missing
- **THEN** no per-question live activity or full-batch placeholder manifest is invented
- **AND** unsupported protocol reception stops without a new generation request; a missing manifest can only be awaited within the bounded event policy

### Requirement: Received contents retain stable identity and position
For v2, cards SHALL be keyed by run and question identity and positioned only by the validated manifest. Draft, image, corrected and final snapshots SHALL update the same card without using final arrival order or an identity-or-index match. A lower content revision SHALL NOT overwrite a newer received revision. A terminal summary's final revision SHALL constrain which subsequent content can fill its final position. A card with only shared 文本 SHALL retain the 題組 layout.

#### Scenario: B finishes before A
- **WHEN** A has a draft at index 0 and B delivers final at index 1 before A finishes
- **THEN** B stays in the second card and A's draft remains in the first card

#### Scenario: Older content arrives after newer content
- **WHEN** revision 2 arrives after revision 3 of the same question
- **THEN** it cannot replace revision 3 or acquire revision 3's review conclusion

### Requirement: Processing delivery review and receipt remain separate
Each card SHALL separately represent processing (`waiting`, `running`, `ended`, `unknown`), termination reason when established, delivery completeness (`complete`, `partial`, `none`, `unknown`), review (`passed`, `failed`, `skipped`, `unknown`) and received content (`none`, `draft`, `final`). Normally ended processing SHALL permit partial delivery or failed review. Only explicit terminal evidence SHALL establish ended processing; final content alone SHALL remain inspectable and downloadable without that inference.

#### Scenario: Final arrives without terminal
- **WHEN** final is received but the stream ends without its question_terminal
- **THEN** the final stays available and processing becomes unknown rather than successful

#### Scenario: Terminal precedes its final
- **WHEN** terminal declares final revision 5 but revision 5 has not arrived
- **THEN** the card records ended processing and final-result information as pending receipt
- **AND** if the stream ends first it displays 結果未收到 rather than asserting the backend produced no result

#### Scenario: Old draft is shown while final is pending
- **WHEN** a card displays draft revision 3 and terminal describes reviewed final revision 5
- **THEN** the revision 5 verdict is labeled as information about the pending final and is not applied to revision 3

#### Scenario: Matching final arrives after terminal
- **WHEN** declared final revision 5 arrives after its terminal
- **THEN** it fills the content without reopening processing or increasing the ended count again

#### Scenario: No final exists but a draft was received
- **WHEN** terminal explicitly states has_final false and the card has draft content
- **THEN** the card distinguishes 無結果 from its preserved downloadable draft

### Requirement: Live activity uses actual work sets
Per-question activity SHALL be derived from identified work operations and summarized by 生成步驟, with counts for concurrent operations and optional expansion into 小題, attempts and calls. Call text SHALL be separated by run, call_id and channel. Superseded work and delayed events SHALL remain attached to their original records, not terminate new work. Empty active sets SHALL NOT terminate a question or imply a later step. Non-applicable or unobserved steps SHALL NOT appear as completed; trace attribution SHALL NOT force expansion of hundreds of lanes.

#### Scenario: Multiple operations overlap
- **WHEN** a 題組 has two active 小題 operations and one image operation
- **THEN** its compact activity can state 小題生成 × 2 and 圖片生成 × 1 without conflating the operations

#### Scenario: Old attempt ends after a replacement starts
- **WHEN** O2 supersedes O1 and O1's end or text arrives late, even with a larger event_seq
- **THEN** O2 remains active and O1 text stays in O1's original call record

#### Scenario: No current activity is reported between operations
- **WHEN** all known operations end but no question terminal exists
- **THEN** processing remains running without portraying an ended operation as still active or inventing the next step

#### Scenario: Optional or inapplicable steps are absent
- **WHEN** flat math has no 小題 pipeline, no image is generated, or verification is explicitly skipped
- **THEN** the interface does not fabricate 小題 work, completed image work or a passed review

### Requirement: Batch counts are unique terminal and receipt counts
The primary batch count SHALL read 已結束 X/N 題, with N fixed by the accepted manifest and X counting unique questions with undisputed terminal evidence of normal ending, failure or confirmed cancellation. A separate count SHALL state 收到最終結果 Y 題 for unique received final results. Drafts, retries, operations, duplicate events and pending final bodies SHALL NOT inflate either count. Completeness and review classifications SHALL remain separate; 100 percent SHALL mean all processing ended, not that every result is complete or passed.

#### Scenario: Mixed outcomes in four questions
- **WHEN** A has complete passed final and terminal, B has partial failed-review final and terminal, C has a failed no-final terminal plus draft, and D has final without terminal
- **THEN** the batch displays 已結束 3/4 題 and 收到最終結果 3 題
- **AND** C's downloadable draft does not increase Y and D stays processing-unknown at closure

#### Scenario: Retries and repeated final arrive
- **WHEN** a 小題 retries or the same question's final and terminal are redelivered
- **THEN** the batch denominator and unique ended/received counts do not grow

### Requirement: Bounded ordering and idempotent event acceptance
The client SHALL deduplicate by `(run_id, event_seq)` and SHALL distinguish identical redelivery from conflicting reuse. It SHALL buffer out-of-order events from the first gap, with limits of 2 seconds, 256 pending events or 4 MiB of pending data, degrading when any limit is reached or closure leaves an unresolved gap. A large normally ordered body SHALL NOT be rejected as a pending-buffer overflow. Limits SHALL only bound waiting and memory, never infer a backend outcome. A fully repaired gap within limits SHALL allow ordered processing. Unknown event kinds with valid envelopes SHALL account for their sequence but only be logged, not advance activity or results.

#### Scenario: Out-of-order events are repaired within bounds
- **WHEN** seq 12 arrives before seq 11 and seq 11 arrives before any limit is reached
- **THEN** both are applied once in sequence order and activity follows the complete evidence

#### Scenario: A gap exceeds any bound
- **WHEN** a gap lasts 2 seconds, retains 256 events, or retains 4 MiB, whichever occurs first
- **THEN** unsupported live activity stops and the interface reports incomplete event information
- **AND** because a global sequence gap cannot reliably name an affected question, live activity degrades for the batch while independently valid results and terminal summaries remain usable

#### Scenario: A missing earlier event arrives after degradation
- **WHEN** a smaller unseen seq later contains independently valid versioned content or terminal evidence
- **THEN** it can clarify that content or conclusion without being discarded solely for its smaller sequence
- **AND** the run does not automatically claim an intact activity stream again or request replay

#### Scenario: Duplicate or unknown events arrive
- **WHEN** an identical seq is redelivered or an unknown kind has a valid envelope
- **THEN** text and counts are not duplicated, unknown kinds do not advance state, and neither is treated as proof of termination

### Requirement: Incomplete and conflicting evidence is isolated
Missing attribution, inconsistent manifest/payload identity, mixed raw events inside v2, conflicting reuse of a sequence, different contents under one revision and contradictory terminal summaries SHALL NOT be repaired by timestamps, adjacency, role names or last-arrival-wins. The client SHALL retain previously received content, isolate conflicting data, state the affected uncertainty and restrict degradation to identifiable affected questions or conclusions; unlocatable attribution defects SHALL disable batch live attribution. Incomplete unpaired content SHALL NOT overwrite a versioned snapshot or earn v2 final/terminal status. A disputed terminal SHALL not count in X; a review-only conflict SHALL not remove otherwise undisputed terminal evidence.

#### Scenario: Two summaries disagree on termination
- **WHEN** the same question receives contradictory terminal evidence
- **THEN** its content remains, its disputed processing conclusion becomes unknown and it is excluded from X
- **AND** an unaffected sibling's terminal and content remain authoritative

#### Scenario: Only review conclusions conflict
- **WHEN** two conclusions disagree for the same content revision but processing termination is consistent
- **THEN** review becomes unknown while ended processing and X remain intact

#### Scenario: A raw legacy result appears inside v2
- **WHEN** a v2 stream contains a raw unversioned result
- **THEN** it does not switch parsers or replace existing versioned content and is identified as unpaired information

### Requirement: Legacy evidence remains useful without new claims
When a new client receives a recognized old-server stream, it SHALL retain the batch using aggregate activity/logs and explicitly state 此批無每題即時進度. Received content SHALL be keyed by connection and opaque question ID. Only consistent explicit index-to-ID evidence SHALL establish original order; unknown order SHALL be labeled 原題序未知, not inferred from IDs or final arrival. No full manifest placeholders SHALL be invented. Legacy final SHALL contribute only to unique received-result evidence, not new terminal conclusions; a total derived only from the request SHALL be labeled as the requested total. The client SHALL NOT automatically resubmit this already-started batch.

#### Scenario: New frontend reaches an old backend
- **WHEN** old started, interleaved unscoped activity, A's indexed draft and B's unindexed final arrive
- **THEN** aggregate activity and both contents remain visible, B cannot overwrite A, and B's original order stays unknown until explicitly established

#### Scenario: Legacy done follows final
- **WHEN** a legacy stream closes after delivering content without per-question terminal evidence
- **THEN** content remains available and unsupported processing conclusions are unknown rather than inferred from done

### Requirement: Closure and shared surfaces preserve truthful state
At stream closure or unexpected disconnection, the client SHALL retain received contents and established terminal facts, mark unestablished outcomes unknown, and stop activity indicators without a trustworthy source. Client abort SHALL NOT mean confirmed cancellation; intentional clear SHALL preserve its existing clearing and confirmation semantics. The progress bar, ProgressLog and cards SHALL derive coherent counts and conclusions from the same normalized evidence. Shared 人工審題修正 components SHALL retain their distinct stream handling, selection/qualification rules and result/error association, alongside existing localization, accessibility, reduced-motion and masking rules.

#### Scenario: Connection ends during generation
- **WHEN** A has a terminal and B only has a draft when the connection is lost
- **THEN** A retains its conclusion, B's content remains with unknown processing, and no unsupported running animation continues
- **AND** the interface does not claim cancellation or offer automatic execution recovery

#### Scenario: Shared components render modification activity
- **WHEN** a teacher submits 修改指示 and the separate modification run proceeds through 修改, 審題 and 改題
- **THEN** its original stream and eligibility remain valid and its result/error stays attached to its originating card
- **AND** adopting generation-v2 selectors does not require a generation manifest for modification
