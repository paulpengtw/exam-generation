# Comment for GitHub issue #873

Research run complete. Report: `docs/research/2026-09-27-873-every-item-required.md`

## What was measured

**Model:** `claude-opus-4-6` at `high` effort (default `model_verify`). Total new LLM calls: 0 (API credits exhausted). Steps 2 and 3 are pending re-run.

---

## Step 1 — EXTRA_ITEMS_FIXED_SENTENCE baseline: **0/157 = 0.0%** (measured, complete)

Scanned all 157 [2] rubric entries in the Constructed-response NS few-shot corpus.
None contains the `#871` fixed sentence:
```
學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。
```
This is expected — the sentence was introduced in #871 after the corpus was written.

**Goal for generation-run (Step 3):** ≥90% of newly-generated [2] entries contain the fixed sentence. Recommend **Fail if <90%** once the generation run completes.

---

## Step 2 — every_item_required labelled set (pending)

12 entries built (1 corpus True, 7 corpus False, 2 synthetic True, 2 near-miss False).

**Single corpus True case:** fasting-method seq=3 — 「請問以上實驗可以得出什麼結論？（請寫兩個結論）」 with [2]: 「正確寫出兩個合理且有所不同的結論，且均基於組間比較」. The 均 applies to student-generated conclusions (open scope); any off-scope conclusion → [1].

**All other corpus cases (False):** 皆/均 applies to question-pre-named members (實驗組, 器材角色, 表格資料點) — not to student-generated extras.

**FP risk:** near_miss|answer_chain|1 — 均 over steps of ONE answer chain; model may predict True.

**Recommendation:** Note only until the confusion matrix is measured.

**PENDING — rerun command:**
```
uv run python scripts/research/rubric_873_harness.py
```
(reads cache first; only unevaluated entries make new API calls)

---

## Step 3 — Generation-run rubric writing (pending)

30 小題 selected from NS Constructed-response corpus:
- 3 need #650 conversion first (fasting-method|3, washing-machine-physics|5, 胡椒蛾|3)
- 27 ready to send to rubric-writing prompt

**PENDING — rerun command (same as Step 2 above):**
```
uv run python scripts/research/rubric_873_harness.py
```

---

## Verifier field change

The `every_item_required` field is already added to `VERIFIER_USER_TEMPLATE_V2` and `VERIFIER_SYSTEM_V2` in `scripts/research/rubric_872_harness.py`. It is NOT wired into the production verifier (`src/natural_sciences/verifier.py` or `src/social_studies/verifier.py`) — that is the production change for #873.

## Files committed

- `docs/research/2026-09-27-873-every-item-required.md` — full report
- `docs/research/873-every-item-required/responses.jsonl` — LLM cache (0 entries)
- `scripts/research/rubric_873_harness.py` — harness (30 gen-run items, 12 labelled set entries)
