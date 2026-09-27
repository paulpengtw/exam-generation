# Comment for GitHub issue #873

Labelled set and harness committed. Steps 2 (flag matrix) and 3 (generation run) are PENDING — API credit exhausted 2026-09-27. Report: {REPORT_URL}

## Step 1 — EXTRA_ITEMS_FIXED_SENTENCE baseline: **0/143 = 0.0%** (measured)

Scanned all 143 [2] rubric entries in the NS few-shot corpus with `題型=Constructed response` (all three `few_shot/` subfolders, bucketed by 小題's own `題型` field). None contains the `#871` fixed sentence:
```
學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。
```
This is expected — the sentence was introduced in #871 after the corpus was written. Once the generation run completes (Step 3), it measures the rate at which the 1/2/1 hook will send freshly-generated rubrics to the corrector.

---

## Step 2 — every_item_required labelled set: **35 entries** (committed; LLM evaluation PENDING)

### Composition

| Source | True | False | Total |
|---|---|---|---|
| Corpus (22 rubric levels, 19 open-response 小題) | 1 | 21 | 22 |
| Synthetic positives | 3 | 0 | 3 |
| Near-misses | 0 | 10 | 10 |
| **Total** | **4** | **31** | **35** |

Only one True: `fasting-method seq=3 code=2` — 「正確寫出兩個合理且有所不同的結論，且均基於組間比較」. All other 21 corpus entries (皆/均/都/全部 over framed members, or code=0/1) are False.

**PENDING — rerun command:**
```
uv run python scripts/research/rubric_873_harness.py
```

---

## Step 3 — Generation-run input: **30 items** (committed; run PENDING)

30 小題 selected from NS Constructed-response corpus. All 30 are fed into the rubric-writing prompt. The 3 counting-stem items use stems converted in the harness per #650 decision 5:

| Item | Original stem | Converted stem | Rule |
|---|---|---|---|
| `fasting-method\|0\|3` | 「請寫兩個結論」 | 「寫出一個結論，並指出它依據哪兩組的比較。」 | #650 decision 5: reduce to one (#871 canonical example) |
| `washing-machine-physics\|0\|5` | 「至少兩點…變因關係」 | 「分別說明：（1）負重對最高轉速的影響；（2）負重對整體運轉時間的影響。」 | #650 decision 5: name two observations from 答案解析 |
| `胡椒蛾的分子機制\|0\|3` | 「至少列舉三項」 | 「請說明一項造成黑色胡椒蛾等位基因比例增加的可能原因，並解釋該條件如何被違反。」 | #650 decisions 3 & 5: 「任3項」 of five conditions banned; reduce to one |

**PENDING — rerun command (same as Step 2 above):**
```
uv run python scripts/research/rubric_873_harness.py
```

---

## Verifier field

The `every_item_required` field is added to the harness verifier prompt in `scripts/research/rubric_873_harness.py`. It is NOT wired into the production verifier — per #871 decision 7, it is measured first (in this generation run) and wired as a fail flag only if the generation run shows the wording actually appears.

## Files committed

- {REPORT_URL} — full report
- `docs/research/873-every-item-required/ticket-comment.md` — this file
- `docs/research/873-every-item-required/responses.jsonl` — LLM cache (0 entries; pending re-run)
- `scripts/research/rubric_873_harness.py` — harness (35 labelled set entries, 30 gen-run items with #650 conversions)
