## Purpose

Keep every open-response 評分規準 anchored to how complete the student's reasoning chain is, not to how many items the student lists, and make each rubric carry student-voice examples a teacher can score against. This covers the rule given to the prompts that write rubrics, the scale stated by every other prompt, and the deterministic shape check applied at verification.

## ADDED Requirements

### Requirement: Rubric-authoring prompts carry the open-response rubric rule verbatim
The 子題產生器 system prompt and the corrector system prompt of both 社會領域 and 自然科學 SHALL contain the open-response rubric rule block below, byte-identical across all four prompts. In each 子題產生器 prompt the block SHALL replace the existing open-response scale line. In each corrector prompt it SHALL be added as the rule to follow whenever an open-response 評分規準 is written or changed.

The block below is the version approved in #871 (with #859's 【判準】 amendment and #650's 【提問】/【額外項目】 amendments). It has **seven** clause markers: 【禁止】【判準】【注意】【提問】【額外項目】【具體性】【學生作答實例】. Note that 【判準】 and 【額外項目】 are also referenced mid-sentence inside other clauses, so the unit test asserts each marker starts a clause exactly once (count at line start after indentation), not raw substring counts. The fixed sentence `「學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。」` (#871) is defined as the constant `EXTRA_ITEMS_FIXED_SENTENCE` in `src/common/open_response_rubric.py` and interpolated into the block; tests assert the constant appears in the block and the assembled block is byte-identical to the approved text.

The block is:

```
- 開放式建構反應題 / Constructed response：必須附每題專屬 `評分規準`，固定使用 2 / 1 / 0 三級。
  級距依「該小題所宣告的認知歷程（社會領域）／科學能力（自然科學）被完成到什麼程度」區分，
  也就是學生推理鏈條的完整度：
  - [2] 完整走完該認知歷程／科學能力所要求的推理，且有證據支持。
  - [1] 已進入該推理，但鏈條有缺口：依據不足、連結錯誤，或結論未回扣證據。
  - [0] 未進入該推理，或方向錯誤。
  【禁止】不得以學生列舉的項目「數量」區分級距。
  【判準】要分辨是「完整度」還是「數量」，看該小題自身的題目敘述與所宣告的
  學習內容／科學能力，能否在事前把「完整答案的成分集合」框定下來：
  - 能框定 → 依補齊幾個成分分級為合法，且 [2] 必須逐一指名該集合的成員。
    （例：題目明寫「請從甲、乙兩個面向說明」；或該科學概念本身即由數個必要環節構成；
    或題目所指的圖表本身決定了成員——完整答案可直接從圖表讀出，任何人看圖即列出同一份清單。）
    以圖表框定時，[2] 須指明每個成員取自哪一張圖表（如「圖(一)」「附表」），
    且該成員須以該圖表上可見的標示出現（軸、欄、列、圖例或區域）。
  - 不能框定 → 不得依數量分級；[1] 必須以推理鏈條的缺口描述，
    不得寫成「僅提及其中之一」。
    （例：題目問「有什麼好處？」「請提出建議」，可接受的答案是一群開放、獨立的項目；
    或「研究員為何質疑？」這類須分析資料才能提出的項目——圖表只提供資料，不決定成員。）
  【注意】題幹指定的「數量」不等於框定「集合」。「請寫兩個結論」只固定了個數，
  並未固定是哪兩個，因此屬於不能框定。
  【提問】小題要求學生寫出兩項以上時，必須逐一點名各項是什麼（「一個優點與一個缺點」
  「從甲、乙兩個面向」「(1)…(2)…」），使完整答案的成分集合可事前框定。
  不得要求學生從開放集合中自行產出若干項——不論以數字（「請寫兩個結論」「至少列舉三項」）
  或以「有哪些」提問。若集合已由題目框定，所要求的個數必須等於該集合的全部成員；
  「其中任 N 項」只固定個數、未固定是哪幾項，屬於不能框定。只要求一項時不在此限。
  若出題指示或出題概念要求學生列出若干項，請保留其數量並逐一點名各項；
  無法點名時，改為只要求一項。
  【額外項目】學生可能寫出比小題要求更多的項目。級距依學生所寫最完整的一項評定
  （能框定時，每個成分各取最完整的一項）；其餘為額外項目，不論對錯都不影響級距，
  只有與得分的作答矛盾（兩者不可能同時成立）時，最高給 [1]。
  - [2] 的規準說明結尾必須逐字加上這一句：
    「學生多寫的其他項目不影響評分，但若與得分的作答矛盾，最高給 [1]。」
  - [2] 只能要求本題指定的成分成立，不得要求學生自行多寫的項目也成立
    （不得寫成「所提結論皆…」「所列理由都…」）。
  【具體性】規準說明必須指名本小題的內容——[2] 要寫出本題該答對什麼，
  [1] 要寫出本題最可能出現的兩種缺口，與下方兩個 [1] 實例一一對應。
  不得使用「完整正確回答／部分正確／錯誤」這類可套用到任何題目的字樣
  （【額外項目】規定的固定句不在此限）。
  學生作答實例必須是本小題的作答——用到本題文本中的資料、變因或名稱；
  不得使用「例如：」「完整正確回答」「（空白）」這類可貼到任何題目的內容。
  【學生作答實例】每一級距的實例數固定為：[2] 一個、[1] 兩個、[0] 一個。
  實例不得包含額外項目。
  - 實例是學生可能真的寫出的作答原文，以學生口吻書寫。實例裡不得出現對這份作答的
    評語（如「未說明原因」「只寫一點」「部分正確」）——評分理由寫在規準說明，不寫在實例裡。
    若本小題要求繪圖、標示或作圖，實例改為中性描述學生畫了什麼，同樣不加評語。
  - 第一個 [1] 實例是 [2] 實例的最小對照：提出相同的主張、相同數量的要點，也附了理由，
    差別只在理由沒有接上推理鏈（依據不足、連結錯誤，或未回扣證據）。
    第二個 [1] 實例呈現另一種缺口。
    若依【判準】屬「能框定」，[1] 實例可改為缺少集合中的一個具名成分。
  - [0] 實例是本小題最可能引出的錯誤觀念或錯誤方向，須是學生合理會寫的答案；
    不得使用空白、「不知道」、或與題目無關、荒謬的作答。
```

