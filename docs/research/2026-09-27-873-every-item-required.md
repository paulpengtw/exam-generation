# Research #873: every_item_required field

Date: 2026-09-27  
Branch: feat/866-869-open-response-rubric  
Script: `scripts/research/rubric_873_harness.py`  
Data: `docs/research/873-every-item-required/`

---

## Summary

This research adds the `every_item_required` boolean field to the open-response rubric verifier, and measures two properties of the NS few-shot corpus:

1. **every_item_required distribution** (needs LLM): how many [2] rubric entries in the generation-run output declare `every_item_required=True` vs False, and whether the LLM classifies them correctly against the labelled set.
2. **EXTRA_ITEMS_FIXED_SENTENCE coverage** (programmatic): what fraction of existing corpus [2] entries contain the `#871` fixed sentence. **Baseline: 0/143 = 0.0%** — the sentence was introduced in #871 and has not yet been back-filled.

**API credit exhaustion.** No LLM calls completed. Steps 2 and 3 are pending re-run.

---

## Definition

`every_item_required = True` iff the [2] level uses 皆/均/都/全部 over a **student-generated (open) scope**: any item the student independently writes must satisfy the condition, and extra wrong-scope items cause a downgrade to [1].

Pattern: 「所提結論皆…」, 「所列理由均須…」, 「每一項都…」

`every_item_required = False` when:
- [2] uses 皆/均/都/全部 only over a set the **小題 names in advance** (「兩個條件均提及」, 「五點全部正確…」, 「甲、乙兩者均…」). Student-added extras are NOT penalised.
- [2]'s 皆/均 applies to **parts of one required answer chain** (「主張與數據皆須相符」) — not to extra student items.
- [2] does not use 皆/均/都/全部 at all.
- The criterion is code=1 or code=0 (not code=2).

**Key test**: "student-driven open scope" (True) vs "question-framed members OR single-answer-chain parts" (False).

---

## Step 1 — EXTRA_ITEMS_FIXED_SENTENCE baseline (measured)

```
EXTRA_ITEMS_FIXED_SENTENCE = "學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。"
```

| Metric | Value |
|---|---|
| Total [2] rubric entries in NS few-shot corpus (Constructed-response 題型, any folder) | 143 |
| Has EXTRA_ITEMS_FIXED_SENTENCE | 0 (0.0%) |
| Missing sentence | 143 |

The #871 fixed sentence was introduced after the corpus was written. The generation-run (Step 3) measures whether the new rubric-writing prompt with `OPEN_RESPONSE_RUBRIC_RULE` achieves ≥90% inclusion in freshly-generated rubrics.

**Rerun command** (reads cache first; only unevaluated entries make new API calls):
```
uv run python scripts/research/rubric_873_harness.py
```

---

## Labelled set for every_item_required (35 entries)

Labels are derived from the written definition above, never from model output.

The ticket criterion requires that the corpus's 21 framed-set levels are labelled False. A complete scan of all NS few_shot subfolders found **22 rubric levels in 19 unique open-response 小題** that use 皆/均/都/全部. Only `fasting-method seq=3 code=2` is True. All 22 are in the labelled set.

Scan method: both rubric key shapes handled (`{code, 規準說明}` and legacy `{編碼, 說明}`); each 小題 bucketed by its own `題型` field (not by folder), so items in `Simple-multiple-choice/` with `題型=Constructed response` are included, and items in `Constructed-response/` with `題型=Complex-multiple-choice` are excluded.

### Composition

| Source | True | False | Total |
|---|---|---|---|
| Corpus (22 rubric levels, 19 小題) | 1 | 21 | 22 |
| Synthetic positives | 3 | 0 | 3 |
| Near-misses | 0 | 10 | 10 |
| **Total** | **4** | **31** | **35** |

### Corpus entries (22)

All 22 corpus rubric levels with 皆/均/都/全部 in Constructed-response 小題:

| Key | Label | Rule |
|---|---|---|
| corpus\|fasting-method\|3\|2 | **True** | T1: 均 over student-generated conclusions (open scope) |
| corpus\|entomopathogenic-fungi\|3\|2 | False | F1: 均 over two named members (保護行, 多區塊設計) |
| corpus\|fishing-harbor-renovation\|2\|2 | False | F1: 均 over two named experimental groups |
| corpus\|hot-pack\|4\|2 | False | F1: 均 over two named experimental groups |
| corpus\|sea-ice-land-ice\|2\|2 | False | F1: 均 over two named groups (海冰組, 陸冰組) |
| corpus\|sea-ice-land-ice\|3\|2 | False | F1: 均 over two named roles in framed choice |
| corpus\|seawater-vertical-properties\|2\|2 | False | F1: 全部 over five given data points in the table |
| corpus\|soil-liquefaction\|5\|0 | False | F1+code0: code=0; 均 over two named evaluators |
| corpus\|truck-cornering\|2\|0 | False | F1+code0: code=0; 均 over two named sub-question parts |
| corpus\|weather-proverbs\|1\|1 | False | F1+code1: code=1; 都 over two named weather systems |
| corpus\|weather-proverbs\|2\|2 | False | F1: 均 over two named weather systems |
| corpus\|weather-proverbs\|2\|1 | False | F1+code1: code=1; 均 over two named weather systems |
| corpus\|weather-proverbs\|2\|0 | False | F1+code0: code=0; 均 over two named weather systems |
| corpus\|大氣能見度\|3\|2 | False | F1: 全部 over pre-specified table cells |
| corpus\|拉塞福散射\|2\|0 | False | F1+code0: code=0; 均 over two named positions |
| corpus\|日食\|2\|1 | False | F1+code1: code=1; 均 over two named yes/no questions |
| corpus\|果凍\|5\|1 | False | F1+code1: code=1; 都 over two named keywords |
| corpus\|生長素與向光性\|6\|2 | False | F1: 全部 over four named calculated values |
| corpus\|胡椒蛾の分子機制\|3\|0 | False | F3+code0: code=0; 全部 = all-answers-wrong |
| corpus\|蛙勒\|2\|2 | False | F1: 全部 over four named table items |
| corpus\|蛙勒\|2\|0 | False | F1+code0: code=0; 全部 over named table items |
| corpus\|自製夢幻飲品\|6\|0 | False | F1+code0: code=0; 皆 over two named answer items |

