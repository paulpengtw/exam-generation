## Purpose

讓教師在試題生成與人工審題修正期間，從既有生成進度列、工作紀錄與 Agent 文字窗辨識目前工作，並保有一致的語言、動態、可及性及隱私表現。批次呈現受現有事件可辨識範圍約束，不推測無法歸屬到個別題目的即時階段。

## ADDED Requirements

### Requirement: Immediate waiting feedback

The frontend SHALL present visible working feedback as soon as generation or 人工審題修正 starts, without waiting for a server event. Before a recognized generation step starts, the generation label SHALL be「產生中」; before a recognized modification step starts, it SHALL be「修改中」. Waiting SHALL NOT create placeholder Agent lanes or fabricated question results.

#### Scenario: Generation opens before any event arrives
- **WHEN** the user confirms a single-question request and no server event has arrived
- **THEN** 生成進度列 shows「產生中」with shimmer and the progress status line shows the same label with a spinner
- **AND** the Agent panel remains absent until real Agent activity arrives

#### Scenario: Modification admission is pending
- **WHEN** the user submits 修改指示 and the admission request or stream has not yet produced a modification step
- **THEN** its existing 生成進度列 shows「修改中」with shimmer throughout that waiting interval

#### Scenario: Non-step events arrive first
- **WHEN** acknowledgement, log, plan, or unrelated Agent events arrive before any recognized generation step
- **THEN** the waiting label remains visible and no later phase is inferred from elapsed time

### Requirement: Event-driven single-run phase presentation

For a single run, the frontend SHALL derive its phase from actual recognized step activity and present the same phase text in 生成進度列 and the progress status line. The grouped generation breadcrumb SHALL use「文本 › 子題 › 圖片 › 審題 › 改題」; flat math SHALL retain its generation step without introducing a fictitious 子題 step. The live label SHALL use「文本生成中」、「子題生成中」、「圖片生成中」、「審題中」or「改題中」as applicable; flat math generation SHALL use「產生中」. Completed steps SHALL be green, pending steps gray, and the current phase SHALL be identified by text as well as appearance. Steps lacking evidence SHALL NOT be marked completed.

#### Scenario: Grouped generation advances to 子題
- **WHEN** 文本 generation ends and actual 子題 generation activity starts
- **THEN** 文本 is complete and the current phase reads「子題生成中」on both status surfaces
- **AND** the grouped breadcrumb is used for social studies, natural sciences, and math when math actually runs its grouped pipeline

#### Scenario: Flat math does not generate 子題
- **WHEN** a math request runs the flat pipeline
- **THEN** its breadcrumb contains no 子題 step and its live generation label is「產生中」

#### Scenario: Optional steps are not observed
- **WHEN** a run reaches verification without image generation or correction events
- **THEN** 圖片 and 改題 remain dim and are not presented as completed or currently running

#### Scenario: Correction returns to verification
- **WHEN** verification fails, correction runs, and verification starts again
- **THEN** the live label changes from「審題中」to「改題中」and back to「審題中」according to those events
- **AND** unrelated or unknown stage names do not advance the breadcrumb

#### Scenario: No step is currently active between recognized steps
- **WHEN** a step ends and the run remains in progress before the next recognized step starts
- **THEN** both status surfaces retain the last recognized phase label until the next step or terminal outcome
- **AND** they do not invent the next phase or leave the running status blank

### Requirement: Truthful 子題 completion counts

During a single run's 子題 phase, the frontend SHALL show the number of distinct 子題 workers whose latest attempt ended successfully. Repeated events SHALL NOT inflate the count, and a worker retry SHALL cease to count as complete until that retry succeeds. The denominator SHALL use the submitted 子題 count when present, otherwise the announced total; an unknown total SHALL be omitted rather than guessed.

#### Scenario: Known total with a retry
- **WHEN** one of three workers completes, then that worker begins a retry
- **THEN**「子題生成中 1/3」changes to「子題生成中 0/3」until the retry completes

#### Scenario: Total has not been announced
- **WHEN** one distinct worker has completed and neither submitted nor announced total exists
- **THEN** the current label displays the completed count without a fabricated denominator

### Requirement: Frontend-only batch progress

For a multi-question run, 生成進度列 and the progress status line SHALL show「產生中 · 已完成 k / n」using received final results for k and the requested count for n. They SHALL NOT show a shared phase breadcrumb. Received draft and final questions SHALL retain their existing result-state chips and finality-dependent controls. The frontend SHALL NOT map unscoped Agent events to particular questions, infer live phases from result snapshots, or create a per-question live-phase chip. The Agent panel SHALL preserve its aggregate mode without per-question timers or stage attribution.

#### Scenario: Workers are in different phases
- **WHEN** a batch has three requested questions, one final result, and interleaved generation, verification, and correction activity
- **THEN** both run status surfaces show「產生中 · 已完成 1 / 3」
- **AND** only the bottom run status uses shimmer; the progress status line uses a spinner
- **AND** no question is labeled as currently verifying or correcting based on those unscoped events

#### Scenario: A non-final snapshot arrives
- **WHEN** the frontend receives an image or verified draft snapshot for a question
- **THEN** that question's existing result-state chip reflects the received snapshot
- **AND** the batch completed count does not increase until a final result arrives

