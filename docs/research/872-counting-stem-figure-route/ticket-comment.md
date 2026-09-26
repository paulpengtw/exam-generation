# Comment for GitHub issue #872

Research run complete. Report: {REPORT_URL}

## What was measured

**Model:** `claude-opus-4-6` at `high` effort (default `model_verify`). Total new LLM calls: 11. Cache hits: 257 (from #651 warm cache). API credits exhausted partway through step 3; steps 3 and 4 are partial.

---

## Step 2 — Relabelled #651 recall: **5/9 = 55.6%** ✓

Applied the three #859 relabels (black-white-car-heat 5 and entomopathogenic-fungi 6 move from basis 圖表資料 → 題幹; entomopathogenic-fungi 5 moves LEGAL → VIOLATES). All 257 entries served from the #651 warm cache (0 new calls). The recall matches the expected "5 of 9" baseline from the #859 resolution.

**4 FNs share one failure mode:** the model infers implicit framing from the rubric or known answer components, rather than requiring the stem to frame the set explicitly. A counter-example in the prompt ("the rubric naming the members does NOT frame the set") targets this pattern. Counting-only FP on LEGAL/CONFORMING/OOS: **0**.

---

## Step 3 — counting_stem (partial, 11/20 entries evaluated)

API credits ran out after 11 entries. The 9 unevaluated entries are all label=False dangerous-FP cases.

| Evaluated (n=11) | TP | FN | FP | TN |
|---|---|---|---|---|
| | 6 | 1 | 0 | 4 |

Recall (positives): 6/7 = 85.7%. FPR (negatives): 0/4 = 0.0%.

**One FN:** `胡椒蛾的分子機制` seq=3 ("至少列舉三項" over Hardy-Weinberg's 5 conditions). The model applied exception F4 (scientifically necessary components), missing that "at least 3 of 5" is 「任N項」 of a larger set — which #650 explicitly bans. Fixable with a prompt counter-example.

**Recommendation:** **Note only** until the 9 remaining entries are evaluated. If re-run shows 0 FP there, upgrade to **Fail**.

**details sentence (for when Fail):**  
`[評分規準檢核] 此小題以數字或「有哪些」要求學生從開放集合列舉——請改寫題目逐一點名各成員（「一個X與一個Y」），或改為只要求學生列出一項。`

---

## Step 4 — Figure route (0/9 evaluated)

Harness built: 4 chart images rendered, 9 matched-pair items (4 read-off, 3 supplies-data, 2 absent-members). API credits exhausted before any LLM call. **Cannot report a confusion matrix.** Caveat: server environment has no CJK font; chart labels rendered as tofu (numeric values correct).

**Recommendation:** Re-run when credits are available. Consider alphanumeric-only chart labels to avoid CJK font dependency.

---

## Files committed

- `docs/research/651-counting-rubric-prototype/labelled_set_relabelled.json` — relabelled set (original preserved)
- `docs/research/2026-09-27-872-counting-stem-figure-route.md` — full report
- `docs/research/872-counting-stem-figure-route/run_summary.json` — machine-readable results
- `docs/research/872-counting-stem-figure-route/responses.jsonl` — LLM cache (11 entries)
- `docs/research/872-counting-stem-figure-route/images/` — 4 chart PNGs
- `scripts/research/rubric_872_harness.py` — harness (extensible for #873 `every_item_required`)
