# Spec: Batch-level scope dedup in prompts (issue #111)

## Why

Each question in a `count > 1` batch is generated independently; the LLM never sees what siblings already covered, so a 5-question batch can repeat the same 核心問題/學習內容 angle. The only 「不重複」 instruction lives in a Claude Desktop POC file that production never loads.

## Decision

Prompt-level dedup only (issue Phase 1). Embedding-similarity retry (Phase 2) is explicitly deferred. Applies to all three subjects.

## Design

### Accumulation

The batch loops in `src/cli.py` (math), `src/social_studies/cli.py` / `src/natural_sciences/cli.py` callers, and `server/generate/service.py` (all three subject branches) maintain a `prior_scopes: list[PriorScope]` where `PriorScope` = `{核心問題 | 出題概念 summary, 學習內容 codes}` extracted from each *accepted* question before the next iteration starts.

### Prompt injection

Each subject's context builder gains an optional `prior_scopes` parameter rendering a block:

```
## 已生成題目（請避免相似範圍）
1. 核心問題：…；學習內容：歷Ka-Ⅳ-1, 地Ab-Ⅳ-2
2. …
```

- Math: appended in `build_user_prompt` (uses 出題概念 + 學習內容 codes since math has no 核心問題).
- SS/NS: injected into the **文本生成器** prompt (`build_text_user_prompt`) — the shared passage/核心問題 is where topic overlap originates; 子題產生器 prompts are unchanged.
- Section omitted entirely when the list is empty (question 1 of a batch, or count=1) — zero behavior change for existing single-question flows.
- Cap the block at the most recent 10 entries to bound prompt growth for large batches.

Note: sampling-level coordination (which codes get scheduled) is issue #112's `BatchSampler`; this issue only makes the LLM aware of siblings so it varies angle/題材 even when codes overlap.

## Error handling

Extraction failures for a prior question (missing fields) skip that entry with a debug log; the block renders what it has.

## Testing

- Context-builder tests per subject: empty list → no section; two priors → both listed verbatim; >10 priors → capped.
- Batch-loop test (mock LLM): after question 1 completes, the recorded prompt for question 2 contains question 1's 核心問題/codes (`tests/test_batch_dedup.py`).
- Regression: count=1 prompts byte-identical to today.

## Out of scope

Embedding-similarity checks and retry-on-collision; cross-batch/user history dedup; coverage planning (#112); using the POC prompt file.
