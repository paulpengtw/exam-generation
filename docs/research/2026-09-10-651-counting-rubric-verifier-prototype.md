# Research #651 — 計數式規準 Verifier Criterion Prototype (v2)

**Issue:** https://github.com/paulpengtw/exam-generation/issues/651  
**Parent map:** https://github.com/paulpengtw/exam-generation/issues/646  
**Script:** `scripts/research/rubric_counting_prototype.py`  
**Labelled set:** `docs/research/651-counting-rubric-prototype/labelled_set.json`  
**Responses:** `docs/research/651-counting-rubric-prototype/responses.jsonl`  
**Date:** 2026-09-10 (v2 correction commit same day)  
**Model:** claude-sonnet-4-6 (LLM_MODEL_EXECUTE, effort=medium, temperature=provider default)  
**Total LLM calls:** 218 (first run) + 45 (v2 correction for newly-classified entries) = 263

---

## 1. Bucket Totals vs #648

Loader fix: all three NS directories (Constructed-response/, Complex-multiple-choice/,
Simple-multiple-choice/) are loaded; **OUT_OF_SCOPE_C3 is assigned by 題型, not directory**.
Entries keyed by (file_stem, item_idx, 序號) to prevent seq-number collisions across items.

| Bucket | Reconstructed | #648 expected | Match |
|--------|---------------|---------------|-------|
| CLEAR | **17** | 17 | **OK** |
| BORDERLINE | **21** | 21 | **OK** |
| CONFORMING | **149** | 149 | **OK** |
| OUT_OF_SCOPE_C3 | **70** | 70 | **OK** |
| **Total** | **257** | **257** | **OK** |

**v1 loader gap explained.** The original loader assigned OOS by directory and skipped
CMC/SMC 題型 subquestions found inside the Constructed-response/ directory. This produced:
- 39 CMC/SMC 小題 in Constructed-response/ dir were silently dropped
- 12 Constructed-response 小題 in the CMC/SMC dirs were mis-labelled OOS
- Net: 218 entries instead of 257 (−39 new OOS entries not loaded, +12 misclassified
  CR→OOS). The 45 new calls in v2 cover the 39 newly-loaded OOS entries and re-run
  the 12 CR entries previously seen in cache as OOS.

---

## 2. The 38 Relabels Under 規則 C

**規則 C 判準:** The 小題's 題目 narration or declared 學習內容/科學能力 must frame the
complete component set in advance. Permitted framing sources under the 判準:
1. **題幹** — text of the question itself names the required components
2. **學習內容/科學能力** — declared curricular codes determine the required components
3. **科學概念必要環節** — the scientific concept is by nature composed of fixed necessary steps

**Not accepted:** framing by figure or table data alone (even when referenced in the stem).

### Summary

| Verdict | Count | Framing basis breakdown |
|---------|-------|------------------------|
| VIOLATES | **8** | 其他 (open stems) ×8 |
| LEGAL — 題幹 | **20** | stem names components explicitly |
| LEGAL — 科學概念必要環節 | **2** | H-W conditions; salt→temp→CO2 chain |
| LEGAL — 圖表資料 (contestable) | **8** | figure/table frames the set |
| **Total** | **38** | |

**Contestable entries = 8** (all LEGAL, all framing basis = 圖表資料). Under the strict
reading of 判準, these 8 revert to VIOLATES (图表 not in the accepted list).

### VIOLATES decisions (8 entries)

| File | Seq | 648 | Framing fragment that FAILS |
|------|-----|-----|----------------------------|
| entomopathogenic-fungi | 3 | CLEAR | 題幹問「有什麼好處？」，集合開放 |
| 生物防治2-1 | 1 | CLEAR | 「對本土生態環境的影響」未列影響對象集合 |
| fasting-method | 3 | BORDERLINE | 「兩個結論」指定個數未固定是哪兩個（【注意】） |
| fasting-method | 4 | BORDERLINE | 「至少兩份圖表資訊」是數量要求，非集合框定 |
| hot-pack | 2 | BORDERLINE | 未列出三個考量向度，集合未事前框定 |
| hot-pack | 7 | BORDERLINE | 「多種做法的可行性」未框定具體集合 |
| washing-machine-physics | 5 | BORDERLINE | 「什麼影響因素？」集合開放 |
| wind-corridor-effect | 1 | BORDERLINE | 「如何藉由實驗驗證」未框定實驗集合 |

### Contestable LEGAL entries (8, framing by 圖表資料)

