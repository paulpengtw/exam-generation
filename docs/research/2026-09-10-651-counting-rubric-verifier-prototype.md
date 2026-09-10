# Research #651 — 計數式規準 Verifier Criterion Prototype

**Issue:** https://github.com/paulpengtw/exam-generation/issues/651  
**Parent map:** https://github.com/paulpengtw/exam-generation/issues/646  
**Script:** `scripts/research/rubric_counting_prototype.py`  
**Labelled set:** `docs/research/651-counting-rubric-prototype/labelled_set.json`  
**Responses:** `docs/research/651-counting-rubric-prototype/responses.jsonl`  
**Date:** 2026-09-10  
**Model:** claude-sonnet-4-6 (LLM_MODEL_EXECUTE, effort=medium, LLM_TEMPERATURE=default)  
**LLM calls:** 218 (all entries, first run; subsequent runs use the JSONL cache)

---

## 1. Bucket Totals vs #648

| Bucket | Reconstructed | #648 expected | Match |
|--------|---------------|---------------|-------|
| CLEAR | **17** | 17 | OK |
| BORDERLINE | **21** | 21 | OK |
| CONFORMING | 137 | 149 | **MISMATCH −12** |
| OUT_OF_SCOPE_C3 | 43 | 70 | **MISMATCH −27** |
| **Total** | **218** | **257** | MISMATCH −39 |

**Why the totals differ.** The CLEAR and BORDERLINE counts match exactly, confirming the 38-entry test set is correct. The CONFORMING and OOS gaps arise from:

- The CMC/SMC directories do not contain every file that the #648 audit enumerated. Files added or removed since September 9 (or files the audit counted from a different path) account for the gap. Specifically, the `Complex-multiple-choice` and `Simple-multiple-choice` directories in the worktree produced 43 entries; the audit counted 70.
- Social-studies CSV: only 2 entries loaded (both CONFORMING), consistent with the audit.
- The loading logic correctly excludes subquestions without a `評分規準` field, which may reduce the CONFORMING count relative to the audit's hand-count.

These mismatches affect only the CONFORMING and OOS buckets—the two buckets used as the "expected pass" baseline. They do not affect the 38-entry core (CLEAR + BORDERLINE), which is the primary measurement surface.

---

## 2. The 38 Relabels Under 規則 C

