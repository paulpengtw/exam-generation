# #861 — Measuring 【具體性】 on 規準說明 against independent labels (Claude Code approximation)

**Ticket:** [#861](https://github.com/paulpengtw/exam-generation/issues/861). **Parent:** [#860](https://github.com/paulpengtw/exam-generation/issues/860). **Spot-check:** [#882](https://github.com/paulpengtw/exam-generation/issues/882).
**Corpus:** `origin/staging@946fb32`. The few-shot corpus is unchanged since #651.
**Assets:** [`861-specificity-measurement/`](861-specificity-measurement/).

## Summary

After the owner's spot-check in [#882](https://github.com/paulpengtw/exam-generation/issues/882) (2026-10-03):

- **The checker never fails a specific rubric.** It failed 0 of the 103 rubrics the owner's verdicts call specific, and 0 of the 70 multiple-choice rubrics.
- **It misses about half of the vague rubrics.** It caught 43 of 84.
  - It catches all 27 「完整正確回答／部分正確／錯誤」 template rubrics.
  - It misses two shapes the owner ruled vague: a [2] that restates the task with 「正確」, and a [1] whose only gap is 「說明不完整／未說明原因」, even when [1] names the item's choice.
- **#651's open question is answered: the clause does its job.** Every flag here is correct, so #651's 41 flags on conforming rubrics were the clause catching real vagueness, not over-firing.
- **Recommendation:** ship the 規準說明 half as a **fail** criterion, with the criterion text amended to spell out the two missed shapes. Re-measure that text on the real harness before #860 decides (see Recommendation and Limits).

## Method

The owner chose this method on 2026-10-02: a **Claude Code approximation, without an API key**.

| Role | Model | Prompt |
|---|---|---|
| **Labeller** | `claude-opus-5-5` (the Claude Code main session) | [`labelling_rule.md`](861-specificity-measurement/labelling_rule.md), posted on #861 before any labelling. It never saw a checker verdict. |
| **Checker** | `claude-sonnet-4-6` (6 Claude Code subagents, about 43 items each, in shuffled order) | The #651 harness's `VERIFIER_SYSTEM` and `VERIFIER_USER_TEMPLATE`, verbatim, except one change below. Inputs were truncated as in the harness (stem 600, rubric 600 characters). |

**The one change to the checker prompt.** The `specificity_violation` field description now carries the 規準說明 half of 【具體性】 as worded in #653:

> 評分規準說明未指名本小題的內容——[2] 未寫出本題該答對什麼，或 [1] 未寫出本題最可能出現的缺口；或使用「完整正確回答／部分正確／錯誤」這類可套用到任何題目的字樣

The system prompt's 【具體性】 clause already had this wording, minus the #653 "two gaps" amendment. That amendment is **out of scope**: no existing rubric was written to it, so measuring it would flag every rubric and tell us nothing.

**Scope.**
- **In scope:** 187 open-response rubrics (185 自然科學 + 2 社會領域), bucketed by each 小題's own `題型` and labelled *specific* or *vague*.
- **Out of scope:** the 70 multiple-choice rubrics. The rule doesn't apply to them, so their expected verdict is pass.
- **What is measured:** the `specificity_violation` field only. `verdict` also folds in counting.

**A rule clarification made during labelling.** The posted rule did not cover a top level that only restates the task with 「正確」, such as 「正確畫記流動方向」「五點全部正確依深度排列」「表格全部答對」. The labeller treated those as **generic**: they don't say what the answer is. Of the 23 disagreements, 12 turn on this clarification, so it is the first question in the spot-check.

## Pass-1 confusion matrices, before the spot-check (positive = vague, i.e. the checker should fail)

**Under the labeller's labels:**

| Bucket | n | TP | FP | FN | TN | Recall | False-fail rate |
|---|---|---|---|---|---|---|---|
| CLEAR | 17 | 1 | 1 | 3 | 12 | 25% | 8% |
| BORDERLINE | 21 | 3 | 3 | 2 | 13 | 60% | 19% |
| CONFORMING | 149 | 33 | 2 | 12 | 102 | 73% | 2% |
| OUT_OF_SCOPE_C3 | 70 | 0 | 0 | 0 | 70 | — | 0% |

**With every disagreement flipped to the checker's side.** This is the other end of the range your spot-check can move the numbers within:

| Bucket | n | TP | FP | FN | TN | Recall | False-fail rate |
|---|---|---|---|---|---|---|---|
| CLEAR | 17 | 2 | 0 | 0 | 15 | 100% | 0% |
| BORDERLINE | 21 | 6 | 0 | 0 | 15 | 100% | 0% |
| CONFORMING | 149 | 35 | 0 | 0 | 114 | 100% | 0% |
| OUT_OF_SCOPE_C3 | 70 | 0 | 0 | 0 | 70 | — | 0% |

The buckets are #648's counting-audit buckets. They are kept separate as the ticket requires, but they say little about vagueness, so read them as strata, not as a difficulty scale.

## The disagreement list

There are 23 disagreements, and the labeller had marked 20 of them borderline. They fall into four groups, and each group is decided by one question about the rule. Per-entry verdicts go on #882.

**A. The [2] level restates the task without the answer.** The labeller says vague; the checker passes it. (12 entries)
- seawater-vertical-properties|0|2
- sea-ice-land-ice|0|3
- 大氣能見度|0|2
- 早餐論證A線上版|0|3
- 早餐論證A線上版|0|4
- 烏賊線上版|0|4
- 生物防治2-1|0|4
- 生物防治2-1|0|6
- 生長素與向光性|0|3
- 運動與健康-糖尿病患者的健康生活|0|3
- 隕石探究|0|6
- 颱風資料庫|0|5

**B. The [2] level is specific, but the [1] level is generic.** The labeller says vague; the checker passes it. (5 entries)
- crazy-track|0|7
- hot-pack|0|1
- hot-pack|0|3
- 氣候變遷|0|5
- 社會領域_row4|0|4

**C. The [1] level leans on [2], or has one generic alternative.** The labeller says specific; the checker fails it. (4 entries)
- entomopathogenic-fungi|0|5: its [1] includes 「說明部分正確」.
- typhoon-database|0|4
- washing-machine-physics|0|5
- 氣候變遷|0|4

**D. The [2] level names a concept or choice, not the content.** The labeller says specific; the checker fails it. (2 entries)
- 胡椒蛾的分子機制|0|3
- 隕石探究|0|3

Group D sits awkwardly with the labeller's own group A clarification: 「實驗假設正確」 also restates the task. Expect the labeller to be wrong here.

## The owner's spot-check (#882, 2026-10-03)

| Group | Owner's verdict | Entries |
|---|---|---|
| A: [2] restates the task | **Labeller right on 11** (vague). **Checker right on 早餐論證A線上版 Q4**: naming the item's reasoning-chain steps (B→省略早餐, C→變胖) is specific. | 12 |
| B: specific [2], generic [1] | **Labeller right:** [1] must name an item-specific gap on its own. | 5 |
| C: [1] leans on [2] or has a generic alternative | **Checker right on all 4:** a template phrase in any alternative fails; judging criteria without the judgment, and a general principle, are generic. | 4 |
| D: [2] names a concept or choice, not the content | **Checker right on both.** | 2 |

**The follow-up ruling went beyond the 23.** A [1] that names this item's choice but only a generic gap (「選小宗但說明不完整」) is vague. Version 1's "borrowing" allowance was therefore a labeller error. Under it, the labeller had passed **25 rubrics on which it agreed with the checker**, and they are now relabelled vague. A generic tail next to a named gap (「…，或說明不完整」) is fine.

The labelling rule is amended to [version 2](861-specificity-measurement/labelling_rule.md), with a change log. #862 must reuse version 2. Per-entry verdicts are in [`owner_verdicts.json`](861-specificity-measurement/owner_verdicts.json), and `final_label` in `labelled_set.json` carries them.

### Final matrix (owner's verdicts; positive = vague)

| Bucket | n | TP | FP | FN | TN | Recall | False-fail rate |
|---|---|---|---|---|---|---|---|
| CLEAR | 17 | 2 | 0 | 3 | 12 | 40% | 0% |
| BORDERLINE | 21 | 6 | 0 | 1 | 14 | 86% | 0% |
| CONFORMING | 149 | 35 | 0 | 37 | 77 | 49% | 0% |
| OUT_OF_SCOPE_C3 | 70 | 0 | 0 | 0 | 70 | — | 0% |
| **In scope (187)** | 187 | 43 | 0 | 41 | 103 | 51% | 0% |

Each of the 41 misses is one of the two shapes: 11 restated tasks (Group A), and 30 generic-gap [1] levels (5 in Group B + 25 relabelled).

## Observations

- **Specificity and counting share one `details` line.** The checker judges 【禁止】 and 【具體性】 in one prompt, so the reasons blur. washing-machine-physics Q5's specificity flag is explained by counting. 氣候變遷 Q5 got a counting fail, so its `details` is the corrector's only instruction, and it says nothing about the generic [1]. If the 規準說明 half ships, give it its own criterion or `details` line, so the corrector gets one instruction at a time.
- **The checker's `details` sentences are usable corrector instructions.** They name the item's content and propose replacement wording, for example 胡椒蛾的分子機制|0|3, which lists the H-W conditions.

## Recommendation

**Ship the 規準說明 half as a fail criterion. Amend its text first, then re-measure that text on the real harness.**

- **Why fail is safe:** the checker produced no false fails under the owner's verdicts, in scope or out.
- **Why the text needs amending:** the misses are systematic. Both missed shapes are absent from the criterion text, and Sonnet 4.6 doesn't infer them. The proposed lines to add to the 【具體性】 clause:

> - [2] 若只寫「正確作答／正確排列／正確畫出／判斷正確」等重述題目要求的字樣，而未寫出本題答案的內容（應選的答案、應得的關係或結論、須引用的數據），視為違反。若 [2] 已寫出本題推理鏈的各個步驟，則不在此限。
> - [1] 必須寫出本題特有的缺口。「說明不完整」「未說明原因」「理由不充分」「論述不完整」等字樣，即使前面寫出本題的選項或主張，也不算寫出缺口；只要有一個選項寫出具體缺口即可。

The `details` sentence the corrector would receive:

> 「[評分規準檢核] 規準說明未指名本小題內容：[2] 請寫出本題該答對的具體內容（應選的答案、應得的關係或結論、須引用的數據），不要只寫「正確作答」；[1] 請寫出本題最可能出現的缺口（缺了哪個要素、哪個推理環節或哪項證據），「說明不完整」「未說明原因」不算缺口；不得使用「完整正確回答／部分正確／錯誤」這類可套用到任何題目的字樣。」

**Interim fallback.** If the amended text can't be measured soon, ship the current text as fail anyway. It catches the template defect with no false fails, and the misses pass, which is no worse than today.

## Limits

- **This is an approximation.** The checker ran as Claude Code subagents, which wrap the harness prompts in Claude Code's own system prompt and run several items per context, not as `LLMClient` calls at the harness's effort setting. **Re-run on the real harness with an API key before #860 decides.** The labels and the labelling rule carry over unchanged.
- **One labeller, one human pass.** The labels come from one LLM pass, corrected by the owner's verdicts on the 23 disagreements. Rubrics where the labeller and checker agreed were not human-checked. The 25 relabelled under the owner's follow-up ruling were relabelled by the labeller, not by the owner, and are listed in `owner_verdicts.json` so the owner can contest any of them. Shared blind spots would not show up in these matrices.
