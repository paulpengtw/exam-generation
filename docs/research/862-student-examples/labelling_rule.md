# Labelling rule: 學生作答實例 judgement rules (#862)

**Version 2, amended 2026-10-03 after the owner's spot-check (verdicts on [#879](https://github.com/paulpengtw/exam-generation/issues/879)).** Version 1 was posted on #862 before labelling and is in this file's git history. Every change is listed under "Changes from version 1" at the end. Later slices that reuse this procedure (#863, #884) must reuse **this** version.

This rule is for the **independent labeller** only. It produces the reference labels that the checker's per-example flags are compared against. It is written separately from the checker's prompt, and the labeller never sees the checker's verdicts. It reuses the procedure of [#861's labelling rule, version 2](../861-specificity-measurement/labelling_rule.md): one written rule, a short quoted reason per label, borderline marks, and every disagreement listed for the owner.

The three rules come from the 【具體性】 and 【學生作答實例】 clauses that [#653](https://github.com/paulpengtw/exam-generation/issues/653) approved. The fourth, 最小對照, is #863 and is not labelled here. The fixed 1 / 2 / 1 counts are a deterministic hook and are not labelled either.

## What is labelled

- **The unit is one example**: one string in one level's `學生作答實例` list. Its id is `<file>|<item>|<序號>|<code>|<index>`.
- **Scope is set by the 小題's own `題型`** (`開放式建構反應題` or `Constructed response`, or `小題題型` for the 社會領域 CSV), never by its folder. Examples on multiple-choice 小題 are not labelled (C3).
- **Each rule is labelled on its own.** An example can break one, two or all three rules. A label for one rule never looks at the others.
- **The 規準說明 is context, not the object.** Whether the level's description is vague is #861's question. Whether the example sits at the right level is not judged here, except where rule 3 says so.

## Rule 1: 擬答 (student voice)

**Label: `answer` or `narration`.** Applies to every example at every level.

- **`answer`**: text a student could literally have written on the answer sheet for this 小題. It may be short, fragmentary, wrong, or badly reasoned.
- **`narration`**: anything else. Three shapes:
  - **It describes an answer** instead of being one: third-person or meta wording such as 「學生回答…」「能說明…」「有提到…」「只提改變間距的實驗」「答出兩點」.
  - **It comments on the answer**: a remark about this answer's own quality or completeness, inside it or as a trailing note: 「未說明原因」「只寫一點」「部分正確」「（理由不完整）」「完整正確」.
  - **It is a placeholder** standing in for an answer: 「完整正確回答」「例如：」「（空白）」「同上」.
- **Grading words are not comments when the student uses them about the item.** A student judging a claim, a 推論 or a design in the 文本 writes 「推論一正確，因為…」「這個說法不合理」「他的實驗沒有對照組」. That is the answer, not a comment on it. **The test is what the word is about:** this answer (narration) or something in the item (answer).
- **Drawing, labelling and graphing 小題 are exempt from the student-voice part.** There the example is a description of what was drawn, and a **neutral** description is labelled `answer` (「畫折線圖，X軸為光照時間、Y軸為彎曲角度，折線逐漸上升」). A description that grades the drawing (「圖形正確但標題錯誤」) is `narration`.
- **First-person framing is not required.** A bare claim (「溫度越高，反應越快」) is an answer.

## Rule 2: answers this 小題

**Label: `this_item` or `generic`.** Applies to every example at every level.

- **The test is #861's paste test.** Take an open-response 小題 on an unrelated topic. If the example could be pasted there unchanged, it is **`generic`**.
- **`this_item`**: it uses at least one of this 小題's or its 文本's **data, variables or names**: a datum or value, a variable, a named thing or person, or an option it offers. **And** it answers the question this 小題's stem asks.
- **`generic`**: placeholders (「例如：」「完整正確回答」「（空白）」), 「不知道」, and content that fits any item (「數據沒有意義」「因為很重要」「我覺得都對」). Also:
  - **The item's concept or topic alone is not enough.** 「只採可直接觀察的事實，排除推測與情緒性陳述」 names 客觀科學論述 but none of the item's 貨車, 民眾 or 行車紀錄器, so it is `generic`.
  - **Grading a drawing in words that fit any graph** (「圖形形狀正確但未標明縱軸單位或刻度數值」) is `generic` as well as `narration`.
  - **Same 文本, different question.** An example that uses the 題組's data but answers a different question than this 小題's stem is `generic` (「答非本小題所問」).
- **Correctness is not judged.** A wrong answer that uses this item's data, variables or names, and is aimed at this 小題's question, is `this_item`.

## Rule 3: plausible [0]

**Label: `plausible` or `filler`.** Applies only to examples at level `0`. Examples at any other level get `n/a`.

- **`plausible`**: a wrong answer that a student who engaged with this 小題 could really write, showing a misconception or a wrong direction about this item's content. Examples: a reversed relationship, a wrong choice with a mistaken reason, everyday intuition used instead of the data, reading correlation as cause.
- **`filler`**:
  - a blank, 「不知道」「不會」, or a refusal;
  - an answer unrelated to the item, an absurd answer, or a joke (「停車場看起來很好玩」);
  - a placeholder, or a description that names no misconception (「答案錯誤」「方向錯誤」「未作答」);
  - an example that **is not wrong**: it would earn [1] or [2] under this rubric. Mark this one borderline.
- **"Most likely" is not ranked.** The labeller cannot know which misconception is commonest, so any plausible, item-tied misconception passes. An example is `filler` only when no real student who tried the item would write it.
- **Voice is rule 1's job.** A narrated but plausible misconception (「說高度越高越穩定」) is `plausible` here. It fails rule 1 instead.

## The trap set

The labeller also writes **at least 15 trap examples**: genuine student-voice answers to 小題 that ask the student to **judge** something, so they contain grading words (`typhoon-database` 序號 4 is the model). Each trap sits under the real 小題 and its real 規準說明, in a separate checker call, so traps never mix with the real examples. By construction a trap is `answer` and `this_item`, and `plausible` if it sits at [0]. They are still labelled with this rule like any other example. A checker flag on a trap is a false positive that would block a good generation, so trap false positives are reported on a line of their own.

## Output per example

`{id, rule1, rule2, rule3, borderline: [rules], reason: {rule: quoted deciding phrase}}`

## Changes from version 1

| # | Change | Source |
|---|---|---|
| 1 | Rule 2: **the item's concept or topic alone no longer counts**. An example must use the item's data, variables or names, which is the block's own wording (「資料、變因或名稱」). | Owner, disagreements #2 and #3 (`truck-cornering\|0\|3` [2] and [1]): checker right. These were labeller errors. |
| 2 | Rule 2: **an example must answer this 小題's question.** Same 文本, different question is `generic`. Version 1 passed it as borderline. | Owner, `社會領域_row4\|0\|4` [2], which was off the list: the labeller and the checker had both passed it. |
| 3 | Rule 2: a graph-grading phrase that fits any graphing item is `generic` as well as `narration`. | Owner, disagreement #4: labeller right. Spelled out, not changed. |
| — | **Kept as in version 1:** 「選B，說明…」 is narration (#1); a [0] example that is not wrong is `filler` (#6); an answer close to a joke is `filler` (#7); an answer with no datum or name from the 文本 is `generic` (#5). | Owner: labeller right on #1, #4, #5, #6 and #7. |
