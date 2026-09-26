# Comment for GitHub issue #873

Research run complete. Report: `docs/research/2026-09-27-873-every-item-required.md`

## What was measured

**Model:** `claude-opus-4-6` at `high` effort (default `model_verify`). Total new LLM calls: 0 (API credits exhausted). Steps 2 and 3 are pending re-run.

---

## Step 1 — EXTRA_ITEMS_FIXED_SENTENCE baseline: **0/143 = 0.0%** (measured, complete)

Scanned all 143 [2] rubric entries in the NS few-shot corpus with `題型=Constructed response` (all three `few_shot/` subfolders, bucketed by 小題's own `題型` field).
None contains the `#871` fixed sentence:
```
學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。
```
This is expected — the sentence was introduced in #871 after the corpus was written.

**Goal for generation-run (Step 3):** ≥90% of newly-generated [2] entries contain the fixed sentence. Recommend **Fail if <90%** once the generation run completes.

---

## Step 2 — every_item_required labelled set: **35 entries** (complete; LLM evaluation pending)

### Composition

| Source | True | False | Total |
|---|---|---|---|
| Corpus (22 rubric levels, 19 open-response 小題) | 1 | 21 | 22 |
| Synthetic positives | 3 | 0 | 3 |
| Near-misses | 0 | 10 | 10 |
| **Total** | **4** | **31** | **35** |

### Corpus scan

Complete scan of all NS few_shot subfolders for rubric entries using 皆/均/都/全部 in Constructed-response 小題. Both rubric key shapes handled (`{code, 規準說明}` and legacy `{編碼, 說明}`). Count: **22 rubric levels in 19 unique 小題** — matches the ticket's stated 22/19.

**Only one True**: `fasting-method seq=3 code=2` — 「正確寫出兩個合理且有所不同的結論，且均基於組間比較」. The 均 applies to student-generated conclusions (open scope); any off-scope conclusion → [1].

**All other 21 corpus entries (False)**: 皆/均/都/全部 applies to question-pre-named members (named experimental groups, framed table cells, named answer choices, named meteorological systems, named positions), OR is code=0/code=1 rather than code=2, OR 全部 means "all wrong" in a code=0 criterion.

Notable cases:
- `weather-proverbs seq=2` contributes 3 entries (code=2, 1, 0) — same 小題, three rubric levels, all False.
- `蛙勒 seq=2` contributes 2 entries (code=2, 0) — same 小題.
- `自製夢幻飲品 seq=6` is in `Simple-multiple-choice/` folder but `題型=Constructed response` — included.
- `entomopathogenic-fungi seq=3` is in `Constructed-response/` but its parent item has `題型=Complex-multiple-choice` for seq=1 — seq=3 is Constructed-response and IS included.

### Near-miss design

10 near-miss entries (all False) weighted toward the two failure modes the ticket flags:
- **Kind A** (5 entries): 皆/均 over named members of a framed set — named variable types, named experimental groups, named answer dimensions, three named plants.
- **Kind B** (5 entries): 皆/均 over parts of ONE required answer chain — the ticket example 「主張與數據皆須相符」 and four analogues (受力+加速度, 機制+影響, 觀察+推論, 假設+設計).

### FP/FN risks

- **FP risk**: model sees 均/皆 and predicts True without checking whether scope is student-generated.
- **FN risk**: model reads `code=0` "全部錯誤" entries as full-scope-EIR and predicts True (should be False — "全部" here means "all student answers are wrong", not "every student-written extra item must satisfy a condition").

**Recommendation:** Note only until the confusion matrix is measured (requires API credits).

**PENDING — rerun command:**
```
uv run python scripts/research/rubric_873_harness.py
```
(reads cache first; only unevaluated entries make new API calls)

---

## Step 3 — Generation-run rubric writing (pending)

30 小題 selected from NS Constructed-response corpus:
- 3 need #650 conversion first (fasting-method|3, washing-machine-physics|5, 胡椒蛾|3)
- 27 ready to send to rubric-writing prompt with `OPEN_RESPONSE_RUBRIC_RULE`

**PENDING — rerun command (same as Step 2 above):**
```
uv run python scripts/research/rubric_873_harness.py
```

---

## Verifier field change

The `every_item_required` field is already added to `VERIFIER_USER_TEMPLATE_V2` and `VERIFIER_SYSTEM_V2` in `scripts/research/rubric_872_harness.py`. It is NOT wired into the production verifier (`src/natural_sciences/verifier.py` or `src/social_studies/verifier.py`) — that is the production change for #873.

## Files committed

- `docs/research/2026-09-27-873-every-item-required.md` — full report
- `docs/research/873-every-item-required/ticket-comment.md` — this file
- `docs/research/873-every-item-required/responses.jsonl` — LLM cache (0 entries)
- `scripts/research/rubric_873_harness.py` — harness (35 labelled set entries, 30 gen-run items)
