# 試題生成 (Exam Generation)

Generates 108課綱-aligned exam items for 數學, 社會領域 and 自然科學 from curriculum data, via LLM calls with a verify-and-correct loop.

## Language

### 題目結構 (Item structure)

**題組**:
A parent item consisting of a shared 文本 plus several 小題. The unit that 社會領域 and 自然科學 always produce.
_Avoid_: question set, question group

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
The per-小題 settings a user supplies before generation — 題型, 出題指示, 字數限制, and explicit 學習內容/學習表現.
_Avoid_: subquestion config, per-item settings

**出題指示**:
A free-text instruction attached to one 小題, telling the generator what that 小題 should focus on.
_Avoid_: instruction, hint, guidance

**預抽**:
Resolving a value that would otherwise be chosen randomly during generation, before the user confirms, so the confirmation screen can show it.
_Avoid_: pre-draw, pre-roll, client-side sampling

**釘選**:
Sending a resolved value with the request so nothing downstream re-randomises it. A 預抽 value is always 釘選.
_Avoid_: pin, lock, fix

**建議值**:
A submitted setting the generator is asked to honour but is not required to. Contrast 強制值.
_Avoid_: hint, suggestion, soft constraint

**強制值**:
A submitted setting enforced after generation regardless of what the model returned. Contrast 建議值.
_Avoid_: enforced value, hard constraint, override

### 流程 (Pipeline)

**文本生成器**:
The first generation stage for 社會領域 and 自然科學. Produces the 文本, 核心問題, 取材來源 and a plan of 小題.
_Avoid_: text generator, stage one, planner

**子題產生器**:
The second generation stage. One call per planned 小題, each writing one complete 小題.
_Avoid_: subquestion generator, stage two, worker

**發送前確認**:
The screen shown after the user submits the form and before generation begins, stating what will be sent.
_Avoid_: confirmation dialog, review screen, preview

**提示詞預覽**:
The literal system and user prompt text displayed on 發送前確認, assembled without calling any model.
_Avoid_: prompt preview, dry run, payload preview

**生成進度列**:
The bar fixed to the bottom of 生成頁面, stating which 生成步驟 a run has reached.
_Avoid_: sticky bottom bar, navbar, progress bar, 進度條