### Requirement: Modification uses the same status vocabulary

人工審題修正 SHALL use its existing run-status surface with the breadcrumb nouns「修改」、「審題」、「改題」and live phase labels「修改中」、「審題中」、「改題中」. Repeated verification and correction activity SHALL remain visible in its existing chronological step history. Its result and error presentation SHALL remain attached to the originating question.

#### Scenario: Modification performs an automatic correction
- **WHEN** modification ends, verification runs, correction runs, and verification runs again
- **THEN** the breadcrumb preserves that order and only the currently presented phase shimmers
- **AND**「修改」and「改題」remain distinct operations

### Requirement: Functional indicators and streaming caret

Existing spinner sites SHALL share one consistent visual treatment while retaining their existing sizes, labels, and conditions for appearing and disabling controls. Single-run Agent thinking and response panes SHALL retain verbatim text formatting, selection, scrolling, stage history, errors, and the existing 100 ms timer cadence. Exactly one decorative caret SHALL appear at the tail of the pane receiving text for an active LLM call; no caret SHALL appear before text exists, after that call ends, or on inactive panes. Aggregate lanes SHALL NOT gain a caret that implies a particular worker is streaming.

#### Scenario: The active stream changes panes
- **WHEN** a single-run Agent emits thinking text and then response text
- **THEN** the caret moves from the thinking pane to the response pane without modifying either pane's text
- **AND** the pane headings remain「思考中」and「回應」in zh-TW

#### Scenario: A call ends while another Agent stage continues
- **WHEN** the LLM response completes or the call fails while other processing remains active
- **THEN** that call's caret disappears even if a containing Agent stage is still running

#### Scenario: Existing controls use the shared indicator
- **WHEN** a login, verification, generation, or core-question control reaches its existing loading condition
- **THEN** it shows the shared spinner treatment with its existing accessible label and enabled/disabled behavior
- **AND** the icon replacement does not introduce new network requests or permit repeated submission

### Requirement: Motion is limited and respects reduced motion

The only ambient shimmer SHALL occur on the running text of 生成進度列, using a blue-600 base, blue-300 highlight, and a 2250 ms loop. Normal spinners SHALL rotate linearly. The frontend SHALL retain its light palette and system font. When reduced motion is requested, shimmer and spinner rotation SHALL become an opacity pulse without translation or rotation, carets SHALL become solid while active, and transitions on affected surfaces SHALL become effectively instant. Finished, failed, and idle runs SHALL NOT retain running indicators.

#### Scenario: Normal motion during a run
- **WHEN** a run is active under normal motion preferences
- **THEN** shimmer appears only in its 生成進度列, never on Agent headings, the progress status line, result chips, or other controls

#### Scenario: Reduced motion is enabled
- **WHEN** the browser uses reduced motion before or during a run
- **THEN** moving shimmer and rotating spinners are replaced by opacity pulses and the active caret is solid
- **AND** the same phase text, result state, and controls remain available

#### Scenario: The run ends or fails
- **WHEN** a terminal success or failure is recorded, or the user clears the run
- **THEN** associated shimmer, spinners, and carets stop
- **AND** completion or error feedback replaces working feedback; a trailing stream-close event does not turn a recorded failure into success

### Requirement: Localized and accessible status without content disclosure

All new user-facing phase labels SHALL be available in zh-TW and English. zh-TW breadcrumb nouns SHALL use「審題／改題」while English retains Verify／Correct; internal generation-step identities SHALL remain unchanged. Generic AI “Thinking” terminology SHALL NOT replace run phases. Semantic status changes SHALL be announced politely once per run; animated frames, elapsed-time ticks, and raw streamed text SHALL NOT be added to that live announcement. Decorative indicators SHALL be hidden from assistive technology. Only fixed application labels SHALL be newly eligible for Sentry unmasking; user content, streamed thinking/responses, error reasons, and previously masked dynamic values SHALL remain masked.

#### Scenario: Locale changes during generation
- **WHEN** the locale changes between zh-TW and English while verification is active
- **THEN** both status surfaces switch to their corresponding localized phase text without resetting the run or changing its internal step identity
- **AND** no missing translation key appears

#### Scenario: Phase announcement and replay masking
- **WHEN** a live phase changes and its text is wrapped for animation
- **THEN** one polite status announcement communicates the phase without elapsed ticks or streamed contents
- **AND** the animation wrapper does not unmask the surrounding console, pane contents, error reason, or previously masked counters

### Requirement: Existing generation safeguards remain effective

The frontend SHALL preserve the resolved payload shown in 發送前確認, both submit affordances' disabled state for the whole generation run, the dormant resubmit guard, navigation and clear-results confirmation, and finality-based export restrictions. Starting or displaying indicators SHALL NOT wait for an animation or alter the submitted request.

#### Scenario: Feedback accompanies submission
- **WHEN** the user confirms generation
- **THEN** the confirmed request is dispatched immediately and both submit affordances remain disabled throughout the run
- **AND** visual feedback neither changes the payload nor delays dispatch

#### Scenario: Draft results and navigation protections
- **WHEN** a non-final result is visible and the user attempts navigation, clearing, or export
- **THEN** the existing confirmation and finality restrictions remain in effect independently of the new indicators
