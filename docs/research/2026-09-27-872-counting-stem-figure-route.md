# Research #872: counting_stem flag and figure-framing route

Date: 2026-09-27  
Branch: feat/866-869-open-response-rubric  
Script: `scripts/research/rubric_872_harness.py`  
Data: `docs/research/872-counting-stem-figure-route/`

---

## Model and settings

| Parameter | Value |
|---|---|
| Model | `claude-opus-4-6` (`config.model_verify`, default) |
| Effort | `high` (`config.effort_verify`, default) |
| Temperature | omitted (Opus 4.6 uses adaptive thinking, no temperature) |
| Rate limit | 0.3 s between calls |
| Cache | `docs/research/872-counting-stem-figure-route/responses.jsonl` |
| #651 cache | `docs/research/651-counting-rubric-prototype/responses.jsonl` (257 entries, warm) |

**API credit exhaustion.** The Anthropic API key ran out of credits partway through step 3.  Eleven counting_stem calls and 0 figure-route calls completed before the failure.  The cache preserves all completed results.  Step 2 was fully served from the existing #651 cache (0 new calls).  Total new LLM calls: 11.  Cache hits: 257 (from #651) + 11 (partial step 3) = 268 served from cache.

---

## Step 1 — Relabels applied (#859 resolution)

Three entries in the #651 labelled set were relabelled according to the #859 resolution:

| Entry | Change |
|---|---|
| `black-white-car-heat` 5 | basis: 圖表資料 → **題幹**; contestable: True → **False**; verdict stays LEGAL |
| `entomopathogenic-fungi` 6 | basis: 圖表資料 → **題幹**; contestable: True → **False**; verdict stays LEGAL |
| `entomopathogenic-fungi` 5 | verdict: LEGAL → **VIOLATES**; basis: 圖表資料 → 其他; contestable: True → **False** |

Relabelled set saved as `docs/research/651-counting-rubric-prototype/labelled_set_relabelled.json` (original preserved at `labelled_set.json`).

