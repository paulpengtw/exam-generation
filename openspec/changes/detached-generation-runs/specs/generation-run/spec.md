## Purpose

Keep an accepted generation (a 生成執行) running to a definitive per-question outcome independently of any browser connection. Make its persisted state the trustworthy source for what a returning teacher sees, so generations longer than the hosting platform's request limit, or abandoned by the viewer, still deliver their results.

## ADDED Requirements

### Requirement: 受理 creates a durable run before responding
A generation submission SHALL be accepted (受理) only after the server has durably recorded the run and one 處理狀態 entry per manifest question, each initially waiting. The acceptance response SHALL return the run identity and the complete question manifest (`index`, `question_id`) without waiting for any generation work. A run SHALL exist once accepted, whether or not the response reaches the browser. A submission that fails before the record is complete SHALL NOT leave a partial run.

#### Scenario: A three-question batch is submitted
- **WHEN** a teacher confirms 確定發送 for three questions
- **THEN** the response returns immediately with a run identity and three question identities at indices 0, 1 and 2
- **AND** reading that run shows three waiting questions before any model call has finished

#### Scenario: The connection drops before the response arrives
- **WHEN** the server records the run but the browser never receives the acceptance response
- **THEN** the run still executes and appears to its owner among runs that have not ended

### Requirement: Duplicate submissions do not create a second paid run
Each press of 確定發送 SHALL carry a client-generated submission key. When the same teacher submits again with a key that already produced a run, the server SHALL return the existing run's acceptance instead of creating another. A deliberate new submission SHALL use a new key and create a new run.

#### Scenario: A timed-out submission is retried
- **WHEN** a submission's response is lost and the client retries with the same submission key
- **THEN** the server returns the original run identity and manifest and no second run starts

#### Scenario: A teacher deliberately submits the same parameters again
- **WHEN** the teacher presses 確定發送 a second time with identical parameters
- **THEN** a new submission key creates a separate run with new identities

### Requirement: Runs execute independently of observers
An accepted run SHALL continue until every question has a 終止原因 regardless of observer state. Network loss, page refresh, navigating away, closing the tab or browser, logging out and the end of any live stream SHALL NOT cancel, pause or fail the run. Only an explicit owner cancel, exhaustion of recovery attempts or the total time limit SHALL stop unfinished questions.

#### Scenario: The teacher leaves while one question is delivered and another is generating
- **WHEN** question A has ended and question B is generating and the teacher closes the page
- **THEN** B continues and, on return, A shows its final result and B shows its current 生成步驟 or its final result

#### Scenario: A generation runs longer than the platform request limit
- **WHEN** a batch needs more than 900 seconds to finish
- **THEN** every question still reaches a 終止原因 and its delivered results are readable afterwards

### Requirement: Results are saved before they are delivered
A question's final result, with its sibling verification, figure-policy and reference-example records, SHALL be durably saved before the result is published to any observer or reported as delivered. At most one saved result SHALL exist per run and question; repeated saves SHALL NOT create duplicates. A save that fails after bounded retries SHALL be reported to error monitoring and SHALL end that question with 終止原因 failed and a stated reason; the question SHALL NOT be reported as delivered.

#### Scenario: A result is completed while nobody is connected
- **WHEN** question B finishes after the viewer's connection has closed
- **THEN** B's result is saved and is readable when the owner returns

#### Scenario: A resumed run completes a question again
- **WHEN** recovery causes a question's save to be attempted twice
- **THEN** exactly one saved result exists for that run and question

#### Scenario: The database rejects a save repeatedly
- **WHEN** saving a completed question still fails after the retry limit
- **THEN** the question ends as failed with a reason, the failure is reported, and no observer is told the result was delivered

### Requirement: Each question receives exactly one 終止原因
Every manifest question SHALL receive exactly one persisted 終止原因 (`normal`, `failed` or `cancelled`), which SHALL NOT be overwritten once recorded. When several outcomes race for the same question, the first recorded SHALL stand. A run SHALL end only after every question has a 終止原因. The persisted terminal record SHALL preserve delivery completeness and review conclusion separately from processing termination.

#### Scenario: Cancel and completion race
- **WHEN** question A records normal termination just before a cancel reaches it
- **THEN** A stays normal with its result and only questions without a 終止原因 become cancelled

#### Scenario: A normally ended question has a failed review
- **WHEN** question A ends normally but its review failed and one 小題 is missing
- **THEN** its record keeps termination normal, delivery partial and review failed as separate facts

### Requirement: Only the owner can cancel, and only the whole run
The owning teacher SHALL be able to cancel an unfinished run. Cancellation SHALL apply to the whole run and SHALL take effect within about 30 seconds. The interface SHALL show 取消中 immediately after the request. Questions that have already ended SHALL keep their results and remain downloadable. Questions without a 終止原因 SHALL end as cancelled. Cancelling a run whose questions have all ended SHALL change nothing. Losing the connection, leaving the page and logging out SHALL NOT count as cancellation.

