# Labelling rule: 規準說明 vagueness (#861)

**Version 2, amended 2026-10-03 after the owner's spot-check in #882.** Version 1 was posted on #861 before labelling and is in this file's git history. Every change is listed under "Changes from version 1" at the end. #862 (the 學生作答實例 slice) must reuse **this** version.

This rule is for the **independent labeller** only. It produces the reference labels that the 【具體性】 checker's verdicts are compared against. It was written separately from the checker's prompt, and the labeller never sees the checker's verdicts.

## What is labelled

- **One label per open-response 小題** (`題型` is 開放式建構反應題 or Constructed response, taken from the 小題 itself, never from its folder): **specific** or **vague**.
- **Only the 規準說明 text is judged.** These are judged elsewhere:
  - 學生作答實例 is #862.
  - Counting is #651.
  - The #653 amendment that [1] must name *two* gaps is out of scope here.
- **Multiple-choice 小題 are not labelled.** The rule does not apply to them, so a checker should always pass them.

## Levels

- **Top level**: the highest code, which is [2], or [1] on a 0/1 scale.
- **Partial level**: any code between the top level and [0]. A 0/1 scale has none.
- **[0] is not judged.** A generic [0] such as 「其他」 or 「錯誤或空白」 does not make a rubric vague on its own.

## The test: could this level be pasted onto another 小題?

Take a different open-response 小題 on an unrelated topic. If a level's description would fit it unchanged, that level is **generic**.

**The top level is specific** when it names what a correct answer to *this* 小題 contains: the expected choice or value, the expected relationship or conclusion, a data point or named thing from this item, or the particular reasoning link. It is generic when:
- it uses process words only (「完整正確回答」「完整合理說明」「正確推論並有證據支持」);
- it **restates the task with 「正確」** and never says what the answer is (「五點全部正確依深度排列」「表格全部答對」「X軸與Y軸標題正確，折線趨勢正確」「能說明兩數值與入射角度關係」);
- it **names a theory or set by reference without its members** (「符合Hardy-Weinberg條件違反的原因」), or a **general principle instead of this item's answer** (「相關不能推論因果關係」);
- it **names one part of a multi-part answer and leaves the part that needs reasoning as 「正確」** (「選擇不同形狀、實驗假設正確」);
- it names judging criteria that would fit any item of the same kind, but **not the expected judgment** (「能對三項推論提出具體判斷，並說明判斷標準（直接對應、有無替代解釋、是否過度外推）」).

**Exception:** a top level that names the **steps of this item's reasoning chain** is specific, even when the content of each step is left open (「分別說明B（導致省略早餐）和C（導致變胖）兩條推論路徑」).

**A partial level is specific** when it names at least one way an answer to *this* 小題 falls short, in this item's terms. It must do so **on its own**: a specific top level does not rescue a generic partial level.
- **A named gap is specific:** a missing element, a missing or wrong link, missing evidence (「未引用表中資料」「只引用一項數據」), or a concrete defect tied to this item's content.
- **A generic gap is generic, even next to this item's choice or claim:** 「說明不完整」「未說明原因」「理由不充分」「論述不完整」「僅說明現象而未解釋原理」. So 「選小宗但說明不完整」 and 「正確選(C)但未能合理說明原因」 are generic.
- **Graph-mechanical defects are generic:** 「標示不完整」「缺圖例或軸標題」「數據有小誤差」.
- **Pointing at a framed set is specific:** a reference to members the top level names (「僅提及兩個條件之一」「正確評估其中一人的論述」) names the gap, which is the missing member.
- **Alternatives (「…；或…」):** one specific alternative is enough. A generic tail such as 「或說明不完整」 does not spoil it, **unless** an alternative is a template phrase (「部分正確」「說明部分正確」「僅部分正確」). A template phrase makes the level generic. The words 部分正確 inside a specific description (「提出部分正確建議，但僅基於單次表現」) do not count.

## The label

- **vague**: the top level is generic, **or** a partial level exists and is generic under the rules above.
- **specific**: otherwise.

For every label, record a short reason that quotes the deciding phrase. Mark an entry **borderline** when the call could reasonably go the other way.

## Changes from version 1

| # | Change | Source |
|---|---|---|
| 1 | A top level that restates the task with 「正確」 is generic. **Exception:** naming the item's reasoning-chain steps is specific. | Clarification made during labelling. The owner confirmed it on 11 of the 12 Group A rubrics and made the exception on 早餐論證A線上版 Q4. |
| 2 | A partial level must name an item-specific gap on its own; a specific top level does not rescue it. | Owner, Group B: labeller right. |
| 3 | **Borrowing is removed.** A partial level naming this item's choice or claim plus a generic gap is generic. | Owner, follow-up ruling. This was a labeller error in version 1. 25 agreed rubrics were relabelled vague. |
| 4 | A template phrase in any alternative makes a partial level generic. | Owner, Group C (entomopathogenic-fungi Q5): checker right. |
| 5 | Naming a theory or set by reference, a general principle, judging criteria without the judgment, or one part of the answer with the reasoning part left as 「正確」, is generic. | Owner, Groups C and D: checker right on typhoon-database Q4, 氣候變遷 Q4, 胡椒蛾的分子機制 Q3 and 隕石探究 Q3. These were labeller errors. |
| 6 | One specific alternative is enough even with a non-template generic tail. | Owner, follow-up ruling. Version 1 is kept on this point. |
