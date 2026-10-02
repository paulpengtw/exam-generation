# Labelling rule: 規準說明 vagueness (#861)

This rule is for the **independent labeller** only. It produces the reference labels that the 【具體性】 checker's verdicts are compared against. It was written separately from the checker's prompt, and the labeller never sees the checker's verdicts.

## What is labelled

- **One label per open-response 小題** (`題型` is 開放式建構反應題 or Constructed response, taken from the 小題 itself, never from its folder): **specific** or **vague**.
- **Only the 規準說明 text is judged.** These are judged elsewhere:
  - 學生作答實例 is #862.
  - Counting is #651.
  - The #653 amendment that [1] must name *two* gaps is out of scope here, because no existing rubric was written to it.
- **Multiple-choice 小題 are not labelled.** The rule does not apply to them, so a checker should always pass them.

## Levels

- **Top level**: the highest code, which is [2], or [1] on a 0/1 scale.
- **Partial level**: any code between the top level and [0]. A 0/1 scale has none.
- **[0] is not judged.** The 【具體性】 clause only puts positive requirements on [2] and [1]. A generic [0] such as 「其他」 or 「錯誤或空白」 does not make a rubric vague on its own.

## The test: could this level be pasted onto another 小題?

Take a different open-response 小題 on an unrelated topic. If a level's description would fit it unchanged, that level is **generic**.

- **The top level is specific** when it names what a correct answer to *this* 小題 contains: the expected choice or value, a concept, variable, data point or named thing from this item, or the particular reasoning link. Process words alone do not count: 「完整正確回答」「完整合理說明」「正確推論並有證據支持」.
- **A partial level is specific** when it names at least one way an answer to *this* 小題 falls short, in this item's terms: which element is missing or wrong, or which link breaks. 「部分正確」「說明不完整」「理由不足」 are generic unless they say *what* is incomplete.
  - When a partial level lists alternatives (「…；或…」), one specific alternative is enough.
  - Count-shaped wording that names the item's elements (「僅從孢子含量或致死率其中一個面向說明」) still counts as specific here. Whether counting is legal is a separate check.
- **A partial level can borrow specificity from the top level.** 「選A，但理由說明不完整」 is specific only if the stated choice is itself this item's content *and* the top level names what the full reason is. If neither level says what a complete reason contains, the partial level is generic.

## The label

- **vague**: the top level is generic, **or** a partial level exists and every alternative in it is generic.
- **specific**: otherwise.

For every label, record a short reason that quotes the deciding phrase. Mark an entry **borderline** when the call could reasonably go the other way, so the spot-check knows where to look first.