| File | Seq | 648 | Framing evidence (data-based) |
|------|-----|-----|-------------------------------|
| 二氧化碳的產生與改變 | 1 | CLEAR | 附圖中固定兩個變因（光強度、溫度） |
| 大氣能見度 | 1 | CLEAR | 附表框定兩個觀測項目（AQI、相對溼度） |
| 大氣能見度 | 3 | CLEAR | 表格欄位固定（8格） |
| 蛙勒 | 4 | CLEAR | 附圖框定各月蛙種數，最多種月份（4、5、6月） |
| black-white-car-heat | 5 | BORDERLINE | 實驗表格框定兩個數據面向 |
| entomopathogenic-fungi | 5 | BORDERLINE | 實驗設計框定兩個統計缺陷 |
| entomopathogenic-fungi | 6 | BORDERLINE | 圖表資料結構框定兩個評估維度 |
| typhoon-database | 3 | BORDERLINE | 颱風追蹤資料框定路徑序列 |

### Non-contestable LEGAL (30 entries, framing by 題幹 or 科學概念)

Representative entries: entomopathogenic-fungi Seq 2 (題幹明寫兩個面向),
seawater-vertical-properties Seq 2 (給定5個固定項目), 拉塞福散射 Seq 2
(題幹明寫「第一個及最後一個」), 胡椒蛾的分子機制 Seq 3 (H-W定律5條件),
salt-soda Seq 4 (科學因果鏈必要環節), 蛙勒 Seq 2 (題幹明寫4項表格欄位).

---

## 3. Verifier Criterion Text

### System prompt

```
你是108課綱自然科學／社會領域素養導向命題的評分規準稽核員。
你的任務是判斷一道小題的評分規準是否違反下列「規則 C」。

## 規則 C（完整條文）

開放式建構反應題 / Constructed response 的評分規準必須依循以下規定：

  【禁止】不得以學生列舉的項目「數量」區分級距。

  【判準】要分辨是「完整度」還是「數量」，看該小題自身的題目敘述與所宣告的
  學習內容／科學能力，能否在事前把「完整答案的成分集合」框定下來：
  - 能框定 → 依補齊幾個成分分級為合法，且 [2] 必須逐一指名該集合的成員。
    （例：題目明寫「請從甲、乙兩個面向說明」；或該科學概念本身即由數個必要環節構成。）
  - 不能框定 → 不得依數量分級；[1] 必須以推理鏈條的缺口描述，
    不得寫成「僅提及其中之一」。

  【注意】題幹指定的「數量」不等於框定「集合」。「請寫兩個結論」只固定了個數，
  並未固定是哪兩個，因此屬於不能框定。

  【具體性】評分規準說明必須指名本小題的內容。不得使用「完整正確回答／部分正確／
  錯誤」這類可套用到任何題目的字樣。

注意：本規則僅適用於 Constructed response / 開放式建構反應題。
```

### User prompt template (key fields)

```json
{
  "set_framed": "<bool>",
  "framing_evidence": "<引用框定文字或說明無法框定，限50字>",
  "counting_violation": "<bool: 依數量分級且集合未框定>",
  "specificity_violation": "<bool: 使用完整正確回答等空泛語句>",
  "verdict": "<pass|fail: 任一violation為true則fail>",
  "details": "<fail時以[評分規準檢核]開頭，指示corrector修正方向>"
}
```

**Design note on `details`.** The field gives the corrector positive instruction: what quality criterion to substitute, how to distinguish [2] from [1] by reasoning completeness—never "count less."

---

## 4. Per-Bucket Confusion Matrices

Four matrix variants per bucket:
- **Standard** = 8 VIOLATES as ground-truth fail (rule_c_verdict = VIOLATES)
- **Strict** = 16 VIOLATES (adds the 8 contestable 圖表資料 entries)
- **Combined** = verdict = counting_violation OR specificity_violation
- **Counting-only** = verdict = counting_violation alone

Key: TP FN FP TN | recall FPR precision

### CLEAR bucket (n=17)

Standard: VIOLATES={2}, LEGAL={15}  
Strict: VIOLATES={6}, LEGAL={11}

| Scheme | TP | FN | FP | TN | recall | FPR |
|--------|----|----|----|----|--------|-----|
| standard, combined | 0 | 2 | 4 | 11 | 0% | 27% |
| standard, counting-only | 0 | 2 | 1 | 14 | **0%** | **7%** |
| strict, combined | 1 | 5 | 3 | 8 | 17% | 27% |
| strict, counting-only | 0 | 6 | 1 | 10 | 0% | 9% |

### BORDERLINE bucket (n=21)

Standard: VIOLATES={6}, LEGAL={15}  
Strict: VIOLATES={10}, LEGAL={11}

| Scheme | TP | FN | FP | TN | recall | FPR |
|--------|----|----|----|----|--------|-----|
| standard, combined | 4 | 2 | 5 | 10 | 67% | 33% |
| standard, counting-only | 4 | 2 | 1 | 14 | **67%** | **7%** |
| strict, combined | 6 | 4 | 3 | 8 | 60% | 27% |
| strict, counting-only | 5 | 5 | 0 | 11 | 50% | **0%** |