#### Scenario: The owner cancels mid-run
- **WHEN** A has ended and B and C are unfinished and the owner presses Cancel
- **THEN** the control reads 取消中 at once, A keeps its result, and B and C end as cancelled within about 30 seconds

#### Scenario: Someone else attempts to cancel
- **WHEN** a different signed-in user sends a cancel for the run
- **THEN** the request is refused and the run is unaffected

#### Scenario: Cancel arrives after the run ended
- **WHEN** every question already has a 終止原因 and the owner presses Cancel
- **THEN** no question changes and the run remains ended as before

### Requirement: Runs recover from host failure
If the process executing a run stops (crash, restart, deployment replacement), the run SHALL be detected as abandoned within about 3 minutes and resumed by an available host. Resumption SHALL keep every question that already has a 終止原因 and SHALL redo questions that were unfinished. While awaiting resumption, reading the run SHALL show each question's last known 生成步驟. A run SHALL be attempted at most 3 times; after the last attempt fails, unfinished questions SHALL end as failed with a visible reason. Reference-example and figure-policy records from an abandoned attempt SHALL be retained and labelled with their attempt number rather than discarded.

#### Scenario: A deployment replaces the host mid-run
- **WHEN** A has ended and B is generating when the host process is replaced
- **THEN** the run resumes on a host, A is not regenerated, B is redone, and both end with a 終止原因

#### Scenario: Every attempt fails
- **WHEN** the run's host stops during three separate attempts
- **THEN** unfinished questions end as failed with a reason stating recovery was exhausted, and ended questions keep their results

#### Scenario: A reference-example draw happened in an abandoned attempt
- **WHEN** attempt 1 drew reference examples for B before its host stopped and attempt 2 redoes B
- **THEN** the 參考範例紀錄 retains both draws, each labelled with its attempt

### Requirement: Admission and execution limits
Each teacher SHALL have at most one run executing at a time; further accepted runs SHALL wait queued in submission order. A teacher SHALL have at most five queued runs; a further submission SHALL be rejected before a run is created, with a readable reason. Each host SHALL execute at most a configured number of runs concurrently. A run SHALL end unfinished questions as failed with a stated reason once it exceeds a total execution time of 2 hours. Queued runs SHALL NOT expire.

#### Scenario: A teacher queues a second run
- **WHEN** a teacher's first run is executing and they submit another
- **THEN** the second is accepted as queued and shows 排隊中 with its position

#### Scenario: A sixth queued run is submitted
- **WHEN** a teacher already has five queued runs and submits again
- **THEN** the submission is rejected with a readable reason and no run is created

#### Scenario: A run exceeds the total time limit
- **WHEN** a run is still unfinished two hours after execution began
- **THEN** its unfinished questions end as failed with a time-limit reason and ended questions keep their results

### Requirement: Owners read persisted run state
The owner SHALL be able to list their runs, both those that have not ended and those that have, and to read any of their runs. Reading a run SHALL return, per manifest question, its 處理狀態 (`waiting`, `running`, `ended`), current 生成步驟 while running, 終止原因 when ended, delivery completeness, review conclusion, error reason and the saved final result with its images and downloads. A queued run SHALL report how many runs are ahead of it. Persisted state SHALL be the authority for returning viewers. Drafts of unfinished questions, per-agent activity and full model-call text SHALL NOT be restored. Only the owner SHALL be able to read a run. Saved results SHALL follow the existing history retention.

#### Scenario: The owner returns on another device
- **WHEN** the owner signs in on a different device while their run is executing
- **THEN** they see the same per-question states and delivered results as on the original device

#### Scenario: Another user requests the run
- **WHEN** a different user requests the run by its identity
- **THEN** the request is refused without revealing the run's contents

#### Scenario: An unfinished question had a live draft
- **WHEN** B showed a draft live and the owner returns after the connection ended
- **THEN** B shows its 處理狀態 and 生成步驟 but no restored draft

### Requirement: Teacher surfaces follow persisted run state
The generation page SHALL fill in each question from persisted state as it changes and SHALL keep doing so after the page is reopened. The history page SHALL show a 「尚未結束」 section listing the owner's queued and executing runs, with queued runs reading 「排隊中 · 前面還有 k 個」. A run SHALL move from 「尚未結束」 into the ordinary history list once it ends. The navigation SHALL show an in-app indicator when one of the owner's runs ends. No email notification SHALL be sent. Leaving the generation page SHALL NOT abort the run.

#### Scenario: A run finishes while the teacher is elsewhere
- **WHEN** the teacher is on another page when their run ends
- **THEN** an in-app indicator appears and the run is listed among ended history with its results

#### Scenario: The teacher reopens the generation page
- **WHEN** the teacher navigates back to a run that is still executing
- **THEN** the page shows current persisted states and continues updating without a new submission
