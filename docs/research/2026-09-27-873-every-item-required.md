# Research #873: every_item_required field

Date: 2026-09-27  
Branch: feat/866-869-open-response-rubric  
Script: `scripts/research/rubric_873_harness.py`  
Data: `docs/research/873-every-item-required/`

---

## Summary

This research adds the `every_item_required` boolean field to the open-response rubric verifier, and measures two properties of the NS few-shot corpus:

1. **every_item_required distribution** (needs LLM): how many [2] rubric entries in the generation-run output declare `every_item_required=True` vs False, and whether the LLM classifies them correctly against a 12-entry labelled set.
2. **EXTRA_ITEMS_FIXED_SENTENCE coverage** (programmatic): what fraction of existing corpus [2] entries contain the `#871` fixed sentence. **Baseline: 0/157 = 0.0%** — the sentence was introduced in #871 and has not yet been back-filled.

**API credit exhaustion.** No LLM calls completed. Steps 2 and 3 are pending re-run.

---

## Definition

`every_item_required = True` iff the [2] level uses 皆/均/都/全部 over a **student-generated (open) scope**: any item the student independently writes must satisfy the condition, and extra wrong-scope items cause a downgrade to [1].

Pattern: 「所提結論皆…」, 「所列理由均須…」, 「每一項都…」

`every_item_required = False` when:
- [2] uses 皆/均/都/全部 only over a set the **小題 names in advance** (「兩個條件均提及」, 「五點全部正確…」). Student-added extras are not penalised.
- [2] does not use 皆/均/都/全部 at all.

**Key test**: "student-driven scope" (True) vs "question-driven framing" (False).

---

## Step 1 — EXTRA_ITEMS_FIXED_SENTENCE baseline (measured)

```
EXTRA_ITEMS_FIXED_SENTENCE = "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
```

| Metric | Value |
|---|---|
| Total [2] rubric entries in Constructed-response corpus | 157 |
| Has EXTRA_ITEMS_FIXED_SENTENCE | 0 (0.0%) |
| Missing sentence | 157 |

The #871 fixed sentence was introduced after the corpus was written. The generation-run (Step 3) measures whether the new rubric-writing prompt with `OPEN_RESPONSE_RUBRIC_RULE` achieves ≥90% inclusion in freshly-generated rubrics.

**Rerun command** (reads cache first; only unevaluated entries make new API calls):
```
uv run python scripts/research/rubric_873_harness.py
```

---

## Labelled set for every_item_required (12 entries)

Labels are derived from the definition above, never from model output.

| Key | Source | Label | Rule |
|---|---|---|---|
| corpus\|fasting-method\|3 | corpus | **True** | T1: 均 over student-generated conclusions |
| corpus\|entomopathogenic-fungi\|3 | corpus | False | F1: 均 over two named members |
| corpus\|fishing-harbor-renovation\|2 | corpus | False | F1: 均 over two named experimental groups |
| corpus\|hot-pack\|4 | corpus | False | F1: 均 over two named experimental groups |
| corpus\|sea-ice-land-ice\|2 | corpus | False | F1: 均 over two named groups |
| corpus\|sea-ice-land-ice\|3 | corpus | False | F1: 均 over two named roles |
| corpus\|seawater-vertical-properties\|2 | corpus | False | F1: 全部 over five given data points |
| corpus\|weather-proverbs\|2 | corpus | False | F1: 均 over two named meteorological systems |
| synth\|every_item\|1 | synth_positive | **True** | T1: 皆 over student-generated recommendations |
| synth\|every_item\|2 | synth_positive | **True** | T1: 均 over student-generated explanations |
| near_miss\|named_pair\|1 | near_miss | False | F1: 均 over two named members |
| near_miss\|answer_chain\|1 | near_miss | F2: 均 over steps of one answer chain |

True: 3, False: 9 (1 corpus True, 7 corpus False, 2 synthetic True, 2 near-miss False)

### Corpus True case: fasting-method seq=3

**Question**: 「請問以上實驗可以得出什麼結論？（請寫兩個結論）」

**[2]**: 正確寫出兩個合理且有所不同的結論，且均基於組間比較

**Why True**: The "均" applies to each conclusion the student writes: any conclusion that is NOT based on inter-group comparison would violate this criterion. The student's extra-wrong conclusions cause a downgrade.

**Note**: This item is also counting_stem=True (「請寫兩個結論」 from open set). #650 conversion is needed before it can be used as a generation-run input.

---

## Step 2 — every_item_required confusion matrix (pending)

API credits exhausted. Expected distribution based on labelled set:
- 3 True, 9 False
- Hypothesis: the model may confuse "student-driven scope" with "question-driven framing" when the keyword 均 appears in both contexts.
- Key FP risk: near_miss|answer_chain|1 — the model may see 均 and predict True even though the steps are part of one required answer chain.

**Rerun**: `uv run python scripts/research/rubric_873_harness.py`

---

## Step 3 — Generation-run input (30 items, pending)

30 open-response 小題 selected from the NS Constructed-response corpus:
- **3 need #650 conversion** before rubric-writing:
  - `fasting-method|0|3`: 「請寫兩個結論」→ rewrite to name the two conclusions or reduce to one
  - `washing-machine-physics|0|5`: 「至少兩點」→ rewrite to name the observations or reduce to one
  - `胡椒蛾の分子機制|0|3`: 「至少三項」of Hardy-Weinberg violations → name them or reduce to one
- **27 normal items**: no counting_stem issues; ready to send to rubric-writing prompt

### Expected counts (after generation run)

| Metric | Expected | Threshold |
|---|---|---|
| Has EXTRA_ITEMS_FIXED_SENTENCE | ≥90% of 27 | Note only if <90% |
| every_item_required=True | ~1-3 of 27 | Note only |

**Rerun**: `uv run python scripts/research/rubric_873_harness.py`

---

## Rubric-writing prompt

The prompt uses `OPEN_RESPONSE_RUBRIC_RULE` from `src/common/open_response_rubric.py` verbatim, plus:
- Instruction to append `EXTRA_ITEMS_FIXED_SENTENCE` at the end of every [2] 規準說明.
- Request for `every_item_required` (bool) and reason in the output JSON.

The prompt is defined in `scripts/research/rubric_873_harness.py` as `RUBRIC_WRITING_SYSTEM_PROMPT` and `RUBRIC_WRITING_USER_TEMPLATE`.

---

## Recommendations (preliminary)

### every_item_required field
**Recommendation: implement as informational field** (no Fail check on its own). The field is needed to correctly route EXTRA_ITEMS_FIXED_SENTENCE: when `every_item_required=True`, the fixed sentence should be suppressed (because the student's extra items ARE penalised — the fixed sentence would be contradictory). When `every_item_required=False`, the fixed sentence must be present.

### EXTRA_ITEMS_FIXED_SENTENCE coverage
**Recommendation: Fail if <90%** of freshly-generated [2] entries contain the sentence. Baseline is 0% (existing corpus). The generation-run will measure whether the new prompt achieves the threshold.

---

## Files committed

- `docs/research/2026-09-27-873-every-item-required.md` — this report
- `docs/research/873-every-item-required/ticket-comment.md` — comment for issue #873
- `docs/research/873-every-item-required/responses.jsonl` — LLM cache (0 entries; pending re-run)
- `scripts/research/rubric_873_harness.py` — harness