### CONFORMING bucket (n=149, all expected pass)

| Scheme | FP | TN | FPR |
|--------|----|----|-----|
| standard, combined | 41 | 108 | 28% |
| standard, counting-only | **0** | 149 | **0%** |
| strict, combined | 41 | 108 | 28% |
| strict, counting-only | 0 | 149 | **0%** |

### OUT_OF_SCOPE_C3 bucket (n=70, all expected pass; informative only — hook skips by 題型)

| Scheme | FP | TN | FPR |
|--------|----|----|-----|
| standard, combined | 1 | 69 | 1% |
| standard, counting-only | 0 | 70 | **0%** |
| strict, combined | 1 | 69 | 1% |
| strict, counting-only | 0 | 70 | **0%** |

The single OOS FP (combined): jumping-bottle-cap Seq 6 (Complex multiple-choice) triggered
by the 【具體性】 clause only. The counting-only check generates zero OOS false positives.

---

## 5. False Negatives on CLEAR (Missed Violations, Standard)

Both CLEAR VIOLATES were missed (recall=0% on standard CLEAR):

**1. entomopathogenic-fungi Seq 3**  
Rule C: VIOLATES — 題幹問「有什麼好處？」  
Rubric: `[2] 同時提及保護行避免藥液污染，以及多區塊設計避免位置效應`  
Model: passed (details empty). The model inferred the two design features from
experimental context and treated them as a frameable set from scientific knowledge,
bypassing the requirement that framing appear in the stem text.

**2. 生物防治2-1 Seq 1**  
Rule C: VIOLATES — 影響對象未在題目中事前框定  
Rubric: `[2] 同時從對作物與人的潛在危害說明`  
Model: passed (details empty). The passage text likely names both 作物 and 人
explicitly, leading the model to treat the two targets as a framed set from context.

**Pattern.** Both FNs: model correctly recognises that the components are "scientifically
obvious" from the passage, but 判準 requires framing in the 題幹 or declared metadata,
not from general knowledge or passage inference. The criterion prompt needs a sharpening
example: "if the stem does not name the components explicitly, framing cannot be inferred
from general domain knowledge."

---

## 6. False Positives on OUT_OF_SCOPE_C3 (Combined Verdict)

1 entry (FPR=1%):

**jumping-bottle-cap Seq 6** (Complex multiple-choice)  
Rubric: `[2] 全對; [1] 部分正確; [0] 錯誤或空白`  
Triggered by: 【具體性】 clause only (generic rubric language)  
Model details: `[評分規準檢核] 評分規準使用「全對／部分正確／錯誤」等空泛語句…`

Counting-only check: zero OOS false positives.

---

## 7. The 【具體性】 Clause — Separate Defect Class

The 28% FPR on CONFORMING (combined) is driven entirely by the 【具體性】 clause.
Counting-only FPR on CONFORMING = **0%** — the counting check produces zero false alarms
on the 149 entries the audited corpus classified as conforming.

The 41 CONFORMING entries flagged for specificity are not false positives in the strict
sense: they use "完整正確回答／部分正確／錯誤" language that genuinely violates the
【具體性】 clause. However, #648 labelled them CONFORMING because they contain no counting
language — the clause was added after the audit ran. They are a separate defect class
(空泛規準) not measured by #648.

---

## 8. Pooled Recall on All VIOLATES

Standard labeling (8 VIOLATES total):

| Verdict scheme | Caught | Total | Recall |
|----------------|--------|-------|--------|
| Combined (counting + specificity) | 4 | 8 | **50%** |
| Counting-only | 4 | 8 | **50%** |

Under standard labeling the two schemes catch the same 4 entries (washing-machine Seq 5,
hot-pack Seq 7, fasting Seq 3, wind-corridor Seq 1). The 4 caught are all BORDERLINE;
the 2 CLEAR VIOLATES are both FN.

Under strict labeling (16 VIOLATES), combined catches 7/16 = 44%; counting-only catches 5/16 = 31%.

---

## 9. Spot-Check: Corrector Repair Feasibility

Three VIOLATES entries fed to the corrector system prompt with verifier `details` as
audit feedback. All three rewrites conformed to 規則 C:

**fasting-method Seq 3** — corrector correctly identified the two experimental comparison
groups (飲食控制組vs對照組, 運動組vs對照組), removed counting language, grounded [1]
in reasoning quality.

**hot-pack Seq 7** — corrector rewrote to quality-based (碰撞學說 mechanism), pivoting
from "two or more methods" to reasoning completeness.

