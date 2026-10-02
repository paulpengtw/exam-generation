# #861 — Measuring 【具體性】 on 規準說明 against independent labels (Claude Code approximation)

**Ticket:** [#861](https://github.com/paulpengtw/exam-generation/issues/861). **Parent:** [#860](https://github.com/paulpengtw/exam-generation/issues/860). **Spot-check:** [#882](https://github.com/paulpengtw/exam-generation/issues/882).
**Corpus:** `origin/staging@946fb32`. The few-shot corpus is unchanged since #651.
**Assets:** [`861-specificity-measurement/`](861-specificity-measurement/).

## Summary

- **The checker reliably catches template rubrics.** All 27 「完整正確回答／部分正確／錯誤」 rubrics were flagged.
- **It rarely fails a specific rubric.** It failed 6 of the 133 rubrics the labeller called specific (4.5%) and none of the 70 multiple-choice rubrics.
- **It misses about a third of vague rubrics.** It passed 17 of the 54 the labeller called vague. Almost all 17 restate the task (「正確排列」「表格全部答對」) or have a generic [1] under a specific [2].
- **#651's open question is answered: mostly the clause doing its job.** #651 flagged 41 of 149 conforming rubrics and could not tell whether that was over-firing. Here the checker flagged 35 of the 149, and the labeller agrees on 33 of them.
- **Recommendation (provisional): ship the 規準說明 half as a fail criterion.** This still depends on your spot-check in #882 and on one re-run with the real harness (see Limits).

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

## Confusion matrices (positive = vague, i.e. the checker should fail)

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

## Observations

- **The specificity flag picks up counting.** Two of the checker's false fails (washing-machine-physics|0|5 and 氣候變遷|0|5) cite *counting* in `details`. They were flagged because the checker judges 【禁止】 and 【具體性】 in one prompt. If the 規準說明 half ships, give it its own criterion or `details` line, so the corrector gets one instruction at a time.
- **The checker's `details` sentences are usable corrector instructions.** They name the item's content and propose replacement wording, for example 胡椒蛾的分子機制|0|3, which lists the H-W conditions.

## Recommendation

**Ship the 規準說明 half as a fail criterion. This is provisional.**

- **Why fail is safe:** the false-fail cost is low. In scope, the worst case at the labeller's end of the range is 6 of 133 (4.5%), and multiple-choice is 0 of 70.
- **Why fail is worth it:** the generic template is the defect the corpus teaches, and the checker catches all of it. A note alone would let template rubrics keep shipping.
- **What a fail gets wrong:** the misses (group A) pass, which is no worse than today.

The `details` sentence the corrector would receive:

> 「[評分規準檢核] 規準說明未指名本小題的內容：[2] 請寫出本題該答對的具體內容（應選的答案、須引用的數據或須說明的機制），[1] 請寫出本題最可能出現的缺口；不得使用「完整正確回答／部分正確／錯誤」或「正確作答」這類可套用到任何題目的字樣。」

## Limits

- **This is an approximation.** The checker ran as Claude Code subagents, which wrap the harness prompts in Claude Code's own system prompt and run several items per context, not as `LLMClient` calls at the harness's effort setting. **Re-run on the real harness with an API key before #860 decides.** The labels and the labelling rule carry over unchanged.
- **One labeller, one pass.** The labels come from one LLM pass with no human ground truth. Your #882 verdicts are the only human ground truth these matrices get.
