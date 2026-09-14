## Why

批次工作會交錯執行，但目前生成步驟與 LLM 事件沒有題目身分，final 又按到達順序對位；教師無法可靠分辨哪題正在生成、已結束、部分交付或狀態未知。已完成的決策地圖確立跨三科的身分、生命週期、匯出及相容性契約，現在將它們轉成可實作、可驗收的規格。

## What Changes

- **BREAKING**：新生成 HTTP 請求要求 `stream_version=2`，缺少或不支援者在派工前收到 HTTP 426 與可讀的更新提示；新版 SSE 使用 `{context, payload}`，不向舊分頁提供新生成的舊格式串流。
- 生成前固定 run、題目與原題序，小題由程式固定身分；所有活動按 operation／call 識別，每批事件按 `event_seq` 去重、排序，內容按 `content_revision` 配對。
- 以不可改寫的 `question_terminal` 分開表達終止原因、是否有 final、完整性／缺項及對應版本的審題結果；單題失敗不終止兄弟題。
- 題目卡片維持固定位置，顯示實際活動集合；整批分列「已結束 X/N」與「收到最終結果 Y」。legacy、缺口及衝突輸入保留可信結果並明示未知，不推測歸屬。
- 草稿及 final 均可單題／整批匯出。JSON 保留原物件／陣列及 id，只在匯出副本附加 `_export`；ODT 捕捉可見預覽，轉換失敗時明示缺圖。
- 發布／回滾採暫停新受理、等待既有批次排空、全實例相容驗證後才恢復。新增 ADR 條件式取代 ADR 0009，legacy 限制仍適用。

## Capabilities

### New Capabilities

- `generation-event-protocol`: 新生成版本門檻、完整事件脈絡、固定身分、內容版本與逐題終止證據。
- `per-question-live-progress`: 逐題活動／結果模型、固定卡片與計數、事件一致性及 legacy 降級。
- `question-snapshot-export`: 單題／整批草稿與 final 的固定快照、JSON 標記、ODT 預覽和失敗處理。
- `generation-release-control`: 獨立受理控制、排空及發布／回滾門檻、條件式 ADR 遷移。

### Modified Capabilities

無；提案建立時解析到的 OpenSpec 主規格清單為空。`ai-working-surfaces` 在另一分支的提案不是此根目錄的既有主規格，不在本次複製或提前同步；其舊計數、禁止批次 live phase 及草稿禁下載規則與本變更的適用邊界，於 design 和情境驗收明列。

## Impact

- 後端：`server/generate/{routes,service,marshalling,exchange_recorder,persistence}.py`、subject registry；`src/llm_client.py`、共享 generation core、三科解析／渲染／驗證及修正接點。保存題目時仍只保存正文，既有歷程維持 sibling 資料。
- 前端：`useGenerate`、共用進度 selector、`GeneratePage`、`QuestionCard`、`GenerationStatusBar`、`ProgressLog`、`AgentStatusPanel`、ODT／圖片匯出與既有歷史卡片。人工審題修正保留自己的舊串流及資格條件。
- 部署：新增不隨應用回滾消失的受理控制與各實例排空證據；現有 Docker Compose 直接暴露 backend port，不能只在前端停用按鈕。更新發布文件及相容性 fixtures。
- 範圍不含背景續跑、重返恢復、durable job、replay、新取消 API、模型／課綱／生成品質政策、全站動態改版或付費生成驗收。此工作不等待 `ai-working-surfaces` 實作。
- 決議依據：[事件識別與重試邊界](https://github.com/paulpengtw/exam-generation/issues/731#issuecomment-5654415277)、[生命週期、降級與草稿匯出](https://github.com/paulpengtw/exam-generation/issues/732#issuecomment-5658279385)、[相容性、發布與 ADR 遷移](https://github.com/paulpengtw/exam-generation/issues/733#issuecomment-5658547217)。同步主規格不代表功能已實作或 ADR 解除條件已生效。
