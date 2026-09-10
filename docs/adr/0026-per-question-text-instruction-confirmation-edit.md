# ADR 0026 — Per-題組 文本出題指示 on the 發送前確認 Screen

**Status:** Accepted (issue #637)

## Context

`text_instruction` is a free-text hint passed to the 文本生成器 (text-generator stage)
for 社會領域 and 自然科學 requests. Before this change it was purely a request-level
field: one value applied identically to every 題組 in a batch.

A supervisor reviewing the batch on the 發送前確認 screen may want to give a different
instruction to specific 題組 — e.g. "focus on cause-and-effect for 題組 2 only" — without
touching the others or going back to the form.

## Decision

### Classification change

`text_instruction` is moved from `REQUEST_LEVEL_FIELDS` to `PER_QUESTION_FIELDS` in
`server/generate/models.py`. The two sets are mutually exclusive (enforced by
`test_per_question_params.py`).

This does **not** change how the request-level value is sent; it now additionally allows a
non-blank override to be carried inside a `per_question_params[i]` row.

### Resolver (slice A)

After building each resolved row, `src/common/resolver.py` checks the input row for a
non-blank `text_instruction`. If present, it is written into the resolved row verbatim so
`_resolved_payload_for_index` can retrieve it later. A blank or absent row value is not
written; the worker falls back to `params.text_instruction` as before.

The field is intentionally NOT added to `_BATCH_REQUEST_LEVEL_FIELDS` (the set stripped
from resolved rows). Its per-row override handling is entirely opt-in.

### Server routing (slice B)

A new helper `_per_question_text_instruction(i, params)` in `server/generate/service.py`
returns the effective `text_instruction` for worker `i`:

1. If `resolved_payload_for_index(params, i)["text_instruction"]` is non-blank → use it.
2. Otherwise → use `params.text_instruction` (request-level fallback).

Both `build_prompt_previews` and `_worker_one` call this helper instead of reading
`params.text_instruction` directly. This keeps the routing change local and avoids touching
`generate_question_stream`.

The forwarding proof in `test_contract_forwarding_guard.py` is updated to reference
`"_per_question_text_instruction"` as the token that proves each subject's worker routes the
field.

### Web UI (slice C)

Each per-題組 card on the 發送前確認 screen gains a `<textarea>` labelled "文本出題指示"
(i18n key `form.confirm_text_instruction`). The textarea is placed outside the `<dl>` (so
it uses a `<label>` element, not `<dt>`) to avoid conflicting with the top-level shared
display row that already uses a `<dt>` with the same text.

The textarea is prefilled from the effective per-row value:

```
effectiveQuestionTextInstruction
  = questionParams.text_instruction (if non-blank)
  | p.text_instruction (request-level)
  | ""
```

Editing triggers `updatePendingQuestionTextInstruction(index, value)`, which:

- Sets `perQuestionParams[index].text_instruction = trimmed` when non-blank.
- Deletes `perQuestionParams[index].text_instruction` when blank (falls back to
  request-level display, not to empty).
- Leaves all sibling rows untouched.
- Sets `hasPendingConfirmationEdits = true` to trigger a debounced preview refetch.

### Frontend requestLevelFields strip-list

`text_instruction` is removed from the `requestLevelFields` set in `ParamForm.tsx` so that
it is not stripped from per-question parameter rows when rebuilding the payload from history.

## Consequences

- A blank override clears back to the request-level value rather than to empty on the
  confirmation screen — consistent with the "釘選" model for other confirmation edits.
- The per-row override reaches **only** that 題組's 文本生成器 prompt. Sibling 題組 and all
  子題產生器 prompts are unaffected.
- The feature applies identically to `social_studies` and `natural_sciences`; `math` does not
  show the textarea (no 文本生成器 stage).
- The 提示詞預覽 is refetched after a per-題組 edit, reflecting the overridden value for the
  edited 題組.
- This change ran on Anthropic tokens (codex-unavailable fallback).