Notes:
- `weather-proverbs` seq=2 contributes 3 entries (code=2, code=1, code=0) — all from the same 小題.
- `蛙勒` seq=2 contributes 2 entries (code=2, code=0) — same 小題.
- `自製夢幻飲品` is in the `Simple-multiple-choice/` folder but its 題型=Constructed response.
- `胡椒蛾の分子機制` and `蛙勒` code=0 entries use 全部 in the sense of "all answers wrong" (F3), not EIR scope.

### Corpus True case: fasting-method seq=3

**Question**: 「請問以上實驗可以得出什麼結論？（請寫兩個結論）」

**[2]**: 正確寫出兩個合理且有所不同的結論，且均基於組間比較

**Why True**: The "均" applies to each conclusion the student writes: any conclusion that is NOT based on inter-group comparison would violate this criterion. The student's extra wrong-scope conclusions cause a downgrade.

**Note**: This item is also counting_stem=True (「請寫兩個結論」 from open set). #650 conversion is needed before it can be used as a generation-run input.

### Near-miss entries (10)

Near-misses are hand-crafted entries where 皆/均/都/全部 appears but EIR is False — to stress-test the model's ability to distinguish the True and False patterns.

**Kind A — 皆/均 over named members of a framed set** (looks like True because 皆 appears, but the members are named in the rubric/question):

| Key | Rule |
|---|---|
| near_miss\|named_pair\|1 | F1/A: 均 over two named members (甲方法, 乙方法) |
| near_miss\|named_pair\|2 | F1/A: 均 over two named variable types (操縱, 應變) |
| near_miss\|named_pair\|3 | F1/A: 均 over two named conditions (高溫組, 低溫組) |
| near_miss\|named_pair\|4 | F1/A: 均 over two named answer dimensions (定性, 定量) |
| near_miss\|named_triple\|1 | F1/A: 全部 over three named plants (甲, 乙, 丙) |

**Kind B — 皆/均 over parts of ONE required answer chain** (the canonical ticket example 「主張與數據皆須相符」):

| Key | Rule |
|---|---|
| near_miss\|answer_chain\|1 | F2/B: 均 over two parts of one answer chain (受力分析, 加速度推導) |
| near_miss\|answer_chain\|2 | F2/B: 皆 over claim+data parts of one argument |
| near_miss\|answer_chain\|3 | F2/B: 均 over cause+effect parts of one explanation |
| near_miss\|answer_chain\|4 | F2/B: 皆 over observation+inference parts of one reasoning chain |
| near_miss\|answer_chain\|5 | F2/B: 均 over hypothesis+design parts of one research proposal |

### Synthetic positives (3)

Three hand-crafted True entries with explicit EXTRA_ITEMS_FIXED_SENTENCE appended, to provide positive training signal:

| Key | Pattern |
|---|---|
| synth\|every_item\|1 | 「所提方案皆…」 over student-generated recommendations |
| synth\|every_item\|2 | 「均須基於…」 over student-generated causal explanations |
| synth\|every_item\|3 | 「都需引用…」 over student-generated arguments |

---

## Step 2 — every_item_required confusion matrix (pending)

API credits exhausted. Expected distribution based on labelled set:
- 4 True, 31 False
- **Hypothesis**: the model may confuse "student-driven scope" with "question-driven framing" when 均/皆 appears in both.
- **FP risk A**: near_miss|named_pair|* — the model sees 皆 with multiple items and may predict True.
- **FP risk B**: near_miss|answer_chain|* — the model sees 均/皆 and does not distinguish the scope.
- **FN risk**: corpus|胡椒蛾|3|0 and corpus|蛙勒|2|0 — the model may read "全部錯誤" as full-scope and predict True even though code=0 means "all answers wrong".

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
| Has EXTRA_ITEMS_FIXED_SENTENCE | ≥90% of 27 | Fail if <90% |
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
- `scripts/research/rubric_873_harness.py` — harness (35 labelled set entries, 30 gen-run items)
