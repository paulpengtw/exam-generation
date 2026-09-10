# 試題生成 (Exam Generation)

Generates 108課綱-aligned exam items for 數學, 社會領域 and 自然科學 from curriculum data, via LLM calls with a verify-and-correct loop.

## Language

### 題目結構 (Item structure)

**題組**:
A parent item consisting of a shared 文本 plus several 小題. The unit that 社會領域 and 自然科學 always produce.
_Avoid_: question set, question group

**圖像種類**:
The concrete visual genre of a 題組 image — 直方圖, 圓餅圖, 表格, 地圖, 實驗裝置 and similar — independent of which renderer produces it. The ADR 0015 distinct-kind guarantee is currently 社會領域-only; 自然科學 supports 題幹 and 小題 images but is outside that guarantee.
_Avoid_: image kind / figure type / chart kind

**小題**:
One answerable question inside a 題組, carrying its own 題型, 答案 and 評分規準.
_Avoid_: subquestion, sub-item, part

**文本**:
The shared stimulus material a 題組's 小題 are answered against — passage, data, or figure.
_Avoid_: passage, stimulus, prompt

**核心問題**:
The essential question a 題組 is built around. Supplied by the user or produced by a planning call.
_Avoid_: topic, theme, essential question

**主題**:
A free-text subject hint the user may supply to steer generation. Distinct from 核心問題, which is a formed question.
_Avoid_: topic (ambiguous with 核心問題)

### 課綱 (Curriculum)

**學習內容**:
A 108課綱 content code naming what a 小題 covers.
_Avoid_: learning content code, LC, curriculum code

**學習表現**:
A 108課綱 performance code naming the cognitive demand a 小題 places on the student.
_Avoid_: learning performance, LP, standard

**全域池**:
The 學習內容 or 學習表現 codes selected for a whole request, from which individual 小題 draw when they have no explicit selection of their own.
_Avoid_: global pool, request-level codes, parent codes

### 設定 (Configuration)

**各小題配置**:
The per-小題 settings a user supplies before generation — 題型, 出題指示, 題目內容類型, 圖片生成模式, 題目字數限制, 選項字數限制, and explicit 學習內容/學習表現. Note: 文本字數限制 is a request-level setting only and is NOT a valid per-小題 config key (ADR 0023).
_Avoid_: subquestion config, per-item settings

**出題指示**:
A free-text instruction attached to one 小題, telling the generator what that 小題 should focus on.
_Avoid_: instruction, hint, guidance

**文本出題指示**:
A free-text instruction to the 文本生成器 that steers text-stimulus generation for a 題組. A request-level value applies to all 題組 in a batch by default. Since issue #637, each 題組 on the 發送前確認 screen shows an editable textarea prefilled from the request-level value; a non-blank edit for one 題組 is 釘選 as `per_question_params[i].text_instruction` and routes to that 題組's 文本生成器 only, leaving sibling 題組 and all 子題產生器 prompts unchanged. Clearing the textarea reverts that 題組 to the request-level value rather than to empty. It is a 建議值 and is distinct from the per-小題 出題指示.
_Avoid_: instruction, text prompt, passage prompt

**出題模式**:
The request setting that chooses whether batch-wide variety is suggested to the model; it does not control sampling.
_Avoid_: coverage mode, sampling mode, distribution strategy

**均衡**:
The 出題模式 that adds a prompt-level instruction asking the model to spread 題型 and 取材角度 across a batch; it never affects mechanical draws.
_Avoid_: balanced sampling, stratified mode, even allocation

**隨機**:
The 出題模式 that adds no batch-variety instruction to the prompt and leaves the existing independent draws unchanged.
_Avoid_: random sampling mode, shuffle mode, unbalanced mode

**回扣核心問題**:
The request option asking that a 題組's last 小題 be a synthesis question explicitly asking the student to address that 題組's own 核心問題, integrating the earlier 小題. On by default; a 建議值 that composes with any 各小題配置 on the last 小題 and never affects which 題型 is drawn.
_Avoid_: callback, echo, 總結小題, 呼應核心問題

