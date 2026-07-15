# Spec: Per-batch Opus 情境-題材 creative planning (issue #114)

## Why

Opus is confined to generating 3 candidate 核心問題; Sonnet receives the sampled 情境 as a bare enum label (「個人」/「公共」) with no creative direction, so 題材 substitution is mechanical and questions feel repetitive even when core questions differ.

## Decision

**Per-batch** granularity (one Opus call plans N distinct creative briefs for a `count`-question batch), social studies only. This also complements #111: distinct briefs are themselves a dedup mechanism; the #111 prompt block remains as belt-and-suspenders.

## Design

### Planner (`src/social_studies/planner.py` + `src/common/planner.py`)

New `plan_context_angles(client, count, sampled_contexts, learning_content_pool, core_question=None) -> list[CreativeBrief]` using `model_plan` (Opus). One call returns `count` briefs, each:

```python
class CreativeBrief(BaseModel):
    selected_context: str      # one of the sampled/available 情境 values
    題材_angle: str            # 1–2 sentence creative framing tying 核心問題×情境
    framing_hooks: list[str]   # 1–2 concrete grounding devices (e.g. 病患日記、決策會議紀錄)
```

The prompt explicitly requires the N briefs to be **mutually distinct in 題材** and grounded in the provided learning-content pool. JSON-array output parsed with the existing `extract_json` tolerance.

### Threading

- `SampledParams.creative_brief: CreativeBrief | None = None` (SS schemas).
- Batch loops (SS branch of `server/generate/service.py`, `src/social_studies/cli.py`): plan once before the loop when `count ≥ 1` and planning is enabled; question *i* consumes brief *i*. Enable/disable via config `creative_planning: bool` (env `CREATIVE_PLANNING`, default **on** for SS — cost is one Opus call per batch, not per question).
- Prompt (`src/social_studies/context_builder.py`): when a brief is present, the 文本生成器 user prompt renders 情境 as 「**情境**：{selected_context}（創意取材角度：{題材_angle}；參考取材點：{framing_hooks}）」 plus a 「創意指引」 system-prompt section encouraging novel 題材 and discouraging copying few-shot 題材. Without a brief, current wording is unchanged.
- The brief's `selected_context` must come from the sampler's chosen 情境 set (script-side randomness stays authoritative — Opus picks the angle, not new parameters).

## Error handling

Opus call failure, malformed JSON, or fewer briefs than `count` → log a warning and fall back to briefless prompts for the uncovered questions. Planning never blocks generation.

## Testing

- Unit: `plan_context_angles` parses a mocked N-brief response; brief with out-of-set context is dropped (fallback for that slot).
- Prompt tests: with brief → 創意指引 + angled 情境 line; without → current template verbatim.
- Batch test (mock LLM): 3-question batch consumes 3 distinct briefs, one per prompt.
- Diversity smoke (env-gated, manual/real-LLM): 5 same-param generations yield ≥3 distinct 題材 keywords — per the issue's manual QA.

## Out of scope

Math/NS creative planning; Opus generating 題組 content; few-shot retrieval changes; per-question Opus calls.