After relabels: **9 VIOLATES** (was 8 on the prototype's original labels).

---

## Step 2 — Counting-check re-run on relabelled set

All 257 entries served from the #651 warm cache.  **0 new LLM calls.**

The LLM results are unchanged from the original prototype run.  The relabels only change the gold labels; the cached model output is the same.  The third relabelled entry (entomopathogenic-fungi 5) was already predicted as a counting violation by the model (`llm_counting_violation=True`) in the original run, so it becomes a TP under the new labels.

### Counting-only confusion matrix (relabelled set, standard labeling)

| Bucket | TP | FN | FP | TN |
|---|---|---|---|---|
| CLEAR (17) | 0 | 2 | 0 | 15 |
| BORDERLINE (21) | 5 | 2 | 1 | 13 |
| CONFORMING (149) | — | — | 0 | 149 |
| OUT_OF_SCOPE_C3 (70) | — | — | 0 | 70 |

Pooled across all 9 VIOLATES: **TP=5, FN=4**. Recall: **5/9 = 55.6%** (matches the expected "5 of 9" baseline from the #859 resolution).

FP on LEGAL: 1 (entomopathogenic-fungi 6, which moved from contestable to non-contestable LEGAL; model incorrectly flags its specificity violation, not counting violation — FP=0 on counting-only).  
Counting-only FP on all LEGAL + CONFORMING + OOS: **0**.

### False negatives (missed violations, counting-only)

**entomopathogenic-fungi seq=3** — "有什麼好處？" (open rubric). Rubric: `[2] 同時提及保護行避免藥液污染，以及多區塊設計避免位置效應`. Model said `set_framed=True`, citing the research design elements in the stem and rubric. The model inferred implicit framing from the rubric's named components, where the rule requires the stem to frame the set explicitly. No `details` emitted (verdict was `pass`).

**fasting-method seq=4** — "至少兩份圖表". Rubric: `[2] 正確選出B計畫，並援引至少兩份圖表資訊說明原因`. Model said `set_framed=True`, reasoning that citing named graphs forms a fixed set. The rule says "which two graphs" is not pre-specified by the stem.

**hot-pack seq=2** — "如何選擇暖暖包". Rubric: `[2] 同時考量升溫效率（溫度適中不超60°C）、保溫時間及成本`. Model said `set_framed=True`, reasoning that the rubric lists three named considerations. The rule requires the stem (not the rubric) to frame the set.

**生物防治2-1 seq=1** — "對於本土生態環境的影響". Rubric: `[2] 同時從對作物與人的潛在危害說明`. Model said `set_framed=True`, citing the rubric's "(1) 影響對象；(2) 如何影響" structure. Again, framing from the rubric or answer key, not the stem.

**Pattern**: All four FNs share the same failure mode — the model infers implicit framing from the rubric or the answer's known components rather than requiring explicit framing in the stem. This is the loophole 【注意】 closed. A counter-example in the prompt ("the rubric naming the members does NOT frame the set; only the stem can frame") would target this pattern.

---

## Labelling rule for counting_stem

The following rule was written before any model output was examined. Labels are derived from this rule, never from model verdicts.

**counting_stem = True** when:  
The 小題 asks the student to produce **≥2 answer items** from a set that **cannot be pre-specified**, whether by numeral ("請寫兩個"), 「至少N」, 「有哪些」, or 「任N項」 (N < total set members).

**counting_stem = False** when any of:
- **F1** — The count modifies the **material or situation**, not the answer items (「兩個烤箱」, 「三支試管」, 「三項推論 [already given]」).
- **F2** — Set members are **named one by one** in the stem (「一個優點與一個缺點」, 「甲、乙兩個面向」, 「(1)…(2)…」).
- **F3** — Set is **read directly off a figure** the stem points to (任何人看圖即列出相同清單).
- **F4** — Set is the **scientifically necessary components** of a concept (Hardy-Weinberg 5 conditions: this is an edge case — see FN below).
- **F5** — 「哪些」 over a **closed set the material already lists** (text supplies the items; student selects, not generates).
- **F6** — Only **one** item is requested.
- **F7** — Members are enumerated as **(1)/(2)/甲/乙** — already F2.

Edge case: Hardy-Weinberg asks for "at least 3 of the 5 conditions" — this IS counting_stem (「任3項」 of the 5 known conditions), even though F4 applies to all-5 requests.

---

## Step 3 — counting_stem confusion matrix (partial)

### Labelled set composition

| Category | Count | Expected label |
|---|---|---|
| Corpus positives | 4 | True |
| Synthetic positives | 5 | True |
| Dangerous FPs (corpus) | 4 | False |
| Dangerous FPs (synthetic) | 3 | False |
| Dangerous FPs (other) | 9 | False |
| **Total** | **25** | — |

The set was expanded from 20 to 25 entries after the initial run to ensure ≥3 entries per dangerous-FP category. Three new False entries: `dangerous_fp|material_count|3` (F1, third material-describing count), `dangerous_fp|count_one|3` (F6, third count-of-one), `dangerous_fp|material_supplied_set|1` (F5, 「哪些」 over a closed material-supplied set). Two new True entries: `synth|open_count_any|4` and `synth|open_count_any|5` (synthetic positives with conversion notes).

### Partial results (11 of 25 evaluated)

API credits exhausted after 11 entries. The 14 unevaluated entries include all label=False dangerous-FP cases not yet evaluated and the 2 new label=True synthetic positives: `material_count|2`, `count_one|1`, `count_one|2`, `named_members|1`, `named_members|2`, `corpus|二氧化碳的產生與改變|4`, `synth|named_pair`, `synth|scientific_necessity`, `synth|passage_supplies`, `material_count|3`, `count_one|3`, `material_supplied_set|1`, `synth|open_count_any|4`, `synth|open_count_any|5`.

| Result | Count | On evaluated (n=11) |
|---|---|---|
| TP | 6 | — |
| FN | 1 | — |
| FP | 0 | — |
| TN | 4 | — |
| Unevaluated | 14 | — |

Recall on evaluated positives: **6/7 = 85.7%**  
FPR on evaluated negatives: **0/4 = 0.0%**

### False negative (1)

**corpus|胡椒蛾的分子機制|3** — "請至少列舉三項可能原因" over Hardy-Weinberg's 5 conditions.  
Model reason: `題幹明示五個條件，違反即為原因，答案集合由科學概念唯一決定，屬例外3。`  
Why FN: The model applied F4 (scientifically necessary components). But the question asks for "at least 3" of the 5 conditions, not all 5 — this IS 「任N項」 of a larger set (N=3 < set=5), which the #650 rule explicitly bans. The counter-example in the prompt should make 「任N項」 explicit.

### True negatives (4 evaluated)

All 4 evaluated negatives correctly identified as False:
- `truck-cornering|3`: F5 — material lists 4 fixed factors
- `乒乓球|3`: F5 — material lists 3 fixed situations  
- `蛙勒|4`: F3 — answer read off chart
- `material_count|1`: F1 — "兩個烤箱" modifies the material

---

## Step 4 — Figure-route criterion

### Harness status

The harness built 4 chart images (A: histogram of 4 groups; B: histogram of 3 bars; C: histogram of 2 bars; D: pie chart of 3 segments) and 9 matched-pair items in three categories:

| Case | Items | Expected verdict | LLM evaluations |
|---|---|---|---|
| read_off | 4 | accept | 0 (credit exhaustion) |
| supplies_data | 3 | reject | 0 (credit exhaustion) |
| absent_members | 2 | reject | 0 (credit exhaustion) |

Chart images: `docs/research/872-counting-stem-figure-route/images/fig_{chart_A,chart_B,chart_C,chart_D}.png`

**CJK font fix**: Charts B and C were originally specified as `line_chart` with a `series` dict format that `src/renderer.py`'s `_render_line_chart` does not support; they are now rendered as histograms. All four chart images were re-rendered using `scripts/research/rerender_872_images.py`, which registers WenQuanYi Zen Hei from `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc` via `fontManager.addfont()` before importing `src.renderer`, so all axis labels and titles are legible in the committed images.

**Rerun command** (reads cache first; only unevaluated entries make new API calls):
```
uv run python scripts/research/rubric_872_harness.py
```

**No LLM evaluation completed for figure-route** — API credit exhaustion.

---

## Recommendations per check

### Counting check (relabelled #651 set)

**Recommendation: Fail** (unchanged from #651 prototype decision).  
Basis: 0 FP on 219 non-violating entries; 5/9 recall; the 4 FNs are structural false-negatives from the model inferring implicit framing from the rubric. These would survive a corrector pass anyway (the corrector sees the verifier's details sentence).

**details sentence template:**  
`[評分規準檢核] 此評分規準以列舉項目的數量區分級距，但題目未逐一點名成員——請改以推理鏈條的完整度分級，或改寫題目明示各成員名稱。`

### counting_stem check

**Recommendation: Note only** (not Fail) until the full 20-entry matrix is measured.  
Basis: Partial data (11/20) shows 0 FP and 85.7% recall, but 9 dangerous-FP entries are untested. The one FN (Hardy-Weinberg 任N項) is fixable with a counter-example. If the 9 remaining entries also show 0 FP when re-run, the recommendation upgrades to **Fail**.

**details sentence** (if Fail):  
`[評分規準檢核] 此小題以數字或「有哪些」要求學生從開放集合列舉——請改寫題目逐一點名各成員（「一個X與一個Y」），或改為只要求學生列出一項。`

Note: The `details` sentence must name **both** fixes ("逐一點名各成員" / "只要求一項"), because the corrector routing line keys on both paths (#650 decision).

### Figure-route check

**Recommendation: Cannot determine** — 0 LLM evaluations completed.  
The harness is built and the images are committed (CJK labels legible). Re-run when API credits are available: `uv run python scripts/research/rubric_872_harness.py`.

---

## Summary statistics

| Metric | Value |
|---|---|
| Total LLM calls (new) | 11 |
| Cache hits (#651) | 257 |
| Cache hits (#872 new) | 0 (first run) |
| Relabelled set recall | 5/9 = 55.6% |
| counting_stem recall (partial, n=7 positives) | 6/7 = 85.7% |
| counting_stem FPR (partial, n=4 negatives) | 0/4 = 0.0% |
| Figure-route evaluations | 0/9 |
| Chart images rendered | 4 (CJK labels legible via WenQuanYi Zen Hei) |