**預抽**:
Resolving a value that would otherwise be chosen randomly during generation, before the user confirms, so 發送前確認 can show it. Covers every such value except the 參考範例 draw — see 全量預抽.
_Avoid_: pre-draw, pre-roll, client-side sampling

**全量預抽**:
The promise that every value generation would otherwise draw is resolved by 預抽 and 釘選 before 發送前確認, so nothing shown to a supervisor can change after they send. The 參考範例 draw is the single deliberate exception; its outcome is disclosed after the fact as 參考範例紀錄 rather than before sending. Drawing during generation survives only until the web client obtains its 預抽 from the server-side resolver; it is then removed together with the generation gate that rejects incomplete requests. Every caller — web, API or CLI — resolves first and generates second.
_Avoid_: full pre-draw, exhaustive sampling, no-backend-randomness

**從屬參數**:
A setting whose legal values are fixed by another setting's resolved value — 情境子類別 by 情境; 學習內容 / 學習表現 by 科目; and, for 公民與社會 and 跨科, 學習內容 also by 內容領域. A child may have several parents, and its range is the intersection of theirs. 預抽 resolves every parent first and draws the child only from that range. A pair drawn from unrelated ranges is invalid and is rejected, never silently corrected.
小題數 is also a structural parent: the per-小題 slot list (the 各小題配置 rows) exists only because of the resolved 小題數.
When 小題數 is 重抽, the slots are rebuilt to the new count; 覆寫'd rows keep their values where they survive, while untouched 預抽 rows re-resolve.
_Avoid_: dependent field, child parameter, cascading select, parented value

**未送出的輸入**:
Form input the user has entered but not yet sent for generation. It exists from the user's first edit onward; values supplied programmatically by 預抽 or prefilled by Regenerate do not create it without the user's own edit.
_Avoid_: unsaved changes, dirty state, unsubmitted changes

**釘選**:
Sending a resolved value with the request so nothing downstream re-randomises it. A 預抽 value is always 釘選.
_Avoid_: pin, lock, fix

**確認頁修改**:
Editing any resolved 預抽 value on the confirmation screen — a 題組-level row such as 內容領域, 核心素養 or 數學思考, or a 各小題配置 row. The edited value becomes user-supplied and 釘選; untouched values keep their 預抽 state. Editing a 從屬參數 parent behaves like 重抽 of that parent with the chosen value: its children re-resolve from the new range, and a pinned child that no longer fits is cleared and re-resolved, never silently corrected. Applies per 題組 — it never writes back to the shared form configuration.
_Avoid_: final modification, confirmation edit, last-minute tweak

**重抽**:
Clearing a resolved value on the confirmation screen, causing an immediate new 預抽 from the 全域池 for that field only. Sibling fields and the seed are untouched.
_Avoid_: re-roll, re-draw, re-randomise

**圈選**:
One cursor-drag selection over a question's content — an arbitrary span that may cross 文本/小題 boundaries, serialized as field-addressed segments.
_Avoid_: selection, highlight, span, 選取

**修改指示**:
The free-text instruction attached to one 圈選, a constraint the run must preserve; it deliberately echoes 出題指示.
_Avoid_: note, comment, suggestion, annotation, 修改建議 (建議值 already means honoured-but-not-required)

**人工審題修正**:
A user-initiated run sending 圈選+修改指示 batches through 修改→驗證→修正, producing a new version linked to its parent; contrast the automatic 修正 stage.
_Avoid_: 精修, modify, patch, partial regeneration, 局部再生成

**建議值**:
A submitted setting the generator is asked to honour but is not required to. Contrast 強制值.
_Avoid_: hint, suggestion, soft constraint

