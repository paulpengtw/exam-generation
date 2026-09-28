## MODIFIED Requirements

### Requirement: Stream mode is validated once per request
The client SHALL enable per-question progress only after validating the manifest returned at 受理, including supported protocol version, run identity, unique IDs, contiguous valid indices and accepted total. A live observation stream, when used, SHALL be validated against that same manifest; a `started` event whose run or manifest differs SHALL be rejected. Each submission SHALL have a separate client generation so old callbacks cannot bind a new run. Unknown protocol versions SHALL stop decoding, retain received content and report uncertainty without automatic resubmission. A missing manifest SHALL NOT be reconstructed from other events. Presentation degradation SHALL NOT switch a stream's remaining bytes into another parser.

#### Scenario: Valid v2 starts a batch
- **WHEN** the acceptance response passes all manifest checks for N questions
- **THEN** the client creates N fixed-position compact cards initially showing 等待生成

#### Scenario: A stale connection delivers started
- **WHEN** a previous request's callback delivers started or later events after a new submission
- **THEN** it does not change the new run, cards, activity or counts

#### Scenario: Unknown protocol or absent manifest
- **WHEN** the protocol is unsupported or the acceptance response lacks a valid manifest
- **THEN** no per-question activity or full-batch placeholder manifest is invented
- **AND** no new generation request is sent automatically

### Requirement: Batch counts are unique terminal and receipt counts
The primary batch count SHALL read 已結束 X/N 題, with N fixed by the accepted manifest and X counting unique questions with undisputed terminal evidence of normal ending, failure or confirmed cancellation. A 終止原因 recorded in persisted run state SHALL count as terminal evidence. A separate count SHALL state 收到最終結果 Y 題 for unique final results received live or read from persisted run state. Drafts, retries, operations, duplicate events, resumed attempts and pending final bodies SHALL NOT inflate either count. Completeness and review classifications SHALL remain separate; 100 percent SHALL mean all processing ended, not that every result is complete or passed.

#### Scenario: Mixed outcomes in four questions
- **WHEN** A has complete passed final and terminal, B has partial failed-review final and terminal, C has a failed no-final terminal plus draft, and D has final without terminal
- **THEN** the batch displays 已結束 3/4 題 and 收到最終結果 3 題
- **AND** C's downloadable draft does not increase Y and D stays processing-unknown until persisted state establishes its outcome

#### Scenario: Retries and repeated final arrive
- **WHEN** a 小題 retries, a run resumes, or the same question's final and terminal are redelivered
- **THEN** the batch denominator and unique ended/received counts do not grow

#### Scenario: Counts are read after returning
- **WHEN** the owner reopens a run whose persisted state records three ended questions of four
- **THEN** the page reads 已結束 3/4 題 without any live events

### Requirement: Closure and shared surfaces preserve truthful state
When a live observation stream closes or disconnects, the client SHALL retain received contents and established terminal facts and continue from persisted run state. It SHALL NOT mark outcomes unknown merely because the stream ended. Activity indicators without a trustworthy source SHALL stop, and processing SHALL be shown from persisted 處理狀態 and 生成步驟. Client abort, leaving the page and stream loss SHALL NOT mean cancellation; only an explicit owner cancel SHALL. Intentional clear SHALL preserve its existing clearing and confirmation semantics without cancelling the run. The progress bar, ProgressLog and cards SHALL derive coherent counts and conclusions from the same normalized evidence, combining live and persisted evidence without double counting. Shared 人工審題修正 components SHALL retain their distinct stream handling, selection/qualification rules and result/error association, alongside existing localization, accessibility, reduced-motion and masking rules.

#### Scenario: Connection ends during generation
- **WHEN** A has a terminal and B only has a draft when the connection is lost
- **THEN** A retains its conclusion, B continues to be shown from persisted state as running at its current 生成步驟, and no unsupported running animation continues
- **AND** the interface does not claim cancellation

#### Scenario: Persisted state is unavailable
- **WHEN** the stream closes and reading persisted run state fails
- **THEN** received contents remain, unestablished outcomes are shown unknown, and the client retries reading without resubmitting generation

#### Scenario: Shared components render modification activity
- **WHEN** a teacher submits 修改指示 and the separate modification run proceeds through 修改, 審題 and 改題
- **THEN** its original stream and eligibility remain valid and its result/error stays attached to its originating card
- **AND** adopting generation selectors does not require a generation manifest for modification
