## Why

生成進度列、ProgressLog 與 Agent 狀態各自呈現工作狀態，等待首個事件時缺少清楚的階段文字，且「生成中／產生中」用語不一致。依 [AI 工作中介面採用決議](https://github.com/paulpengtw/exam-generation/issues/726#issuecomment-5650950197)，將原型 A「文字閃光」落實到既有前端介面，讓教師能辨識目前工作與結果。

## What Changes

- 生成進度列使用唯一的文字 shimmer；移除 running 狀態的 `◐`。單題顯示實際生成步驟，等待事件時立即顯示「產生中」，人工審題修正立即顯示「修改中」。
- ProgressLog 與生成進度列共用階段判定及翻譯；前者保留 spinner 狀態行、主控台及 LLM trace。
- AgentStatusPanel 保留原始思考／回應 `<pre>`、100 ms 計時器與合計模式，活動文字窗增加尾端游標；不建立等待中的假 Agent。
- 呼叫結束或 run 終止時停止指示器；保留 terminal failure，避免後續串流結束事件誤顯示成功。
- 引入共用 spinner，替換既有六處重複圖示；狀態、停用條件及操作行為由原有呼叫端控制。
- 採用 AICSS 的兩個 CSS 動畫配方與 MIT 出處，加入集中動態 tokens、減少動態模式及可及性語意；不安裝 AICSS 元件、字型或套件。
- zh-TW 進度列用語改為「產生中」、「審題」、「改題」；內部步驟仍為 verify／correct，英文名詞維持 Generating／Verify／Correct。
- **使用者確認的範圍調整（2026-09-13）**：批次僅呈現整批完成數及已收到的題目結果狀態。每題即時階段、後端事件題目識別留給獨立 OpenSpec／wayfinder 工作，不是本變更的前置條件。

## Capabilities

### New Capabilities

- `ai-working-surfaces`: 事件驅動的工作中狀態、前端批次呈現、Agent 游標、共用指示器，以及語言、動態與遮罩規則。

### Modified Capabilities

無。現有 `openspec/specs/` 尚未登錄 capability；本規格記錄既有介面的新增行為契約。

## Impact

- 實作基準為 `origin/staging`（本次檢視 `bc4932a`），原型參考為 `prototype/726-ai-working-surfaces` 的 `be250dd`；目前工作目錄在 `main`，本次只寫 OpenSpec 文件，不合併原型或 staging 的其他變更。
- 前端範圍：`GenerationStatusBar`、`ProgressLog`、`AgentStatusPanel`、`GeneratePage`、`QuestionCard` 的人工審題修正進度列，以及六處 spinner 呼叫端；新增 `web/src/motion/` 和共用進度判定模組，更新 i18n、啟動及測試設定。
- 不修改後端、SSE payload、生成／驗證模型、資料庫、題目內容、發送前確認 payload 或既有停用與導覽保護。
- 遵守 ADR 0004／0005 的 Sentry 遮罩、ADR 0009 的批次不可歸屬限制、ADR 0010 的送出停用規則。這次不包含 #720 的全站操作回饋、匯出重試、路由／對話框動態，亦不包含 #725 的完整送出交接動畫或 #727 的另一輪原型評選。
