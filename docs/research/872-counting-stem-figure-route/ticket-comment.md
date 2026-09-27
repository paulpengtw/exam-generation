# Comment for GitHub issue #872

Labelled set and harness committed; partial results from 11 of 25 evaluated entries. Steps 3 (14 unevaluated) and 4 (0 evaluated) are PENDING — API credit exhausted 2026-09-27. Report: {REPORT_URL}

## What was measured

**Model:** `claude-opus-4-6` at `high` effort (default `model_verify`). Total new LLM calls: 11. Cache hits: 257 (from #651 warm cache). API credits exhausted partway through step 3; steps 3 (partial) and 4 (zero evaluations) are pending re-run.

---

## Step 2 — Relabelled #651 recall: **5/9 = 55.6%** (measured, complete)

Applied the three #859 relabels (black-white-car-heat 5 and entomopathogenic-fungi 6 move from basis 圖表資料 → 題幹; entomopathogenic-fungi 5 moves LEGAL → VIOLATES). All 257 entries served from the #651 warm cache (0 new calls). The recall matches the expected "5 of 9" baseline from the #859 resolution.

**4 FNs share one failure mode:** the model infers implicit framing from the rubric or known answer components, rather than requiring the stem to frame the set explicitly. A counter-example in the prompt ("the rubric naming the members does NOT frame the set") targets this pattern. Counting-only FP on LEGAL/CONFORMING/OOS: **0**.

---

## Step 3 — counting_stem (partial, **11 of 25** entries evaluated)

API credits ran out after 11 entries. The labelled set has 25 entries; 14 are unevaluated (9 entries were null when credits ran out in the initial 20-entry run; 5 new entries added after expansion).

| Evaluated (n=11) | TP | FN | FP | TN |
|---|---|---|---|---|
| | 6 | 1 | 0 | 4 |

Recall on evaluated positives: **6/7 = 85.7%**. FPR on evaluated negatives: **0/4 = 0.0%**.

**One FN:** `胡椒蛾的分子機制` seq=3 ("至少列舉三項" over Hardy-Weinberg's 5 conditions). The model applied exception F4 (scientifically necessary components), missing that "at least 3 of 5" is 「任N項」 of a larger set — which #650 explicitly bans. Fixable with a prompt counter-example.

**Recommendation:** **Note only** until the 14 unevaluated entries are evaluated. If re-run shows 0 FP there, upgrade to **Fail**.

**details sentence (for when Fail):**
`[評分規準檢核] 此小題以數字或「有哪些」要求學生從開放集合列舉——請改寫題目逐一點名各成員（「一個X與一個Y」），或改為只要求學生列出一項。`

**PENDING — rerun command:**
```
uv run python scripts/research/rubric_872_harness.py
```
(reads cache first; only unevaluated entries make new API calls)

---

## Step 4 — Figure route (0/9 evaluated)

Harness built: 4 chart images rendered (now with legible CJK labels via WenQuanYi Zen Hei registered before matplotlib import), 9 matched-pair items (4 read-off, 3 supplies-data, 2 absent-members). Charts B and C switched from line_chart (unsupported `series` format) to histogram. API credits exhausted before any LLM call. **Cannot report a confusion matrix.**

**Recommendation:** Re-run when credits are available.

**PENDING — rerun command (same as step 3 above):**
```
uv run python scripts/research/rubric_872_harness.py
```

---

## Files committed

- {REPORT_URL} — full report
- `docs/research/651-counting-rubric-prototype/labelled_set_relabelled.json` — relabelled set (original preserved)
- `docs/research/872-counting-stem-figure-route/run_summary.json` — machine-readable results
- `docs/research/872-counting-stem-figure-route/responses.jsonl` — LLM cache (11 counting_stem entries evaluated; 9 figure-route entries empty)
- `docs/research/872-counting-stem-figure-route/images/` — 4 chart PNGs (CJK labels legible)
- `scripts/research/rubric_872_harness.py` — harness (25 counting_stem entries, 9 figure-route entries)
- `scripts/research/rerender_872_images.py` — standalone re-render helper with CJK font fix