**washing-machine-physics Seq 5** — corrector correctly replaced "2+ items" with
"可正確說明趨勢關聯", providing specific examples.

---

## 10. Decisions

### (a) Is the criterion worth shipping?

**Yes — ship the counting check; defer 【具體性】 to a later criterion.**

Evidence: counting-only check achieves **FPR=0% on CONFORMING** (0/149 false alarms)
and **FPR=0% on OUT_OF_SCOPE_C3** (0/70). BORDERLINE recall is 67% (4/6 standard VIOLATES
caught). The pooled recall across all 8 standard VIOLATES is 50% (4/8). These numbers are
acceptable for a first-pass verifier that correctly filters the canonical cases (washing-machine,
fasting Seq 3, hot-pack Seq 7, wind-corridor) with zero CONFORMING false alarms.
The 【具體性】 clause causes 28% FPR on CONFORMING and should ship as a separate criterion
after independent measurement.

### (b) Does borderline behaviour agree with 規則 C's text?

**Partially — standard recall on BORDERLINE is 67% (4/6); 2 missed.**

The 4 caught agree with 規則 C. The 2 missed (fasting Seq 4: "至少兩份圖表" inferred as
framed; hot-pack Seq 2: three engineering criteria inferred as implicit set) show the model
deferring to contextual knowledge when the 判準 requires explicit stem framing. The rule
text is correct; the model's inference capability slightly undermines it at the margin.
Mitigation: add a counter-example to the criterion prompt ("if the stem does not list the
criteria explicitly, knowledge of which criteria apply is not framing").

### (c) Should detected 計數式規準 FAIL or ANNOTATE?

**FAIL (passed=False → 修正 loop).**

Evidence: corrector spot-check shows all three repaired rubrics conform to 規則 C. The
verifier's `details` string gives the corrector actionable instruction (what quality
criterion replaces counting). 評分規準 is writable by both correctors (NS ~line 63 and
SS ~line 59 permit it; not in `FROZEN_SUBQUESTION_FIELDS`). Fail → repair is productive.

### (d) Yes/no on dedicated corrector repair path?

**No.** The existing NS/SS corrector seams already handle 評分規準 rewriting. The
verifier hook and the corrector communicate via `VerificationResult.details`. No new
pathway is needed.

### (e) Production gate

The hook must check 題型 deterministically before any LLM call:

```python
if "Constructed" not in sq.題型 and "開放式" not in sq.題型:
    return result  # C3 gate — no LLM call
```

The OOS FPR = 0% (counting-only) is informative about the model's generalization behaviour;
the shipped hook never reaches OOS subquestions because the gate eliminates them.

---

## 11. Proposed Hook Code Shape (Follow-up, Not Implemented Here)

```python
def _ns_rubric_counting_check_hook(
    question: ExamQuestion,
    result: VerificationResult,
    client: LLMClient,
) -> VerificationResult:
    """Detect 計數式規準 (Rule C counting violations) on Constructed-response
    subquestions.  Mirrors _ss_rubric_scale_check_hook's seam.
    Registered in _NS_POST_VERIFY_HOOKS.
    """
    issues: list[str] = []
    for sq in question.subquestions:
        # C3 gate — deterministic, no LLM call for non-open-response
        if "Constructed" not in (sq.題型 or "") and "開放式" not in (sq.題型 or ""):
            continue
        if not sq.評分規準:
            continue
        response = client.generate_json(
            system=RUBRIC_COUNTING_SYSTEM,
            user=_build_counting_user(sq),
            purpose="verify",
        )
        # Ship only the counting check; specificity is a separate criterion
        if response.get("counting_violation"):
            issues.append(
                f"第{sq.序號}題："
                + (response.get("details") or "[評分規準檢核] 請依規則 C 改寫評分規準")
            )
    if issues:
        result.details = result.details.rstrip()
        result.details += "\n\n" + "\n".join(issues)
        result.passed = False
    return result
```

Registered in `_NS_POST_VERIFY_HOOKS`; SS equivalent in `src/social_studies/verifier.py`.

---

## Appendix: Method Notes

- **Loader:** all three NS directories loaded; OOS classified by 題型 not directory; keyed
  by (file_stem, item_idx, seq); v1 cache keys (file_stem|seq) migrated to v2 (file_stem|0|seq).
- **Fixed ordering:** `sorted(glob("*.json"))` per directory, then CMC, then SMC, then SS CSV.
- **Rate limiting:** 0.3 s between calls.
- **Caching:** `responses.jsonl` — v2 key format `{file_stem}|{item_idx}|{seq}`.
- **Rubric schema:** both `{code, 規準說明}` and `{編碼, 說明}` handled.
- **Total LLM calls:** 218 (v1) + 45 (v2 new entries) = 263.
- **No temperature override; effort=medium.**
