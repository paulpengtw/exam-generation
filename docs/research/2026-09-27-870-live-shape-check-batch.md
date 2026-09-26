# #870 Live shape-check batch — research notes

**Date:** 2026-09-27
**Branch:** feat/866-869-open-response-rubric
**Author:** phwu@mail.naer.edu.tw

---

## Part 1 — Sweep result

A grep over `src`, `server`, `web/src`, `CLAUDE.md`, `AGENTS.md`, `README.md`,
`docs`, and `data` for `0\.\.N`, `2 / 1 / 0 / 0X`, `2/1/0/0X`, and `1-2 個學生作答實例`
was run on 2026-09-27 after the sweep edits committed in this PR.

### Remaining hits (all expected exceptions)

| File | Line(s) | Pattern matched | Reason |
|------|---------|-----------------|--------|
| `src/social_studies/schemas.py` | 130–131 | `0..N`, `2/1/0/0X` | Backward-compatibility docstring: states that new records use 2 / 1 / 0 and legacy records with 0..N or 2/1/0/0X codes remain readable. Not an instruction. |
| `web/src/hooks/useGenerate.ts` | 43 | `0..N`, `2/1/0/0X` | Updated comment itself: "new records use fixed 2 / 1 / 0; legacy 0..N and 2/1/0/0X both render." Backward-compat note, not an instruction. |
| `web/src/components/QuestionCard.test.tsx` | 552 | `0..N` | Left alone per task spec: tests rendering of opaque stored levels (existing test contract). |
| `README.md` | 691 | `2/1/0/0X` | Updated text mentions "legacy 2/1/0/0X codes remain readable" as a backward-compat note. |
| `CLAUDE.md` | 553 | `0..N` | Updated RubricEntry description: "legacy 0..N codes remain readable." Backward-compat note. |
| `AGENTS.md` | 553 | `0..N` | Mirror of CLAUDE.md 553; same reason. |

### Files edited

| File | Change summary |
|------|---------------|
| `src/social_studies/schemas.py` | Docstring: new open-response records use fixed 2 / 1 / 0; legacy 0..N or 2/1/0/0X codes remain readable. |
| `web/src/hooks/useGenerate.ts` | Comment: new records use fixed 2 / 1 / 0; legacy 0..N and 2/1/0/0X both render. |
| `CLAUDE.md` | L341: open responses carry fixed 2 / 1 / 0 rubrics (1/2/1 學生作答實例, hook-enforced, legacy readable). L553: RubricEntry code note updated. L557: "0..N" replaced with "fixed 2 / 1 / 0". L587/590: NS RubricEntry and convention line updated. |
| `AGENTS.md` | Identical changes to CLAUDE.md (files are mirrored). |
| `README.md` | L617: schema_parameters.csv rubric convention updated. L691: few_shot_examples.csv rubric codes note updated. |
| `data/social_studies/csv_填寫指南.md` | L271: 開放式建構反應題 row updated to fixed 2 / 1 / 0 with 1 / 2 / 1 example counts. |

---

## Part 2 — Prepared live batch

The batch script is at:

```
scripts/research/rubric_870_live_batch.py
```

### What it does (when credentials are available)

- Generates `BATCH_SIZE = 5` 題組 per subject (社會領域 and 自然科學).
- Each 題組 is generated through `generate_with_corrections` with `max_retries=3`
  and an `on_trail_entry` callback that records the full verification trail.
- At least one open-response 小題 is forced per 題組 via `subquestion_configs`
  (社會領域: `開放式建構反應題`; 自然科學: `Constructed-response`).
- From the trail it records:
  - `first_draft_shape_check_failure_rate` — fraction of 題組 whose first
    `VerificationTrailEntry.details` contains `[評分規準形狀檢核]`.
  - `pass_rate_after_correction` — fraction whose final verification passed.
  - `mean_correction_rounds` — mean number of correction trail entries per 題組.
- Results are written to `docs/research/870-live-shape-check-batch/results.json`.

### Rerun command

From the repository root:

```
uv run python scripts/research/rubric_870_live_batch.py
```

Required environment variables (`.env` or shell):

| Variable | Purpose |
|----------|---------|
| `LLM_API_KEY` | Anthropic API key — used for verification (claude-opus-4-6) and planning |
| `GEMINI_API_KEY` | Gemini API key — used for generation (default execute model: gemini-3.1-pro-preview) |

Override `LLM_MODEL_EXECUTE` to an Anthropic model if Gemini is unavailable.

---

## Status — NOT RUN

**Reason:** The Anthropic API account is out of credit (a probe returns HTTP 400
"Your credit balance is too low") and `GEMINI_API_KEY` is not configured in `.env`
for the default Gemini execute model (`gemini-3.1-pro-preview`).

The script exits early with a descriptive error message and writes no numbers in
this state. No estimated numbers are given here.

See `docs/research/870-live-shape-check-batch/ticket-comment.md` for the ticket
comment text required by the "Without credentials" acceptance criterion.