The 自然科學 corrector also adds the counting-stem routing line (#650) to its 修正原則 list, after the 評分規準 principle line:

```
- 若問題在小題以數字或「有哪些」要求學生從開放集合列舉（計數式提問）→ 改寫該小題題目為
  逐一點名各項或只要求一項，並同步修改答案/答案解析/評分規準。
```

This routing line is defined as `COUNTING_STEM_CORRECTION_ROUTING_LINE` in `src/common/open_response_rubric.py` so that #868 (社會領域) can reuse it.

#### Scenario: 社會領域 子題產生器 prompt carries the block
- **WHEN** the 社會領域 子題產生器 system prompt is built for any 學習階段
- **THEN** it contains the block exactly once
- **AND** it no longer contains 「使用 0..N 並允許部分給分」 or 「每一分數級距請提供 1-2 個學生作答實例」

#### Scenario: 自然科學 子題產生器 prompt carries the block
- **WHEN** the 自然科學 子題產生器 system prompt is built
- **THEN** it contains the block exactly once
- **AND** it no longer contains 「Constructed response：必須附 `評分規準`，使用 2 / 1 / 0 / 0X，並提供學生作答實例。」

#### Scenario: Both correctors carry the block
- **WHEN** the 社會領域 or 自然科學 corrector system prompt is built
- **THEN** it contains the block, introduced as the rule for writing or changing an open-response 評分規準

#### Scenario: The four copies cannot drift
- **WHEN** the four rubric-authoring prompts are built
- **THEN** the block text in each is byte-identical to the others

### Requirement: Every prompt states the open-response scale as 2 / 1 / 0
No generation, correction or verification prompt of 社會領域 or 自然科學 SHALL describe open-response scoring as `0..N`, as partial credit on an open-ended scale, or as `2 / 1 / 0 / 0X`. Where a prompt that does not write rubrics mentions the open-response scale, it SHALL state three fixed levels, 2 / 1 / 0. The scoring text for 選擇題 and `Complex multiple-choice` SHALL remain byte-identical to its current wording.

#### Scenario: 社會領域 文本生成器 prompts
- **WHEN** the 社會領域 文本生成器 system and user prompts are built
- **THEN** neither contains 「0..N」
- **AND** each open-response scale mention states 2 / 1 / 0

#### Scenario: 社會領域 verification prompt
- **WHEN** the 社會領域 verification system prompt is built
- **THEN** it states the open-response scale as 2 / 1 / 0 and does not contain 「0..N」

#### Scenario: 自然科學 legacy system prompt
- **WHEN** the 自然科學 legacy system prompt template is rendered
- **THEN** its Constructed response line states 2 / 1 / 0 and mentions neither `0X` nor 學生作答實例

#### Scenario: Multiple-choice scoring text is untouched
- **WHEN** the prompts of both subjects are built
- **THEN** 「選擇題計分使用 0/1（答對 1 分、答錯 0 分）」 and 「Complex multiple-choice：通常採整組計分；全對代號 2，部分正確可給 1，錯誤代號 0，未作答 0X。」 appear exactly as before wherever they appeared before

### Requirement: Prompts that do not write rubrics carry no 學生作答實例 instructions
The 社會領域 文本生成器 prompts (including the legacy system-prompt text they embed), the 自然科學 legacy system prompt and the 社會領域 verification prompt SHALL NOT instruct how many 學生作答實例 a level carries. Example instructions SHALL appear only inside the rule block in the four rubric-authoring prompts.

#### Scenario: 文本生成器 prompt has no example instructions
- **WHEN** the 社會領域 文本生成器 system prompt is built
- **THEN** it does not contain 「學生作答實例」

#### Scenario: Verification prompt no longer counts examples
- **WHEN** the 社會領域 verification system prompt is built
- **THEN** it does not contain 「每一分數級距應有 1-2 個學生作答實例」

### Requirement: Verification fails an in-scope open-response 小題 whose rubric shape deviates
For every in-scope open-response 小題 (see the scope requirement), verification SHALL, after the LLM verdict, check deterministically that the 評分規準 has exactly one entry for each of the codes 2, 1 and 0 and no other code. It SHALL also check that the level carries exactly 1 學生作答實例 at [2], 2 at [1] and 1 at [0], each non-empty after trimming whitespace.

Any deviation SHALL make the verification result not passed, whatever the LLM verdict was. For each deviation, the details SHALL gain an entry naming the 小題 序號, the level, and the expected and actual count, and saying what the missing example must show:
- [2]: a student's complete answer to this 小題.
- [1]: the first example is a 最小對照 of the [2] example; the second shows a different gap.
- [0]: the misconception or wrong direction this 小題 most likely draws out.

Existing details text SHALL be kept. The check SHALL NOT judge example content (student voice, 最小對照, specificity or plausibility).

#### Scenario: A conforming rubric passes
- **WHEN** an in-scope 小題 has codes 2 / 1 / 0 with 1 / 2 / 1 non-empty examples and the LLM verdict passes
- **THEN** verification passes and the details are unchanged

#### Scenario: Level 1 is missing its second example
- **WHEN** an in-scope 小題 has only one example at [1]
- **THEN** verification is not passed
- **AND** the details name the 小題, level [1], expected 2 and actual 1, and say the second example must show a different gap from the 最小對照

#### Scenario: A blank example does not count
- **WHEN** the [0] level of an in-scope 小題 holds a single example that is empty after trimming
- **THEN** verification is not passed and the details name level [0] of that 小題

#### Scenario: Wrong level set
- **WHEN** an in-scope 小題 has codes 3 / 2 / 1 / 0, or only 2 / 0, or a duplicated code
- **THEN** verification is not passed
- **AND** the details state that the levels must be exactly 2 / 1 / 0 and list the codes found

#### Scenario: Several 小題 deviate
- **WHEN** two in-scope 小題 of one 題組 deviate
- **THEN** the details report each 小題 by its 序號

#### Scenario: The LLM verdict already failed
- **WHEN** the LLM verdict failed with details X and an in-scope rubric also deviates
- **THEN** verification is not passed and the details keep X and add the rubric entries

#### Scenario: Example content is not judged here
- **WHEN** an in-scope rubric has the right levels and counts but its [1] examples are descriptions rather than answers
- **THEN** this check reports nothing for that rubric

### Requirement: The shape check applies only to open-response 小題, with a 社會領域 legacy exemption
The check SHALL apply to a 小題 whose own 題型 is 開放式建構反應題 (社會領域) or `Constructed response` (自然科學). The decision SHALL be made per 小題, never from the 題組's headline 題型 or the few-shot folder. It SHALL NOT apply to 選擇題, 封閉式建構反應題, `Simple multiple-choice` or `Complex multiple-choice` 小題.

In 社會領域 the check SHALL apply only to 小題 that declare a 認知歷程; a legacy 社會領域 小題 without one SHALL pass the check untouched, as it already does under the legacy `0X` exemption. In 自然科學 it SHALL apply to every open-response 小題, including pre-change records re-verified during 人工審題修正.

#### Scenario: Complex multiple-choice is unaffected
- **WHEN** a `Complex multiple-choice` 小題 carries 2 / 1 / 0 / 0X with no examples
- **THEN** the check reports nothing for it

#### Scenario: A mixed 題組 is checked per 小題
- **WHEN** a 題組 whose headline 題型 is `Complex multiple-choice` contains a `Constructed response` 小題 with a deviating rubric
- **THEN** that 小題 is checked and verification is not passed

#### Scenario: 社會領域 legacy record is exempt
- **WHEN** a 社會領域 open-response 小題 without a 認知歷程 carries only a `0X` level and the LLM verdict passes
- **THEN** verification passes and the details are unchanged

#### Scenario: 社會領域 record with a 認知歷程 is checked
- **WHEN** a 社會領域 open-response 小題 that declares a 認知歷程 has a deviating rubric
- **THEN** verification is not passed

#### Scenario: A pre-change 自然科學 record is re-verified in 人工審題修正
- **WHEN** a stored 自然科學 record whose open-response rubric is 2 / 1 / 0 / 0X with no examples is re-verified during 人工審題修正
- **THEN** verification is not passed with the shape entries in its details
- **AND** the stored original is not overwritten; any corrected result is saved as a new version linked to it

### Requirement: The legacy 0X rejection points to the 2 / 1 / 0 scale
When a 社會領域 小題 that declares a 認知歷程 carries a `0X` code, verification SHALL keep failing it. Its details SHALL name the 小題 and `0X`, and direct the fix to the fixed 2 / 1 / 0 scale rather than to `0..N`.

#### Scenario: A new record carries 0X
- **WHEN** a 社會領域 open-response 小題 with a 認知歷程 carries a `0X` code
- **THEN** verification is not passed
- **AND** the details contain 「第1題」, 「0X」 and 「2 / 1 / 0」, and do not contain 「0..N」

### Requirement: Reading stored rubrics stays backward compatible
Loading, displaying and exporting stored records SHALL keep accepting any rubric code string, including legacy `0X` and codes above 2, and any number of 學生作答實例. The new rule SHALL be enforced only in generation, correction and verification prompts and in the verification check.

#### Scenario: A legacy record is loaded and shown
- **WHEN** a stored record whose rubric has codes 3 / 2 / 1 / 0 / 0X and empty example lists is loaded and displayed
- **THEN** it loads without error and its levels render as stored