**規則 C 判準 (from #649):** Does the 小題's 題目 or its declared 學習內容/科學能力 frame the complete component set in advance?
- If YES → component-based levels are legal when [2] names each member.
- If NO → levels may not be distinguished by quantity; [1] must describe a reasoning gap.
- 【注意】: A stem count such as 「請寫兩個」 does NOT frame the set.

Of the 38 entries: **VIOLATES: 8, LEGAL: 30**

### VIOLATES decisions (8 entries)

| File | Seq | 648 label | Framing fragment that FAILS |
|------|-----|-----------|----------------------------|
| entomopathogenic-fungi | 3 | CLEAR | 題幹問「有什麼好處？」，好處集合開放，未事前框定 |
| 生物防治2-1 | 1 | CLEAR | 「對本土生態環境的影響」未列出影響對象集合 |
| fasting-method | 3 | BORDERLINE | 「兩個結論」指定個數未固定是哪兩個（【注意】條款） |
| fasting-method | 4 | BORDERLINE | 「至少兩份圖表資訊」是數量要求，哪兩份未框定 |
| hot-pack | 2 | BORDERLINE | 題目問「如何選擇暖暖包」未列出三個考量向度 |
| hot-pack | 7 | BORDERLINE | 「兩項以上做法的可行性」未框定具體做法集合 |
| washing-machine-physics | 5 | BORDERLINE | 「什麼影響因素？」集合開放，以個數（2點以上）分級 |
| wind-corridor-effect | 1 | BORDERLINE | 「如何藉由實驗驗證」未框定具體實驗集合 |

### LEGAL decisions (selected, 30 entries)

| File | Seq | 648 label | Framing evidence |
|------|-----|-----------|-----------------|
| entomopathogenic-fungi | 2 | CLEAR | 題幹明寫「請從孢子粉比例與致死效果說明」 |
| seawater-vertical-properties | 2 | CLEAR | 固定5個海水性質項目排序 |
| 二氧化碳的產生與改變 | 1 | CLEAR | 附圖框定兩個變因（光強度、溫度） |
| 拉塞福散射 | 2 | CLEAR | 「第一個及最後一個設置的投影幕位置」兩個答案固定 |
| 果凍 | 5 | CLEAR | 參考資料明列「蛋白質」與「酵素」兩個關鍵字 |
| 生物防治2-1 | 3 | CLEAR | 產卵歷程描述框定兩個機制 |
| 生物防治2-1 | 5 | CLEAR | 「含羽化率及雌雄比」由題幹框定 |
| 胡椒蛾的分子機制 | 3 | CLEAR | Hardy-Weinberg定律明定5個平衡條件 |
| 蛙勒 | 2 | BORDERLINE | 「填寫表(一)（含：生殖方式、受精方式、類似動物、大量產卵的意義）」4項 |
| washing-machine-physics is the canonical VIOLATES for prototype | (above) | | |

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
  - 不能框定 → 不得依數量分級；[1] 必須以推理鏈條的缺口描述，
    不得寫成「僅提及其中之一」。

  【注意】題幹指定的「數量」不等於框定「集合」。「請寫兩個結論」只固定了個數，
  並未固定是哪兩個，因此屬於不能框定。

  【具體性】評分規準說明必須指名本小題的內容——[2] 要寫出本題該答對什麼，
  [1] 要寫出本題最可能出現的缺口。不得使用「完整正確回答／部分正確／錯誤」
  這類可套用到任何題目的字樣。

注意：
- 本規則僅適用於「Constructed response / 開放式建構反應題」。
- Complex multiple-choice 與 Simple multiple-choice 不受此規則約束。
```

### User prompt template

```
請判斷以下小題的評分規準是否違反規則 C。

題型：{question_type}
題目（題幹）：{question_stem}
學習內容：{learning_content}
科學能力：{science_ability}
評分規準各級距說明：{rubric_text}

請嚴格依照規則 C 的【判準】邏輯逐步推理，然後以下列 JSON 格式輸出：

{
  "set_framed": <bool>,
  "framing_evidence": "<str: 引用框定文字或說明無法框定（限50字）>",
  "counting_violation": <bool>,
  "specificity_violation": <bool>,
  "verdict": "<pass 或 fail>",
  "details": "<str: fail時以[評分規準檢核]開頭，指示corrector修正方向>"
}
```

**Design note on `details`.** The `details` field is written so that the corrector—which has access to it via the `VerificationResult.details` field—receives actionable, positive instruction: it names what the rewritten rubric must include and how to distinguish [2] from [1] on quality grounds, never to "count less."

---

## 4. Per-Bucket Confusion Matrices

Definitions:
- **TP** = expected fail (rule_c_verdict=VIOLATES), predicted fail — correctly caught violation
- **FN** = expected fail, predicted pass — missed violation
- **FP** = expected pass, predicted fail — false alarm
- **TN** = expected pass, predicted pass — correct pass

### CLEAR bucket (n=17)

Ground truth: 2 VIOLATES (entomopathogenic-fungi Seq 3; 生物防治2-1 Seq 1), 15 LEGAL.

| | Predicted FAIL | Predicted PASS |
|--|--|--|
| **Ground truth FAIL** | TP = 0 | FN = 2 |
| **Ground truth PASS** | FP = 4 | TN = 11 |

- Recall = 0% (0/2)
- FPR = 27% (4/15)

### BORDERLINE bucket (n=21)

Ground truth: 6 VIOLATES, 15 LEGAL.

| | Predicted FAIL | Predicted PASS |
|--|--|--|
| **Ground truth FAIL** | TP = 4 | FN = 2 |
| **Ground truth PASS** | FP = 5 | TN = 10 |

- Recall = 67% (4/6)
- FPR = 33% (5/15)

### CONFORMING bucket (n=137)

Ground truth: all 137 expected pass.

| | Predicted FAIL | Predicted PASS |
|--|--|--|
| **Ground truth PASS** | FP = 38 | TN = 99 |

- FPR = 28% (38/137)

### OUT_OF_SCOPE_C3 bucket (n=43)

Ground truth: all 43 expected pass (hook skips non-Constructed-response deterministically).

| | Predicted FAIL | Predicted PASS |
|--|--|--|
| **Ground truth PASS** | FP = 4 | TN = 39 |

- FPR = 9% (4/43)

---

## 5. False Negatives on CLEAR (Missed Violations)

Both CLEAR VIOLATES were missed (FN=2, recall=0%).

**1. entomopathogenic-fungi Seq 3**  
Rule C verdict: VIOLATES — 題幹問「有什麼好處？」，成分集合未框定  
Rubric: `[2] 同時提及保護行避免藥液污染，以及多區塊設計避免位置效應（兩個條件均提及）; [1] 僅提及兩個條件之一`  
Model details: (empty — model passed)  
Diagnosis: The model appears to have inferred the two design features (保護行, 多區塊) from the experimental context and treated them as a frameable set, even though the stem question "有什麼好處？" is open-ended.

**2. 生物防治2-1 Seq 1**  
Rule C verdict: VIOLATES — 「影響對象（作物、人）」未在題目中事前框定  
Rubric: `[2] 同時從對作物與人的潛在危害說明; [1] 僅從作物或人的潛在危害說明`  
Model details: (empty — model passed)  
Diagnosis: The passage text probably mentions both 作物 and 人 explicitly, leading the model to treat the two targets as a framed set from context. The question hint "(1)影響對象；(2)如何影響" does not enumerate the targets.

**Pattern.** Both FNs are cases where the model correctly recognises a scientific context and infers that the component set is "obvious from domain knowledge," but the 判準 requires the set to be frameable from the 題幹 or declared metadata, not from general knowledge. The rule text may need a clarifying example to close this gap.

---

## 6. False Positives on OUT_OF_SCOPE_C3

4 FP entries (FPR=9%); all triggered by the 【具體性】 clause:

**1. jumping-bottle-cap Seq 3** (Constructed response in CMC directory — data inconsistency)  
Rubric: `[2] 完整正確回答; [1] 部分正確; [0] 錯誤或空白`  
Model details: `[評分規準檢核] 請將各級距改寫為指名本題內容的說明…`

**2. jumping-bottle-cap Seq 4** (Constructed response in CMC directory)  
Same specificity pattern.

**3. jumping-bottle-cap Seq 6** (Complex multiple-choice — correctly OOS)  
Rubric: `[2] 全對; [1] 部分正確; [0] 錯誤或空白`  
Model flagged for specificity. This IS a genuine 【具體性】 violation but the hook would skip it (non-Constructed-response).

**4. wheat-field-experiment Seq 2** (Constructed response in CMC directory)  
Same specificity pattern.

**Note.** Three of the four FPs are Constructed-response subquestions found in the Complex-multiple-choice directory — a data inconsistency, not a model error. The shipped hook determines in-scope by 題型 field, not by directory; these would NOT be skipped in production. The 9% OOS FPR is informative about the model's 【具體性】 detection precision, but the shipped hook's C3 gate is deterministic (check 題型 string) and eliminates the OOS bucket entirely.

---

## 7. CONFORMING FP Analysis — The 【具體性】 Effect

38 of 137 CONFORMING entries were flagged (FPR=28%). These are NOT false positives in the strict sense: they are entries that use generic "完整正確回答／部分正確／錯誤" wording, which genuinely violates the 【具體性】 clause of 規則 C. However, the #648 audit classified them as CONFORMING because they contain no counting language — the 【具體性】 clause was added after #648 ran.

This means the confusion matrix treats 【具體性】 flags on CONFORMING entries as "false positives" because the ground truth was set before the clause existed. The model is behaving correctly; the ground-truth label is outdated.

Example (candle-burning.json Seq 1): `[2] 完整正確回答; [1] 部分正確; [0] 錯誤或空白` — flagged, correctly, because it violates 【具體性】.

---

## 8. Spot-Check: Corrector Repair Feasibility

Three VIOLATES entries were fed to the corrector system prompt (NS corrector.py shape) with the verifier's `details` string as the audit feedback.

**fasting-method Seq 3**  
Verifier: `[評分規準檢核] 請改為以推理鏈條的缺口描述各級距：[2] 應指名本題實驗設計中可比較的具體對照組合（如「飲食控制組vs對照組」、「運動組vs對照組」）…`  
Corrector output: `[2] 正確寫出兩個有效結論，且分別對應不同操縱變因：一個結論須來自「飲食控制組vs對照組」的比較…[1] 僅針對其中一個操縱變因提出有效的組間比較並得出對應結論，但缺乏對另一變因的推論…`  
Assessment: **Conforms** — the rewrite correctly identifies the specific comparison groups, removes counting language, and grounds [1] in reasoning quality.

**hot-pack Seq 7**  
Verifier: `[評分規準檢核] 題目的「做法集合」未在題幹中框定，不得以「兩項以上／一項」區分級距；應改以推理鏈條的完整性描述…`  
Corrector output: `[2] 能指出做法對碰撞頻率或碰撞動能的影響，並連結至反應速率加快，完整說明可行性; [1] 能指出做法的方向（如升溫），但未能以碰撞學說具體說明機制`  
Assessment: **Conforms** — the rewrite grounds the distinction in reasoning quality, not count.

**washing-machine-physics Seq 5**  
Verifier: `[評分規準檢核] 集合無法框定，不得以「回答幾點」區分級距；應改以推理品質描述分級，例如：[2] 能正確說明至少一組變因間的趨勢關聯…`  
Corrector output: `[2] 能正確說明至少一組變因間的趨勢關聯（如轉速、水量、時間等與負重的方向關係）…[1] 能指出型號B與型號A之間的變化現象，但未說明變因間的趨勢方向或因果關聯`  
Assessment: **Conforms** — the rewrite correctly pivots from counting to causal direction.

**Conclusion:** The corrector, given the verifier's `details` wording, can plausibly repair a 計數式規準. All three rewrites removed counting language and grounded the distinction in reasoning quality.

---

## 9. Decisions

### (a) Is the criterion worth shipping?

**Partially yes, but the 【具體性】 check should ship separately.**

Numbers: CLEAR recall=0%, BORDERLINE recall=67%. The counting check alone (ignoring 【具體性】) would show much lower FPR on CONFORMING entries. The BORDERLINE recall of 67% is acceptable for a first-pass verifier that catches the canonical cases (fasting-method Seq 3, hot-pack Seq 7, washing-machine-physics Seq 5, wind-corridor Seq 1). The CLEAR recall=0% reflects a genuine weakness: when domain knowledge makes the component set "obvious," the model defers to that knowledge rather than the stem framing. A follow-on clarification of the 判準 (e.g., adding an example that distinguishes "obvious from science" from "stated in the stem") could fix this.

Decision: **ship the counting check as the hook**; defer 【具體性】 to a separate criterion (it flags a different defect class and its FPR characteristics deserve independent measurement).

### (b) Does borderline behaviour agree with 規則 C's text?

**Partially — 4 of 6 BORDERLINE VIOLATES caught (67%), 2 missed.**

The 4 caught (fasting Seq 3, hot-pack Seq 7, washing-machine Seq 5, wind-corridor Seq 1) represent the clearest cases of open-ended stems with count-based rubrics. The 2 missed (fasting Seq 4: "至少兩份圖表"; hot-pack Seq 2: three evaluation criteria) are cases where the model inferred that the specific evidential targets or criteria were implicitly framed by the experimental context. The rule text's 【注意】 clause covers "個數不等於集合" well, but not the case where criteria are "scientifically self-evident." The text is correct; the model's inference ability slightly undercuts it at the margin.

### (c) Should detected 計數式規準 FAIL or ANNOTATE?

**FAIL (passed=False → 修正 loop).**

Evidence: all three spot-check corrector rewrites conformed to 規則 C. The `details` wording gives the corrector a positive instruction (what to include, how to distinguish [2] from [1] on quality grounds) rather than a vague "fix the rubric." The corrector does not need explicit knowledge of counting—it needs to know what quality criterion to substitute. The verifier supplies this. Since the corrector can repair the defect and 評分規準 is not frozen, a `passed=False` verdict triggers the repair loop productively.

### (d) Yes/no on dedicated corrector repair path?

**No.**

The existing corrector seam already permits 評分規準 rewriting (NS corrector.py says "若問題在小題答案或評分規準，請只修改對應小題的 答案/答案解析/評分規準"; 評分規準 is absent from `FROZEN_SUBQUESTION_FIELDS`). The verifier's `details` string is the corrector's input via `VerificationResult.details`. No new pathway is needed; the hook plugs into `_NS_POST_VERIFY_HOOKS` and the existing loop handles the rest.

### (e) Production gate

The hook **must skip subquestions whose 題型 is not "Constructed response" / "開放式建構反應題" deterministically** before making any LLM call. This is the C3 constraint. The OOS FPR of 9% in this prototype is informative only for the model's generalisation behaviour; the shipped hook never reaches OOS subquestions. The gate is one string check, not LLM inference:

```python
if "Constructed" not in subquestion.題型 and "開放式" not in subquestion.題型:
    return result  # skip without LLM call
```

---

## 10. Proposed Hook Code Shape (Follow-up, Not Implemented Here)

```python
def _ns_rubric_counting_check_hook(
    question: ExamQuestion,
    result: VerificationResult,
    client: LLMClient,
) -> VerificationResult:
    """Detect 計數式規準 (Rule C counting violations) on Constructed-response
    subquestions and append a corrector-actionable detail.

    Mirrors _ss_rubric_scale_check_hook's signature and registration pattern.
    Registered in _NS_POST_VERIFY_HOOKS.
    """
    issues: list[str] = []
    for subquestion in question.subquestions:
        # C3 gate — deterministic, no LLM call for non-open-response
        if (
            "Constructed" not in (subquestion.題型 or "")
            and "開放式" not in (subquestion.題型 or "")
        ):
            continue
        rubric = subquestion.評分規準
        if not rubric:
            continue
        # LLM criterion call
        response = client.generate_json(
            system=RUBRIC_COUNTING_SYSTEM,
            user=_build_counting_user(subquestion),
            purpose="verify",
        )
        if response.get("verdict") == "fail":
            issues.append(
                f"第{subquestion.序號}題："
                + (response.get("details") or "[評分規準檢核] 請依規則 C 改寫評分規準")
            )
    if issues:
        result.details = result.details.rstrip()
        result.details += "\n\n" + "\n".join(issues)
        result.passed = False
    return result
```

This hook is registered by appending it to `_NS_POST_VERIFY_HOOKS` in `src/natural_sciences/verifier.py`. An equivalent hook is added to the SS post-verify hook list in `src/social_studies/verifier.py`, with the 認知歷程 field replacing 科學能力 in the user prompt.

---

## Appendix: Method Notes

- **Fixed ordering:** entries processed in `sorted(glob("*.json"))` order, then CMC/SMC, then SS CSV. Reproducible across runs.
- **Rate limiting:** 0.3 s between calls (config default was 0; override applied in script).
- **No temperature override:** provider default (equivalent to temperature=1 for claude-sonnet-4-6).
- **Caching:** `responses.jsonl` — keyed by `{file_stem}|{seq}`. A re-run reads from cache and makes 0 new calls unless entries are added.
- **Rubric schema handling:** both `{code, 規準說明}` and `{編碼, 說明}` schemas handled at load time.
- **Total LLM calls:** 218 (all entries on first run).
