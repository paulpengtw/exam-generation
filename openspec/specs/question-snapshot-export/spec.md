# question-snapshot-export Specification

## Purpose

Allow teachers to download the content actually received at the moment of export, including drafts and mixed batches, without changing question identity or generation conclusions. Preserve visible figures and explicitly distinguish export failures from incomplete generated content.

## Requirements

### Requirement: Single and batch exports capture received content atomically
JSON and ODT downloads SHALL be available for received draft and final content, including partial delivery, failed or skipped review and unknown processing outcomes. A download SHALL freeze one click-time snapshot of content, identity, revision, state and visible figure sources, without waiting for generation or historical persistence. Batch exports SHALL include received content in established original order, omit bodyless placeholders and retain stable explicitly unknown order for legacy entries without an index. Later generation events SHALL NOT alter an in-progress export.

#### Scenario: A batch contains draft final and placeholder cards
- **WHEN** a teacher downloads a batch with A final, B draft and C without body content
- **THEN** the snapshot contains A and B at their established order and omits C
- **AND** B is identified as draft and does not become a received final result

#### Scenario: Generation changes content during export
- **WHEN** revision 4 arrives while an export captured at revision 3 is being built
- **THEN** that export retains revision 3 content, status and figures throughout

#### Scenario: Draft content has not been saved to history
- **WHEN** only the current page has received the draft
- **THEN** its JSON and ODT downloads remain available without creating a durable draft or recovery record

### Requirement: JSON remains question shaped with export-only metadata
Single-question JSON SHALL remain a question object and batch JSON SHALL remain an array of question objects, preserving original fields and IDs. Only the export copy SHALL append `_export` containing `format_version: 1`, a shared-per-export ISO 8601 UTC `exported_at`, `is_draft`, known-or-null run_id/index/content_revision, processing and termination information, delivery completeness, revision-matched review and known missing items. Unknown evidence SHALL remain null or unknown. Export metadata SHALL NOT mutate live or persisted question data, serve as new generation evidence or include full LLM/operational trails. Removing `_export` SHALL recover the original captured question structure. Consumers SHALL be told that `_export` is additive metadata; compatibility with tools rejecting additional fields SHALL NOT be assumed.

#### Scenario: Draft JSON is downloaded
- **WHEN** a draft is exported
- **THEN** its original id and Chinese question fields remain in place and `_export.is_draft` is true
- **AND** the live and stored question objects are unchanged

#### Scenario: Mixed batch JSON is downloaded
- **WHEN** one export captures both draft and final questions
- **THEN** each retains its own draft status and content revision while sharing the export timestamp
- **AND** the top-level JSON remains an array

#### Scenario: Old history lacks v2 evidence
- **WHEN** a legacy history question is exported through the shared interface
- **THEN** its question structure and original id remain, unavailable run/revision/terminal information is null or unknown, and no progress evidence is fabricated

### Requirement: Draft labels and partial 題組 content survive export
Draft filenames SHALL identify 草稿 and mixed batches SHALL identify 含草稿. ODT SHALL label each draft before its content and preserve received shared 文本, 小題, original ordinals, known missing items and separately stated processing/completeness/review information. Final with unknown processing SHALL remain final received content, not be relabeled a draft solely for missing terminal evidence. A 題組 with shared text but no surviving 小題 SHALL still export that text as a 題組.

#### Scenario: Only shared text is available
- **WHEN** a draft or partial final 題組 has shared 文本 but no surviving 小題
- **THEN** ODT includes that text, its actual draft/final status and known missing 小題 without converting it into an empty flat question

#### Scenario: A final has no terminal evidence
- **WHEN** its content is exported after stream closure
- **THEN** the export preserves final receipt and unknown processing as separate facts

### Requirement: Visible figure previews are included in frozen ODT exports
ODT SHALL include the visual sources actually visible in the frozen snapshot. A matching available image SHALL be embedded directly; a visible preview without a matching backend PNG SHALL be converted for export. Absence of a PNG alone SHALL NOT justify substituting text for a visible preview. Top-level and per-小題 figure placement SHALL preserve fixed identity and revision. Conversion SHALL use the captured preview, not subsequently changed live content, and SHALL NOT call an LLM or image generation provider.

#### Scenario: A card shows a preview with no backend PNG
- **WHEN** the teacher exports that card as ODT
- **THEN** the export attempts conversion and embeds that captured visible preview at its corresponding question or 小題 position

#### Scenario: A later image arrives during preview conversion
- **WHEN** export is converting a captured preview and a different revision's PNG arrives
- **THEN** the in-progress document continues using its original snapshot and does not silently substitute the newer PNG

#### Scenario: No image or visible preview exists
- **WHEN** a required figure has neither a received image nor a visible preview
- **THEN** the known missing figure is stated explicitly without generating a replacement during export

### Requirement: Figure conversion failure is explicit and independent of generation
When a captured figure genuinely fails conversion, the system SHALL allow an ODT containing all other available content and a visible 匯出缺圖／預覽轉換失敗 marker at the affected location. It SHALL distinguish export defects from generated-content missing items and SHALL NOT change processing, delivery completeness or review. A failure to package the document itself SHALL produce an export error, not a corrupt downloadable document. JSON SHALL remain available and export retry SHALL reuse the frozen snapshot without rerunning generation; a new export action SHALL capture current content anew.

#### Scenario: One preview conversion fails
- **WHEN** one visible preview fails conversion while other content can be packaged
- **THEN** ODT remains downloadable with an explicit missing-image conversion marker at that figure's position
- **AND** the original question's generation and review conclusions are unchanged

#### Scenario: The document cannot be packaged
- **WHEN** the ODT archive operation fails independently of figure conversion
- **THEN** the teacher receives an export failure rather than a broken file, retains JSON access and can retry the same snapshot

### Requirement: Shared export surfaces preserve existing modification eligibility
Single-card, batch and existing downloadable-history surfaces SHALL use the same snapshot and annotation contract. Already obtained actual images SHALL remain downloadable as PNG, with draft filenames where appropriate; a preview alone SHALL NOT become a fabricated generated PNG. Enabling draft export SHALL NOT enable 人工審題修正 for content that fails its existing eligibility rules, alter selection paths, or replace its separate execution semantics. Old tabs SHALL retain only their actual old export capabilities until updated; new clients SHALL NOT disable received draft export merely because the content uses legacy or lacks v2 metadata.

#### Scenario: A draft becomes downloadable
- **WHEN** a non-final card receives JSON and ODT download actions
- **THEN** those actions do not grant new annotation or modification eligibility

#### Scenario: Legacy content is shown in a new client
- **WHEN** a new client has received a legacy draft with sufficient content to export
- **THEN** it exports with draft markings and unknown v2 evidence rather than reintroducing final-only download restrictions
