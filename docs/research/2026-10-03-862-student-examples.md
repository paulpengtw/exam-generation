# #862: Measuring the 學生作答實例 rules on real examples (Claude Code approximation)

**Ticket:** [#862](https://github.com/paulpengtw/exam-generation/issues/862). **Parent:** [#860](https://github.com/paulpengtw/exam-generation/issues/860). **Spot-check:** [#879](https://github.com/paulpengtw/exam-generation/issues/879).
**Corpus:** `origin/staging@946fb32`, unchanged since #861.
**Assets:** [`862-student-examples/`](862-student-examples/). The script is [`scripts/research/rubric_862_examples.py`](../../scripts/research/rubric_862_examples.py).

## Summary

Three of the four judgment rules that [#653](https://github.com/paulpengtw/exam-generation/issues/653) set for 學生作答實例 were measured, one matrix per rule. Positive means a violation, so the checker should flag it.

| Rule | In-scope recall | In-scope false flags | Trap false flags | Recommendation |
|---|---|---|---|---|
| **擬答** (student voice) | 17 / 18 (94%) | 0 / 45 | **0 / 18** | **fail** |
| **Answers this 小題** | 3 / 5 (60%) | 2 / 58 | **0 / 18** | **note only** |
| **Plausible [0]** | 5 / 7 (71%) | 0 / 18 | **0 / 6** | **fail** |

- **The trap set never tripped the checker.** It saw 18 genuine answers to judging 小題 full of grading words (「推論二錯誤」「證據不足」「這樣驗證不正確」「說明是正確的」) and flagged none. The ban on comments about the answer is not working as a word list. This was the risk #653 named.
- **Six of the seven disagreements fall on entries the labeller had marked borderline.** The numbers therefore move inside a narrow range (below), and the spot-check decides where they land.
- **The numbers are provisional.** The checker ran as Claude Code subagents, so the result needs a real-harness re-run before #860 wires anything, as #981 is doing for #861.

## Method

The owner chose this method on 2026-10-03: a **Claude Code approximation, without an API key**, the same method as #861.

| Role | Model | Prompt |
|---|---|---|
| **Labeller** | `claude-opus-5-5` (the main Claude Code session) | [`labelling_rule.md`](862-student-examples/labelling_rule.md), posted on #862 before any labelling. It reuses #861's procedure (version 2) and never saw a checker verdict. |
| **Checker** | `claude-sonnet-4-6` (3 Claude Code subagents, 8–9 units each, shuffled; no batch held a trap next to its real 小題) | #861's prompts ([`checker_system.txt`](862-student-examples/checker_system.txt), [`checker_user_template.txt`](862-student-examples/checker_user_template.txt)), extended as described below. |

**The extension to the criterion.**
- **System prompt.** A 【學生作答實例】 clause carries the three rules in #653's approved wording, plus one sentence from #653's resolution: a comment means a remark about this answer itself, while a student judging the item's claims is answering. Counts and 最小對照 are declared out of scope.
- **User prompt.** The examples are listed by number, each with its level. They are never truncated; the stem and the rubric are truncated as in the harness.
- **Output.** Each example gets three flags: `not_student_voice`, `not_this_item`, and `implausible_zero` (null except at [0]). Example findings get their own `example_details` line, separate from the rubric's `details`. #861 found that one shared line blurs two instructions for the corrector.

**Data.**
- **Real examples: 63.** They come from the 17 自然科學 Constructed-response rubrics that carry any example (57), plus the 2 社會領域 `範例_` rows (6), both `開放式建構反應題` by `小題題型`.
  - The prototype's 社會領域 loader reads the CSV's 題組-level `題型` (「選擇題」). The new script reads `小題題型` instead.
  - The 74 examples on 15 multiple-choice rubrics are out of scope by C3. The deterministic gate drops them before any criterion runs.
- **Trap set: 18.** These are student-voice answers written by the labeller for 6 judging 小題, under each 小題's real 規準說明, in separate checker calls ([`trap_set.json`](862-student-examples/trap_set.json)).
- **Cache.** The cache is keyed on the unit and a hash of the prompt, so changing the criterion text invalidates it (the #651 cache did not).

## Matrices (labeller's labels; positive = violation)

### 擬答 (student voice)

| Stratum | n | TP | FP | FN | TN | Recall | False-flag rate |
|---|---|---|---|---|---|---|---|
| 自然科學 | 57 | 17 | 0 | 1 | 39 | 94% | 0% |
| 社會領域 | 6 | 0 | 0 | 0 | 6 | — | 0% |
| **In scope** | 63 | 17 | 0 | 1 | 45 | 94% | 0% |
| **Trap set** | 18 | 0 | 0 | 0 | 18 | — | **0%** |

### Answers this 小題

| Stratum | n | TP | FP | FN | TN | Recall | False-flag rate |
|---|---|---|---|---|---|---|---|
| 自然科學 | 57 | 3 | 2 | 1 | 51 | 75% | 4% |
| 社會領域 | 6 | 0 | 0 | 1 | 5 | 0% | 0% |
| **In scope** | 63 | 3 | 2 | 2 | 56 | 60% | 3% |
| **Trap set** | 18 | 0 | 0 | 0 | 18 | — | **0%** |

### Plausible [0] (level-0 examples only)

| Stratum | n | TP | FP | FN | TN | Recall | False-flag rate |
|---|---|---|---|---|---|---|---|
| 自然科學 | 23 | 3 | 0 | 2 | 18 | 60% | 0% |
| 社會領域 | 2 | 2 | 0 | 0 | 0 | 100% | — |
| **In scope** | 25 | 5 | 0 | 2 | 18 | 71% | 0% |
| **Trap set** | 6 | 0 | 0 | 0 | 6 | — | **0%** |

**The range the spot-check can move.** If every disagreement is flipped to the checker's side, all three rules reach 100% recall with 0 false flags. With the labeller's labels they stand as above.

## The disagreement list

Each example is quoted verbatim. "B" means the labeller marked it borderline. Machine-readable copy: [`disagreements.json`](862-student-examples/disagreements.json).

| # | Rule | Example | Labeller | Checker | The question it turns on |
|---|---|---|---|---|---|
| 1 | 擬答 | `fasting-method\|0\|4` [2]: 「選B，說明斷食縮短胰島素分泌時間，圖三也顯示同熱量下縮短進食窗口效果更好」 | narration (B) | pass | Is 「選B，說明…」 a student's answer, or a description of one? |
| 2 | 本小題 | `truck-cornering\|0\|3` [2]: 「只採可直接觀察的事實，排除推測與情緒性陳述」 | this item (B) | flag | Does the item's **concept** (客觀科學論述) count, or must the example use the item's **data, variables or names** (貨車, 民眾)? The block's wording is 「資料、變因或名稱」, which is closer to the checker. |
| 3 | 本小題 | `truck-cornering\|0\|3` [1]: 「採事實性陳述，不採推測性陳述，但未說明如何判斷」 | this item (B) | flag | Same as #2. |
| 4 | 本小題 | `weather-proverbs\|0\|4` [1]: 「圖形形狀正確但未標明縱軸單位或刻度數值」 | generic | pass | The checker flagged it under 擬答 (both agree on that) but not here. Does a graph-grading phrase that fits any graphing item also fail 本小題? |
| 5 | 本小題 | `社會領域_row4\|0\|4` [1]: 「我覺得先討論比較好，因為有人反對。」 | generic (B) | pass | Does 「先討論」 tie to this 文本's 公聽會, or would it fit any civic-issue item? |
| 6 | Plausible [0] | `jumping-bottle-cap\|0\|3` [0]: 「1.表(二) ；因為計錄比較詳細」 | filler (B) | pass | It picks the same table as the [2] example, so it is not wrong. Should rule 3 catch a [0] example that is not a wrong answer at all? |
| 7 | Plausible [0] | `truck-cornering\|0\|3` [0]: 「只採認識的民眾意見」 | filler (B) | pass | Is trusting people you know a misconception a real student would write, or a joke? |

One more case did not reach the list, because the labeller and the checker agreed on it. `社會領域_row4|0|4` [2] 「我支持先重新評估，因為基地十年淹水三次…」 uses this 文本's data, but it answers a different question (a stance on building, where the stem asks about the citizen's role). Both passed it under 本小題. **Should 本小題 also catch an answer to a different question in the same 題組?** The labelling rule marked it borderline so this question reaches the owner.

## Recommendation

**擬答: fail.** The checker caught 17 of 18 with no false flag, and passed all 18 traps. That includes the hardest shape, a trailing coder note (「（無說明）」「（未說明哪個變因受控制）」), and narration by 「說…」 on [0] examples. The checker's `details` sentences are usable as written. Proposed wording for the corrector:

> [學生作答實例檢核] [<級距>] 的實例 <n> 含對作答的評語「<評語>」（或為轉述、佔位字樣）；請刪去評語，改寫成學生口吻的作答原文。繪圖、標示題改為中性描述學生畫了什麼。

**Answers this 小題: note only.** It is the weakest of the three, and it adds little on its own:
- Every true positive was also caught by 擬答 or plausible [0]: 「例如:」 twice, and 「數據沒有意義」.
- Both false flags come from the checker reading 「本小題」 as the scenario's nouns, which is disagreements #2 and #3.

As a fail criterion it would cost corrector retries on good examples, for almost no added catch. Revisit it if the spot-check rules the concept out (#2 and #3 then become true positives) and the real-harness run holds.

**Plausible [0]: fail.** It caught 5 of 7 with no false flag on 18 real negatives and 6 traps; both misses are borderline. The base is small (25 level-0 examples), so the real-harness re-run should add generated [0] examples before this is final. Proposed wording for the corrector:

> [學生作答實例檢核] [0] 的實例 <n> 不是學生合理會寫的錯誤答案（<理由：空白、不知道、與題目無關或荒謬>）；請改寫成本小題最可能引出的錯誤觀念，例如 <本題的典型迷思>。

**Wiring note for #860.** Keep example findings on their own `details` line, separate from the 【具體性】 and counting line. In this run 5 units failed on their rubric text and also had example flags: `fasting-method|0|3`, `jumping-bottle-cap|0|3`, `typhoon-database|0|4`, `wind-corridor-effect|0|1` and `社會領域_row4|0|4`. In each of them the two lines carried different instructions.

## Limits

- **Approximation.** The checker ran as Claude Code subagents with Claude Code's own wrapper, so the matrices must be re-confirmed on the real harness (a follow-up slice, like #981).
- **Small positives.** 本小題 has 5 in-scope positives and plausible [0] has 7. A single flip moves recall by 14–20 points.
- **The labeller wrote the traps.** By construction they are clean answers. They measure false flags only, not recall.
- **Not measured here:** 最小對照 (#863), the fixed 1 / 2 / 1 counts (a deterministic hook), the 額外項目 rules (#874), and 常見錯誤 agreement with [0] (#884).
