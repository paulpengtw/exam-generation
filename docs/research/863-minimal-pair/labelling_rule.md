# Labelling rule: 最小對照 (#863)

**Version 1, posted on [#863](https://github.com/paulpengtw/exam-generation/issues/863) before any labelling.** It extends [#862's labelling rule, version 2](../862-student-examples/labelling_rule.md), the version #862 says later slices must reuse: one written rule, a short quoted reason per label, borderline marks, and every disagreement listed for the owner.

This rule is for the **independent labeller** only. It produces the reference labels that the checker's `minimal_pair_violation` flag is compared against. It is written separately from the checker's prompt, and the labeller never sees the checker's verdicts.

## The rule being labelled

From the block approved in [#871](https://github.com/paulpengtw/exam-generation/issues/871#issuecomment-5846500569) (unchanged from [#653](https://github.com/paulpengtw/exam-generation/issues/653)):

> 第一個 [1] 實例是 [2] 實例的最小對照：提出相同的主張、相同數量的要點，也附了理由，差別只在理由沒有接上推理鏈（依據不足、連結錯誤，或未回扣證據）。第二個 [1] 實例呈現另一種缺口。若依【判準】屬「能框定」，[1] 實例可改為缺少集合中的一個具名成分。

## What is labelled

- **The unit is one 小題 presented with a full 1 / 2 / 1 example set.** The object labelled is the pair formed by its [2] example and its **first** [1] example. Each unit's id is `<item>|<variant>`.
- **Label: `pass` or `fail`.** Positive means a violation (`fail`), as in #862, so the checker should flag it.
- **The second [1] example and the [0] example are context, not the object.** They are held fixed for each item. The fixed 1 / 2 / 1 count is a deterministic hook and is not labelled.
- **#862's three rules are not labelled here.** Every example is written to pass them: student voice, this item's data, variables or names, and a plausible [0].

## Terms

- **主張 (claim).** The answer to the question the stem asks: the choice, the prediction, the conclusion, the recommended design. Two claims are the same if they would be scored as the same answer; paraphrase is allowed.
- **要點 (point).** A separate answer component that could earn credit on its own: a named member of a framed set, or a second, independent reason or piece of evidence that would complete the chain by itself. **Links inside one reasoning chain are not separate points.** Leaving out a link (citing the data but not the mechanism, or the reverse) is a chain gap, not a missing point.
- **理由 (reason).** A clause offered as justification (因為、所以、由…可知、從表中…). A reason that only restates the claim (「A比較好，因為A的效果比較好」) counts as **no reason**; mark it borderline.
- **接上推理鏈 (closes the chain).** The reason does what the rubric's [2] 規準說明 requires. A [1] example whose reason closes the chain would earn [2] under this rubric.
- **能框定 (framed).** Decided by 【判準】, per item, and recorded with its basis:
  - **題幹**: the stem names the members (「(1)…(2)…」「從甲、乙兩個面向」).
  - **科學概念必要環節**: the concept is itself made of several necessary links.
  - **圖表**: under [#859](https://github.com/paulpengtw/exam-generation/issues/859), a figure or table frames a set only when every member can be read directly off it as a visible label (axis, column, row, legend entry or region). A set that comes from analysing the data is not framed.

## Labels

**`pass`** in two shapes:
- **`true_pair`**: same claim and the same number of points as the [2] example, with a reason present. The only difference is that the reason does not close the chain (依據不足、連結錯誤, or 未回扣證據). The reason may be shorter. There is no length rule.
- **`framed_omission`**, on 能框定 items only: the [1] example leaves out **exactly one** named member of the set. What it says about the other members matches the [2] example.

**`fail`**, by near-miss type:
- **`fewer_points`**: fewer points than the [2] example on an item that is **not** framed. What remains is as complete as in the [2] example, so the difference is a count, not a chain gap. (On a framed item, leaving out one named member is `framed_omission` instead.)
- **`different_claim`**: it makes a different claim, with or without a reason.
- **`no_reason`**: same claim (and the same points) with no reason at all, or a reason that only restates the claim.
- **`closes_chain`**: same claim and points, and the reason closes the chain. This is a mislabelled [2].
- **`omission_plus_gap`**, framed items: it leaves out one named member **and** the reason for a member it keeps does not close the chain. The exception replaces the chain gap; it does not add to it.
- **`omits_two`**, framed items with three or more members: it leaves out two or more named members.

## Borderline marks

Mark a label borderline, with the deciding phrase quoted, when:
- the dropped content could be read either as a separate point or as a link in one chain;
- the reason is close to a restatement of the claim;
- whether the item is framed is arguable, especially a figure-framed item when the checker cannot see the figure;
- a near-miss reason might arguably close the chain.

## The synthetic set

The corpus has about one clean real pair (`fasting-method` 序號 2), so the set is synthetic. The labeller writes it:
- **About 20 open-response items from the few-shot corpus**, spread across three strata:
  - not framed;
  - framed by the stem or by the concept;
  - framed by a figure under #859.
  It includes both 社會領域 `範例_` rows.
- **Per item, a conforming 0 / 1 / 2 rubric** in the block's shape, a [2] example, a second [1] example showing a different gap, and a plausible [0] example. These are held fixed across the item's variants.
  - The [1] 規準說明 names the two gaps that the true pair and the second [1] show.
  - On a framed item's `framed_omission` variant, the first gap names the missing member instead, as a generator following the block would write it.
- **Per item, one first-[1] example per variant**:
  - not-framed items: `true_pair`, `fewer_points`, `different_claim`, `no_reason`, `closes_chain`;
  - framed items: `true_pair`, `framed_omission`, `different_claim`, `no_reason`, `closes_chain`, `omission_plus_gap`, and `omits_two` where the set has three or more members.
  - The `fewer_points` variant may carry its own [2] example with two independent points, because a [2] with one point leaves nothing to drop.
- **Gap kinds rotate.** The true pairs spread across 依據不足、連結錯誤 and 未回扣證據.
- **The real pair is kept.** `fasting-method` 序號 2 keeps its real [2] and [1] examples as its `true_pair`.
- **#859's three relabels apply to anything reused from the verifier prototype's set:** `black-white-car-heat` 5 and `entomopathogenic-fungi` 6 move to 題幹, and `entomopathogenic-fungi` 5 becomes VIOLATES. Of these, `entomopathogenic-fungi` 6 is used as a stem-framed item.

Each variant's design type is the labeller's intent. After writing the whole set, the labeller re-reads every unit against this rule alone and records the final label, any borderline mark and the quoted reason. Where the re-read disagrees with the design type, the label wins and the change is noted.

## The checker sees

The checker runs on the same prompt shape as #862: the item, its rubric and the full example set. No two variants of one item are ever in the same checker batch. **The figure is not shown.** The corpus carries no image files for these items, as in #651, so figure-framed units are reported as their own stratum.

## Output per unit

`{id, item, stratum, framing_basis, variant, gap_kind, label, borderline, reason}`
