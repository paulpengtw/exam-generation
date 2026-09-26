## Context

動機見 proposal.md（Why）；行為契約見 `specs/open-response-rubric/spec.md`。以下為 `origin/staging` `e1014bf` 的現況，也是決定做法的約束。

- **級距與實例語句散落十處 prompt，外加兩份文件。**
  - 社會領域 [`context_builder.py`](https://github.com/paulpengtw/exam-generation/blob/e1014bf/src/social_studies/context_builder.py)：L374、L489、L490、L918、L971、L1054、L1155、L1170。
  - 自然科學 [`context_builder.py`](https://github.com/paulpengtw/exam-generation/blob/e1014bf/src/natural_sciences/context_builder.py)：L216、L828。
  - 社會領域 [`verifier.py`](https://github.com/paulpengtw/exam-generation/blob/e1014bf/src/social_studies/verifier.py)：L36、L37。
  - 文件：`docs/ADDING_SAMPLES.md`，以及 `data/social_studies/curriculum/schema_parameters.csv` 第 8 列。
- **各段 prompt 的來源。**
  - 社會領域文本生成器 system prompt 在 L984 引入舊版 `build_system_prompt`（L374、L489、L490）。
  - 自然科學舊版 `SYSTEM_PROMPT_TEMPLATE`（L216）只有測試在呼叫。
  - `schema_loader` 只讀取 CSV 的值，說明欄不進 prompt。
- **兩科 corrector 的 `_CORRECTION_SYSTEM_PROMPT_CORE` 都能改寫 `評分規準`**，但既沒有級距，也沒有軸線或實例指引（[社會領域 L62](https://github.com/paulpengtw/exam-generation/blob/e1014bf/src/social_studies/corrector.py#L62)、[自然科學 L66](https://github.com/paulpengtw/exam-generation/blob/e1014bf/src/natural_sciences/corrector.py#L66)）。
- **Post-verify hook 接縫已存在。**
  - 契約（[`common/verifier.py`](https://github.com/paulpengtw/exam-generation/blob/e1014bf/src/common/verifier.py#L1-L27)）：`(question, result, client) -> result`，hook 可附加 `details` 並強制 `passed=False`，依序執行。
  - 社會領域已有 [`_ss_rubric_scale_check_hook`](https://github.com/paulpengtw/exam-generation/blob/e1014bf/src/social_studies/verifier.py#L242-L260)：只對有 `認知歷程` 的小題拒絕 `0X`。測試 `test_legacy_0x_rubric_code_is_left_untouched_by_new_era_check` 釘住「舊版紀錄不動」。
  - 自然科學有 `_NS_POST_VERIFY_HOOKS = [_ns_code_check_hook]`。
- **人工審題修正會重跑驗證**（`server/generate/modification_service.py` L288、L366），結果以 `parent_record_id` 存成新版本。
- **讀取與顯示端把級距當 opaque 字串。** `RubricEntry.code` 是 `str`；`web/src/hooks/useGenerate.ts` L41 已註明新舊級距都能呈現。
- **有兩個測試釘住舊字串。**
  - `tests/test_paper_rescore_retirement.py::test_new_social_studies_prompts_use_native_scoring_language` 斷言含「分數 0..N 可部分給分」與「每一分數級距附 1-2 個學生作答實例」。
  - `tests/test_natural_sciences_verifier.py` L186-231 的開放式題 fixture 預期通過。

## Goals / Non-Goals

**Goals:**

- 規則區塊只有一個來源，四個會寫規準的 prompt 取用同一份文字。
- 每一處級距語句都有明確的「現行 → 新」字串，實作時不必再判斷。
- 形狀檢核是純函式加兩個薄 hook，與既有 hook 接縫一致。
- 維持社會領域「舊版紀錄不動」的既有測試契約。

**Non-Goals:**

- 任何 LLM 判斷型準則：#651 的計數準則，以及 #860 的【具體性】與實例內容準則。
- few-shot 語料改寫（C4）、既有紀錄補救、誘答分析。
- 文本生成器 prompt 內「必須附評分規準」與「不得輸出規準」兩句並存的既有矛盾。#649 只要求在該處修正級距，本變更不處理。
- 前端、資料庫、SSE、`RubricEntry` schema。

## Decisions

### D1. 規則區塊單一來源

新增 `src/common/open_response_rubric.py`，定義常數 `OPEN_RESPONSE_RUBRIC_RULE`（spec 中的區塊文字）、`EXPECTED_EXAMPLE_COUNTS = {"2": 1, "1": 2, "0": 1}`，以及判定開放式題型的函式。四個 prompt 都以這個常數組字。

- **替代方案：四份字面複製。** 這是 #649「逐字相同寫進兩檔」的字面讀法，但會重演 #649 查到的九處漂移；使用常數才能保證 byte-identical，測試也只需檢查一處。
- **大括號。** 區塊不含 `{` 或 `}`，可以安全組進經 `.format()` 的社會領域子題產生器模板（L1155 以 `{{}}` 跳脫）。日後若修改區塊文字加入大括號，必須跳脫；D1 的單元測試會斷言區塊不含大括號。

### D2. 落點替換表

「區塊」代表 D1 的常數。選擇題子句一律保持原字不動。

| 位置 | 現行 | 新 |
|---|---|---|
| 社會領域 L374（舊版題型說明，經 L984 進文本生成器） | `…計分採每題專屬評分指引（scoring guide），分數 0..N 可部分給分；**必須附評分規準（rubric）**，每一分數級距附 1-2 個學生作答實例（含正確與錯誤示例）` | `…計分採每題專屬評分指引（scoring guide），固定 2 / 1 / 0 三級；**必須附評分規準（rubric）**` |
| 社會領域 L489 | `5. 開放式建構反應題必須附每題專屬的評分指引（scoring guide），分數使用 0..N 並允許部分給分；評分規準表每一分數級距附 1-2 個學生作答實例（含正確與錯誤示例）。` | `5. 開放式建構反應題必須附每題專屬的評分指引（scoring guide），固定使用 2 / 1 / 0 三級。` |
| 社會領域 L490、L1054 | `…；開放式建構反應題依每題專屬評分指引使用 0..N。` | `…；開放式建構反應題依每題專屬評分指引使用 2 / 1 / 0。` |
| 社會領域 L918（文本生成器題型說明） | `…計分採每題專屬評分指引，分數 0..N 可部分給分；**必須附評分規準**，每一分數級距附 1-2 個學生作答實例（含正確與錯誤示例）` | `…計分採每題專屬評分指引，固定 2 / 1 / 0 三級；**必須附評分規準**` |
| 社會領域 L971 | `4. 若為開放式建構反應題，必須附每題專屬的評分指引（scoring guide），分數使用 0..N 並附完整評分規準（rubric）；每一分數級距附 1-2 個學生作答實例（含正確與錯誤示例）。` | `4. 若為開放式建構反應題，必須附每題專屬的評分指引（scoring guide），固定使用 2 / 1 / 0 三級並附完整評分規準（rubric）。` |
| 社會領域 L1155（子題產生器誘答分析指引） | `…若有評分規準，請依每題專屬 0..N 評分指引填寫。` | `…若有評分規準，請依每題專屬 2 / 1 / 0 評分指引填寫。` |
| 社會領域 L1170（子題產生器） | 整行 | **區塊** |
| 自然科學 L216（舊版模板） | `- Constructed response：必須附 `評分規準`，使用 2 / 1 / 0 / 0X，並提供學生作答實例。` | `- Constructed response：必須附 `評分規準`，使用 2 / 1 / 0。` |
| 自然科學 L828（子題產生器） | 整行 | **區塊**（L827 的 `Complex multiple-choice` 行不動） |
| 社會領域驗證 L36 | `   - 開放式建構反應題採每題專屬評分指引，分數使用 0..N 並允許部分給分；` | `   - 開放式建構反應題採每題專屬評分指引，固定使用 2 / 1 / 0 三級；` |
| 社會領域驗證 L37 | `   - 每一分數級距應有 1-2 個學生作答實例，包含正確與錯誤示例。` | 刪除（數量由 D3 的 hook 負責） |
| `_ss_rubric_scale_check_hook` 訊息 | `…必須使用每題專屬 0..N 評分指引` | `…必須使用每題專屬 2 / 1 / 0 評分指引` |
| 兩科 corrector `_CORRECTION_SYSTEM_PROMPT_CORE` | — | 在「若問題在小題答案或評分規準…」原則之後加一行「修改開放式建構反應題的 `評分規準` 時，必須遵守下列規則：」，接著放**區塊** |

保留「每題專屬評分指引」字樣：既有測試斷言它存在，而且它不牴觸新規則。

### D3. 形狀檢核

共用純函式 `check_open_response_rubric_shape(subquestions, *, in_scope) -> list[str]`，對每個 `in_scope(小題)` 為真的小題依序檢查兩件事：

1. **級距集合。** 去除空白後，code 必須恰為 `2`、`1`、`0` 各一個。
2. **實例數。** 對存在的 2 / 1 / 0 級距比對 `EXPECTED_EXAMPLE_COUNTS`，空白字串不算數；空白字串另報一項。

級距集合不符時，仍逐一報告存在的 2 / 1 / 0 級距的數量問題，讓 corrector 一次補齊。

兩個 hook 登錄方式：

- `_ss_rubric_shape_check_hook` 登錄在 `_SS_POST_VERIFY_HOOKS`，排在 `_ss_rubric_scale_check_hook` 之後。`in_scope` = 小題 `題型` 為 `開放式建構反應題`，且 `認知歷程` 非空。
- `_ns_rubric_shape_check_hook` 登錄在 `_NS_POST_VERIFY_HOOKS`，排在 `_ns_code_check_hook` 之後。`in_scope` = 小題 `題型` 為 `Constructed response`。

有問題時，以 `details.rstrip() + "\n\n[評分規準形狀檢核] " + "；".join(issues)` 附加，並設 `passed=False`，與既有 hook 的寫法一致。issue 的措辭就是 corrector 的修正指引（#651 的耦合），固定如下：

| 情況 | 訊息 |
|---|---|
| 級距集合 | `第{n}題：評分規準級距必須恰為 2 / 1 / 0 各一級（目前為 {codes}）` |
| [2] 數量 | `第{n}題 [2] 級距需要 1 個學生作答實例（目前 {k} 個）：本小題完整走完推理的學生作答原文` |
| [1] 數量 | `第{n}題 [1] 級距需要 2 個學生作答實例（目前 {k} 個）：第一個是 [2] 實例的最小對照，第二個呈現另一種缺口` |
| [0] 數量 | `第{n}題 [0] 級距需要 1 個學生作答實例（目前 {k} 個）：本小題最可能引出的錯誤觀念或錯誤方向` |
| 空白實例 | `第{n}題 [{c}] 級距有空白的學生作答實例` |

- **為何 fail 而非 annotate：** #653 Q7 已定案。與 `0X` 的形狀失敗先例一致；補一則實例對 corrector 輕而易舉，不會白白耗掉重試次數。
- **替代方案：** 只附註、切分（空級距 fail、數量差 annotate）、只靠 prompt。三者都已由業主否決。

### D4. 保留 `0X` hook，只改訊息

帶 `0X` 的社會領域新紀錄會同時得到 `[評分規準檢核]` 與 `[評分規準形狀檢核]` 兩句。兩句指引一致（移除 `0X`、恰為 2 / 1 / 0），所以不合併，以免改動 `0X` hook 的既有測試契約。

### D5. 題型依小題判定

`題型` 值可能是 enum 或字串，比較時取 `getattr(t, "value", t)`。不看題組的 `題型`，也不看 few-shot 資料夾（#651 的 MEMORY.md 陷阱：資料夾以題組標題題型命名，混有其他題型的小題）。

### D6. 自然科學全數檢核

自然科學沒有世代標記，業主於 2026-09-26 選擇全數檢核。

- **替代方案：以 `0X` 作為舊版標記。** 只能部分保護（沒有 `0X` 的舊紀錄照樣失敗），還會放過錯誤產出 `0X` 的新紀錄。
- **替代方案：延後。** 把自然科學排除在 hook 外，另開 map 票；業主未選。

### D7. 詞彙表隨規則落地

Map 延後寫入 `CONTEXT.md` 的理由是共用工作樹有另一個 session 未提交的變更；本變更的 worktree 以 staging 為基準且乾淨，該理由不適用。四個詞條（定義已在 map 與 #653 定案）：

```
**評分規準**:
The scoring guide attached to a 小題: its levels, each with a 規準說明 and 學生作答實例.
_Avoid_: rubric, scoring guide, 評分標準

**計數式規準**:
A 評分規準 whose levels are distinguished by how many things the student produced rather than
by what the item claims to measure.
_Avoid_: counting rubric

**學生作答實例**:
A sample answer to one 小題, written as a student would write it, attached to one level of its
評分規準 so a teacher can see what that level looks like. Never a description of an answer.
_Avoid_: 示例, 範例答案, sample answer

**最小對照**:
A [1] 學生作答實例 that makes the same claim, with the same number of points, as the [2] example,
and differs only in that its reasoning does not close the chain.
_Avoid_: 對照組 (reserved for experimental design)
```

### D8. 文件同步

`docs/ADDING_SAMPLES.md` 的欄位表（L250）、題型說明（L158）與開放式範例（L205-215）改為 2 / 1 / 0 與 1 / 2 / 1；範例本身也要符合區塊（學生口吻、最小對照、不用 `0X`、不用「不知道」）。這份文件是人工新增樣本以及 C4 改寫時會對照的依據。`schema_parameters.csv` 第 8 列只改說明欄，題型值不變。

## Risks / Trade-offs

- **[風險] few-shot 語料尚未改寫**（C4 待 #661），仍示範空實例（185 筆中 168 筆），生成首稿很可能大量觸發形狀檢核，增加修正回合與延遲。
  → 區塊明寫固定數量；落地後以小樣本量測首稿失敗率（tasks 6.2）；語料改寫後應會下降。
- **[風險] corrector 未能補齊，用完重試仍失敗。**
  → issue 措辭逐項指名缺的實例種類；#651 抽查中 corrector 在收到 `details` 後 3 次都修好規準。
- **[風險] #859 或 #650 改動【判準】或【注意】。**
  → 區塊是單一常數：先改 spec 再改常數，apply 前確認兩票狀態（tasks 1.1）。
- **[風險] 自然科學舊紀錄在人工審題修正時規準被改寫，超出教師本次的修改。**
  → 存成 parent-linked 新版本，原紀錄保留（C11）；業主已接受。
- **[取捨] 帶 `0X` 的社會領域新紀錄得到兩句訊息。** 可接受，因為指引一致（D4）。
- **[限制] hook 不判斷內容，模型仍可能寫出敘述式實例或空泛規準。**
  → 由 #860 量測後決定是否加 LLM 準則。

## Migration Plan

沒有資料遷移，部署即生效。回滾就是 revert：prompt 與 hook 都沒有狀態；新紀錄的 2 / 1 / 0 級距在舊版照樣可讀，因為 `RubricEntry.code` 是 opaque 字串。

## Open Questions

- 首稿形狀檢核失敗率高到多少，才值得重新檢討 fail 語意？這不影響本次的 spec 或做法，落地量測後再定。