**強制值**:
A submitted setting enforced after generation regardless of what the model returned. Contrast 建議值.
_Avoid_: enforced value, hard constraint, override

**Reporting Scale**:
The PISA Science proficiency level (1c, 1b, 1a, 2, 3, 4, 5, 6) that a 自然科學 小題 targets. 自然科學-only: 數學 and 社會領域 use 難度 instead. The headword is deliberately English in this Chinese-language glossary because the interface shows the literal English term untranslated in both zh-TW and en locales — no established Chinese equivalent exists. 每小題可各自指定，未指定者承襲題組層級的值；題組層級亦未設定時，每個空位的值由 預抽 解析並 釘選。
_Avoid_: 難度 (wrong term for 自然科學), 報告等級

**難度**:
The easy / medium / hard demand signal for 數學 and 社會領域. Not used for 自然科學, which uses Reporting Scale instead.
_Avoid_: using 難度 for 自然科學

### 流程 (Pipeline)

**文本生成器**:
The first generation stage for 社會領域 and 自然科學. Produces the 文本, 核心問題, 取材來源 and a plan of 小題.
_Avoid_: text generator, stage one, planner

**子題產生器**:
The second generation stage. One call per planned 小題, each writing one complete 小題.
_Avoid_: subquestion generator, stage two, worker

**驗證模型**:
The model tier that runs the 驗證 生成階段. When unset, calls fall through to the 執行模型. Contrast 修正模型.
_Avoid_: verify model, verifier model

**修正模型**:
The model tier that runs the 修正 生成階段. When unset, calls fall through to the 執行模型. Contrast 驗證模型.
_Avoid_: correct model, corrector model

**Agent 自主驗證修正歷程**:
The per-question record of the 驗證/修正 loop — every 驗證 verdict and every 修正 pass with its resulting question snapshot. Exists even when 驗證 passes first try; sibling of the question, never inside it.
_Avoid_: trail, correction trail, 修正紀錄, audit log, correction_trail.

**發送前確認**:
The screen shown after the user submits the form and before generation begins, stating what will be sent.
_Avoid_: confirmation dialog, review screen, preview

**破壞性操作確認**:
A modal that interrupts an action which would irreversibly discard the user's work or end their session, requiring explicit assent before it proceeds; it appears on the way to that destructive or irreversible action, not on the way to sending a form. Contrast 發送前確認.
_Avoid_: destructive-action modal, are-you-sure dialog, warning modal

**參考範例**:
The stored worked 題組 injected into a prompt to show the model the target form. Which ones appear is fixed by the request's seed, so one payload always yields the same 參考範例; the choice is not 預抽 and is not shown on 發送前確認, but which ones were drawn is disclosed afterwards as 參考範例紀錄.
_Avoid_: few-shot examples, exemplars, reference samples

**參考範例紀錄**:
The record of which 參考範例 each 生成步驟 of a generation drew — one entry per stage and per 小題, each naming the example and holding exactly the portion the prompt received. A sibling of the question, like Agent 自主驗證修正歷程; survives a failed or aborted run for the stages that had already drawn; states explicitly when 關閉參考範例 was set.
_Avoid_: few-shot log, example trail, 參考範例歷程

**認知歷程範例**:
A stored 小題 showing one 認知歷程 in practice, drawn per 小題 by that 小題's 認知歷程. 社會領域 only.
_Avoid_: process exemplar, 歷程範例

**提示詞預覽**:
The literal system and user prompt text displayed on 發送前確認, assembled without calling any model.
_Avoid_: prompt preview, dry run, payload preview

**生成進度列**:
The bar fixed to the bottom of 生成頁面, stating which 生成步驟 a run has reached.
_Avoid_: sticky bottom bar, navbar, progress bar, 進度條

**生成步驟**:
One unit of a question's generation pipeline — 文本, 子題, 圖片, 驗證, 修正. Per-question, coarser than the per-agent stage events.
_Avoid_: phase, stage, 階段, 生成階段
