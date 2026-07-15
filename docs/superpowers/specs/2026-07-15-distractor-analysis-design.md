# Spec: Per-option 誘答分析 (distractor analysis) on question output (issue #115)

## Why

`答案解析` explains only the correct answer. Teachers and reviewers cannot see what misconception each wrong option targets; students get no feedback on why plausible-looking options are wrong.

## Decision

Apply to **all three subjects** (issue was SS-only; extending now avoids per-subject follow-ups). Field shape and prompt guidance follow the issue.

## Design

### Schema

- SS `SubQuestion` and NS `SubQuestion` (`src/social_studies/schemas.py`, `src/natural_sciences/schemas.py`): `誘答分析: dict[str, str] = Field(default_factory=dict)`.
- Math `ExamQuestion` (`src/schemas.py`, flat structure): same field at top level (math options live inside 題目 strings; keys are option letters).
- Keys: option labels (`"A"`–`"D"`, or the scheme used). Values: for wrong options, the cognitive trap (誤讀題意 / 概念混淆 / 部分正確誘騙 / 過度推論…); for the correct option, a one-sentence 「正確答案：…」. Constructed-response items: empty dict or `{"常見錯誤": "..."}`.
- Empty-dict default ⇒ fully backward compatible; parsers ignore absence.

### Prompts

- System prompts (three subjects): a 「誘答分析的設計」 guidance block with the trap taxonomy and one JSON example (per the issue text).
- User prompts: hard requirement for 選擇題-family 題型 (math 選擇題 with A–D keys and 是非題 with 「是」/「非」 keys; SS 選擇題; NS Simple/Complex-multiple-choice); optional 常見錯誤 for constructed-response types. For SS/NS this lands in the 子題產生器 prompt (each 子題 call writes its own analysis).
- Corrector frozen-field lists: 誘答分析 is mutable (it must track a corrected answer), and the correction prompt reminds the model to keep it consistent with the fixed options.

### Few-shot

Update ≥2 existing few-shot examples per subject with realistic 誘答分析 so the models see the shape (math JSON styles, SS CSV/JSON, NS 題型 folders).

### Frontend + export

- `QuestionCard.tsx`: collapsible 誘答分析 section (amber panel, per-option rows) shown only where 答案/解析 is shown; i18n key `card.distractorAnalysis`.
- ODT export: include the section under each 小題's 解析 where the exporter already renders answers.

### Verifier (non-blocking)

`validate_distractor_keys()` helper: extract `(A)`–`(D)` labels from 題目, warn (never fail) when 誘答分析 keys don't match. Wired into each subject's verify path as a details-level warning.

## Testing

- Schema round-trip: models accept/omit the field; empty default.
- Prompt tests: MC-type prompts contain the requirement; constructed-response prompts mark it optional.
- Key-validation unit tests (match, extra key, missing key → warnings only).
- Vitest: card renders the section when the dict is non-empty, hides it when empty.

## Out of scope

Localization beyond zh-TW; retroactive regeneration of existing questions; making the verifier fail on missing/weak 誘答分析.
