## Why

開放式建構反應題（社會領域 `開放式建構反應題`、自然科學 `Constructed response`）的 `評分規準`，現行 prompt 只規定**形狀**：級距 0..N 或 2 / 1 / 0 / 0X，每一級附 1-2 個學生作答實例。級距**依據什麼**區分則完全沒有規定。結果是語料與生成都滑向**計數式規準**：依學生列舉幾項給分，把開放題變成有部分給分的複選題。Wayfinder map [評分規準 must measure reasoning, not count answers](https://github.com/paulpengtw/exam-generation/issues/646) 已經定案三件事：規則文字（[Draft the open-response 評分規準 rule text](https://github.com/paulpengtw/exam-generation/issues/649)）、驗證方式（[Can the 驗證模型 reliably detect a 計數式規準?](https://github.com/paulpengtw/exam-generation/issues/651)），以及學生作答實例規則（[What must 學生作答實例 demonstrate under the 0/1/2 axis?](https://github.com/paulpengtw/exam-generation/issues/653#issuecomment-5844982892)）。本變更把其中「prompt 規則＋確定性級距／實例數檢核」落到程式。

## What Changes

- **完整規則區塊只進會寫或改規準的四處。** 兩科子題產生器與兩科 corrector 都注入同一份逐字相同的開放式 `評分規準` 規則區塊，內容以 #653 resolution 的版本為準，取代 #649 的版本：2 / 1 / 0 三級、推理鏈完整度軸線，以及【禁止】【判準】【注意】【具體性】【學生作答實例】五個條款。
- **BREAKING（生成輸出形狀）：級距統一。** 開放式小題的級距從 0..N（社會領域）及 2 / 1 / 0 / 0X（自然科學）統一為 **2 / 1 / 0**。每一級的學生作答實例由「1-2 個」改為**固定數量**：[2] 一個、[1] 兩個、[0] 一個。實例必須是學生口吻的作答原文；第一個 [1] 實例是 [2] 實例的**最小對照**。
- **其他七處只修級距，並刪除實例條款。** 文本生成器與舊版 system prompt 的級距語句改為 2 / 1 / 0，並**刪除**「每一分數級距附 1-2 個學生作答實例」條款；這些 prompt 不寫規準。
- **社會領域驗證模型 prompt。** 刪除「每一分數級距應有 1-2 個學生作答實例」，並把級距語句改為 2 / 1 / 0。`_ss_rubric_scale_check_hook` 的退回訊息也同步改為 2 / 1 / 0。
- **新增確定性 post-verify hook（兩科）。** 開放式小題的 `評分規準` 必須恰為 2 / 1 / 0 各一級，實例數依序為 1 / 2 / 1，且每則非空。不符即 `passed=False`；`details` 指名小題、級距、應有與實有數量，以及缺的是哪一種實例，這段文字就是 corrector 的修正指引。
  - 社會領域沿用既有 `0X` hook 的「有 認知歷程 才檢核」門檻，舊版紀錄不動。
  - 自然科學沒有世代標記，因此**全數檢核**（業主於 2026-09-26 決定）：舊紀錄經人工審題修正重新驗證時，會被升級成新的 parent-linked 版本。
- **選擇題與 `Complex multiple-choice` 的計分語句逐字不動**（C3）。
- **文件同步。** `docs/ADDING_SAMPLES.md` 的範例與欄位說明，以及 `data/social_studies/curriculum/schema_parameters.csv` 的題型說明，同步為 2 / 1 / 0 與 1 / 2 / 1。

## Capabilities

### New Capabilities

- `open-response-rubric`：開放式建構反應題 `評分規準` 的生成規則（級距、軸線、反計數、具體性、學生作答實例）、規則的注入位置，以及確定性的級距與實例數檢核。

### Modified Capabilities

無。現有 `openspec/specs/` 的四個 capability（生成事件協定、發送控制、每題即時進度、題目快照匯出）都不涉及評分規準。

## Impact

- **實作基準。** `origin/staging`，本次檢視 `e1014bf`。本變更文件寫在 worktree `exam-generation-rubric-spec` 的分支 `spec/open-response-rubric-rule`；主工作目錄仍有另一個 session 未提交的 `CONTEXT.md` 變更，本次不動。
- **程式範圍。**
  - Prompt 常數：`src/social_studies/context_builder.py`、`src/natural_sciences/context_builder.py`、`src/social_studies/corrector.py`、`src/natural_sciences/corrector.py`、`src/social_studies/verifier.py`。
  - Hook 註冊：`_SS_POST_VERIFY_HOOKS`、`_NS_POST_VERIFY_HOOKS`，新增一個共用的檢核模組。
  - 測試：更新 `tests/test_paper_rescore_retirement.py` 中釘住舊字串的斷言，以及 `tests/test_natural_sciences_verifier.py` 的開放式題 fixture。
- **不變。**
  - `RubricEntry` schema：`code` 仍是 opaque string，舊碼照常可讀。
  - 前端顯示：`useGenerate.ts` 已把級距當 opaque 文字呈現。
  - 資料庫、SSE、`generation_records` 結構。
- **不在本變更。**
  - 【具體性】與實例判斷條件（擬答、最小對照、本題、合理 [0]）的 LLM 驗證準則：待 [Can the 驗證模型 reliably judge 【具體性】 and the 學生作答實例 constraints?](https://github.com/paulpengtw/exam-generation/issues/860) 量測。
  - #651 定案的計數檢核 LLM 準則：另案實作。
  - few-shot 語料改寫（C4）：待 [統一 few-shot 語料的 rubric schema](https://github.com/paulpengtw/exam-generation/issues/661)。
  - 既有紀錄的補救（remediation）：[Design the stored-record remediation run](https://github.com/paulpengtw/exam-generation/issues/652)。
  - 誘答分析。
- **尚未定案、可能改動規則文字的票。** 實作前須先確認兩張票的狀態；若它們修改了規則區塊，先更新本變更的 spec 再落地。
  - [Does a set framed only by the figure or table count as 事前框定?](https://github.com/paulpengtw/exam-generation/issues/859) 可能為【判準】新增第三條路徑。
  - [Where is the boundary of the counting-stem ban?](https://github.com/paulpengtw/exam-generation/issues/650) 可能改動【注意】或題幹規則。
