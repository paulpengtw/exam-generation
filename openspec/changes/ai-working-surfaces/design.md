## Context

動機與範圍見 [proposal.md](proposal.md)，驗收契約見 [ai-working-surfaces/spec.md](specs/ai-working-surfaces/spec.md)。本變更跨越數個狀態元件、事件判定與遮罩邊界，因此保留設計文件。

本次只讀檢視的正式程式基準為 `origin/staging@bc4932a`。工作目錄 `main@2795d7c` 較舊，例如尚無 `useModificationRun.ts`；套用時應在 staging 基礎上實作，不能為了補足該差異把整個原型分支合併進來。原型 `be250dd` 僅新增 `web/prototypes/726-ai-working-surfaces/index.html`，其模擬時間線與批次假資料不是正式事件契約。

觀察到的實作接點：

| 位置 | 現有行為及本次接點 |
|---|---|
| `web/src/components/GenerationStatusBar.tsx` | 內含生成／修改 breadcrumb 與階段判定；單題等待時可能只剩全為 pending 的 breadcrumb，手機隱藏非 live 步驟後會沒有狀態文字。批次只顯示完成數。 |
| `web/src/pages/GeneratePage.tsx` | 已有 `runState`、`requestedTotal`、`results.length`、submitted／announced 子題數與 `llmCalls`，足以組合單題狀態。 |
| `web/src/components/ProgressLog.tsx` | 狀態行固定用 `progress.generating`，未反映生成步驟；主控台與 trace 各有自己的顯示與捲動。 |
| `web/src/hooks/useGenerate.ts` | `LlmCallEvent` 含 stage／request／thinking／content／response；stage 只有 agent、stage、status、ts 等，沒有題目識別。Agent 回應完成時若 stage 尚未結束，lane 仍可能是 running。 |
| `web/src/components/AgentStatusPanel.tsx` | 已有合計模式與局部 100 ms DOM 計時器；原始文字窗、stage history 與 error message 保留。 |
| `web/src/hooks/useModificationRun.ts`、`QuestionCard.tsx` | 修改在 POST admission 前就設 running，接著接 SSE；QuestionCard 掛載的也是固定底部 GenerationStatusBar，並非另一個卡片內進度列。 |
| `web/src/main.tsx`、`index.css`、`test/setup.ts` | 尚無 motion tokens；CSS 只有 Tailwind import。六個 spinner 分散於 LoginPage、VerifyPage、ParamForm、CoreQuestionPicker、ProgressLog、AgentStatusPanel。 |

### 決議與出處

- [AI 工作中介面採用決議](https://github.com/paulpengtw/exam-generation/issues/726#issuecomment-5650950197)：採原型 A，僅取兩個 CSS 動畫，指定語言、shimmer 範圍、游標與共用 spinner。
- [操作回饋狀態模型](https://github.com/paulpengtw/exam-generation/issues/723#issuecomment-5647665558)：等待狀態與生成／修改階段。
- [動態 tokens 決議](https://github.com/paulpengtw/exam-generation/issues/725#issuecomment-5650303558)：TS 單一來源、easing 與 reduced-motion 規則。此處只落實工作中介面所需基礎；整站動態及交接動畫仍屬另一範圍。
- AICSS 已直接核對固定 commit `4556a918fd8c9358d42d2b24a3866301b8ea10a2` 的 [ThinkingState CSS](https://github.com/kvnkld/aicss/blob/4556a918fd8c9358d42d2b24a3866301b8ea10a2/packages/react/src/thinking-state/ThinkingState.module.css)、[StreamingText CSS](https://github.com/kvnkld/aicss/blob/4556a918fd8c9358d42d2b24a3866301b8ea10a2/packages/react/src/streaming-text/StreamingText.module.css) 與 [MIT license](https://github.com/kvnkld/aicss/blob/4556a918fd8c9358d42d2b24a3866301b8ea10a2/LICENSE)。正式配方的 label-shine 有 0–18%／82–100% 停留區間；原型改寫了 sweep，不能誤稱兩者完全相同。

## Goals / Non-Goals

**Goals:**

- 用一個純進度判定接點供狀態元件消費，讓事件、文字與 terminal 狀態不各自推導。
- 讓動畫只負責呈現，保持請求時序、題目資料、全程停用與既有版面接點。
- 建立可供後續操作回饋工作重用的 tokens 和最小指示元件。

**Non-Goals:**

- 不建立整站 action state machine、不重寫 SSE transport、不修正與本次狀態呈現無關的結果排序／持久化問題。
- 不新增 Motion、shadcn/ui、tw-animate-css、AICSS 套件或字型；本次 CSS 指示器不需要它們。若後續全站計畫引入 Motion，須沿用這份 token 來源。
- 不製作假的批次 placeholder QuestionCard，不增加 batch-to-agent 關聯。後續事件識別地圖是獨立工作，見下方另案入口。

## Decisions

### 1. 從進度列抽出純判定，保留既有事件識別

新增 `web/src/lib/runProgress.ts`，將 `GenerationStatusBar` 的 step matching、active step、distinct 子題完成數整理為純函式；輸出包含 run state、phase message key／參數、breadcrumb steps、步驟狀態與批次完成數的呈現資料。翻譯在 render 時使用，避免切換語言需重新啟動事件處理。

輸入沿用既有資料：generation／modification mode、run state、科目、已知題組設定、requested／completed counts、stage events、子題數。`GeneratePage` 組合一次資料後交給進度列與 ProgressLog；人工審題修正從 `useModificationRun` 的 status／events 使用相同判定入口。不使用 timer 決定進度。

判定規則：

1. idle／error／done 優先於 stage 歷史；running 且尚無識別到的階段顯示預設等待文字。acknowledgement、renderer acquisition、planner 等非本文所列生成步驟不會被誤判為文本完成。
2. 生成匹配沿用 `generator + llm_generate`、`sub_generator#N + llm_generate`、`image_agent + render_image`、`verifier + verify`、`corrector + correct`。修改沿用 `modification`、`verify`、`correct` 與現有 retry history。
3. 對單題，選取最新仍 active 的已知步驟；所有 active 步驟結束時，保留最後識別的 phase 文字直到下一步或 terminal。此時可在獨立的狀態文字上 shimmer，已完成的 breadcrumb 項仍是綠色；最多一段 shimmer。
4. `start` 重新開啟相同 worker／step；`end` 或 `error` 結束該次活動。步驟完成不可只依整條時間線位置推定。重試中的 子題 worker 不算完成；submitted 子題數優先於 announced total，未知 total 不猜測。
5. 社會／自然始終使用 grouped steps；數學若確認資料已指定題組則用 grouped steps，否則由實際 `sub_generator#N` 活動轉為 grouped。數學的 flat 路徑保持原有 generate step。`subject === math` 不再是排除 子題 的唯一條件。
6. 批次直接產生 roll-up，不消費 unscoped stage events 推算個別題目階段。QuestionCard 沿用 `phase`／`isFinal`，不加入新 live-phase prop。

替代方案是讓 ProgressLog 複製進度列的判定；這會延續用語與 retry 行為漂移，因此不採用。也不根據草稿 phase 預測下一步，因為「已收到驗證草稿」不能證明目前正在修正。

### 2. Tokens 與動態配方保持獨立、集中

`web/src/motion/tokens.ts` 是單一數值來源，export 冪等的 root 設定函式，由 `main.tsx` 在首次 render 前及 `test/setup.ts` 呼叫。`index.css` 透過 `@theme inline` 暴露對應 utility；實際動畫 CSS 讀取同一組 custom properties。

| Token | 值 | 用途 |
|---|---|---|
| duration.quick | 150 ms | 受影響元件的短狀態切換 |
| duration.standard | 320 ms | 一般狀態轉換，供後續元件重用 |
| duration.slow | 560 ms | 保留上游 token 契約，本次不新增路由動畫 |
| duration.loop | 2250 ms | shimmer 與 reduced-motion pulse |
| ease.signature | cubic-bezier(0.22, 1, 0.36, 1) | 狀態變化 |
| ease.exit | cubic-bezier(0.64, 0, 0.78, 0) | 退出時使用 |
| ease.loop | cubic-bezier(0.25, 0.1, 0.25, 1) | shimmer／pulse |

spinner／caret 採原型的 1000 ms 功能週期，集中列於同一模組的 indicator constants；這不是新增通用 duration palette。spinner 保持 linear，caret 保持 step-end。reduced-motion pulse 使用 loop token，opacity 1→0.6→1，以保留可讀性；這是落實時的細部選擇。

`web/src/motion/aicss.css` 只取上游 `label-shine`、`caret-blink`，依 app 色彩及 tokens 改寫，檔頭記錄 repo、完整 commit、來源檔與 MIT；`LICENSE-aicss.txt` 保留授權全文。採上游有停留的 sweep，原型 A 作為位置與視覺方向參考。其他 spinner／pulse CSS 為 app 自有。`web/index.html` 固定 `data-theme="light"`，不引入 upstream dark-mode CSS，沿用 system font。

替代方案是匯入 registry component 或整套 AICSS；決議已排除，且既有 raw JSON pane 不適合 prose 元件。兩個配方即可達到本次可觀察效果。

### 3. 三個最小呈現元件

在 `web/src/motion/` 建立 `Shimmer`、`Spinner`、`StreamingCaret`。`Shimmer` 是保留文字與結構的 span，只由進度列使用；它不自動加 `sentry-unmask`、不隱藏原文字，也不擁有 timer 或 fetch。`Spinner`、`StreamingCaret` 預設為裝飾用途，`aria-hidden`；呼叫端提供可讀狀態。

替換六處 spinner 時沿用原有尺寸與色彩 variant、載入條件和 accessibility label；尤其 `ParamForm` 的 `resolverLoading` 操作回饋修補屬上層計畫，本次不順帶調整其操作狀態。現有 icon-only VerifyPage 必須仍有 sr-only／status 文字，不因裝飾化而失去可存取名稱。

減少動態使用 `prefers-reduced-motion` CSS：移除 shimmer 的透明 text fill／gradient、改為固定藍字 pulse；spinner 取消 rotation 改 pulse；caret 固定 opacity 1；受影響 transition duration 設為 1 ms 且無平移。偏好可於執行中切換，功能與文字完全不變。

### 4. 游標根據 LLM call，不能只看 lane.status

為 Agent 呈現補足最小串流描述：從最近一次 request 起追蹤最後收到文字的 pane（thinking／content），於 response、該呼叫 stage 的 error／end、terminal run 或 reset 清除。可在既有 `buildAgentLanes` 過程增加 optional `activeStreamingPane`，不更動 server event shape；必要時傳入 run-active 狀態讓 terminal 清除所有 indicators。

只有 single-run lanes 且該 pane 有文字時掛一個 `StreamingCaret`，置於 `<pre>` 內容尾端、文字節點之外。保留原本截取、複製、捲動與 history；`llm_response` 到達即移除 caret，不等待包含它的較長 stage 結束。aggregate lanes 保持既有文字與合計資訊，不增加虛假的單一 worker 游標。

替代方案是 `lane.status === running` 一律畫游標；實際 hook 在 response 完成後仍可能保留 running，會製造仍在輸出的錯覺，因此不採用。

### 5. 語言、終止狀態與 live region

保留 `verify`／`correct` step ids，不改 agent 名稱、紀錄及領域詞彙。`messages.ts` 將 zh-TW `statusbar.running` 改為「產生中」，breadcrumb noun 改「審題／改題」，另增每個 live phase 的兩種語言 message key。EN 保留 noun Verify／Correct，live label 使用 Verifying／Correcting；既有 Agent pane 的英文 Thinking／Response 不變。新的 run phase 不使用 AICSS 的通用 Thinking label。

每個 run 指定一個獨立、可存取的 polite `role="status"` 區域，只放 semantic phase 或 terminal 文字，與 ElapsedTime、原始 panes、trace 分開。ProgressLog 可見同樣文字但不再重複宣告；spinner 也不另產生相同 announcement。計數仍可見，避免把每個 timer tick 放進 live region。

保留既有錯誤來源與顯示；為防止 terminal error 後的 `done` 把本次失敗改成成功，hook 對同一 run 記住 terminal failure，由 reset／下一次 generate 清除。這僅修補 working→terminal 的呈現，不新增後端 retry、timeout、百分比或錯誤分類。停止時對 AgentStatusPanel 傳遞非 active 狀態，讓殘留 stage history 不會繼續顯示 spinner／caret。

### 6. 遮罩維持最窄邊界

沿用 ADR 0004／0005 的 allowlist：固定 app labels 可放 `sentry-unmask`，而 Shimmer 外層、動態計數／時間、reason、整個 pane／console 不加。批次需要一段連續 sweep 時可讓背景套在父 span，但 unmask 只標記內部固定文字；既有 masked counter 不因父 span 而變成可讀。人工審題修正的錯誤原因與 ripple report 保持原樣。

相比對整個動態元件加 `sentry-unmask`，這個做法需要測試 DOM 祖先邊界，但不會擴大錄製內容。

### 7. 批次每題即時階段另案入口

2026-09-13 使用者確認維持 frontend-only；這明確縮小 [AI 工作中介面採用決議](https://github.com/paulpengtw/exam-generation/issues/726#issuecomment-5650950197) 中的 per-card live phase 要求，保留 ADR 0009。`question_update.index` 與 trail 的 `question_id` 可對應已收到的內容，不能回推每個無識別的 `stage` 事件屬於哪一題。

後續獨立變更建議名稱：`per-question-live-progress`。先用 `$wayfinder` 建立獨立決策地圖，待影響範圍與相容性的決策釐清，再用 `$openspec-propose` 產生可實作的完整 artifacts，以「建立可靠的事件歸屬契約，讓每題真實即時階段可以實作」為規劃終點，不把實作混入決策地圖。

已可清楚命名的另案決策：

- **決定事件的題目識別與重試邊界**：採 question id、request-local index 或兩者？哪些 stage／LLM／plan／result／error 事件需攜帶；如何跨 子題 workers、重試與取消傳遞？
- **決定批次各題的生命週期與降級行為**：尚無草稿時是否顯示既有卡片以外的狀態、部分失敗如何呈現、遇到舊版無識別事件如何降級；Agent 合計模式是否仍保留？
- **決定相容性及文件遷移**：串流 rollout、亂序與重複事件驗收、何時修訂 ADR 0009；斷線後的狀態恢復需求是否成立。

這些是獨立地圖的決策問題，不是本次 tasks，也不是預先鎖定的後端設計。既有操作回饋地圖「全站操作回饋與動態設計」（#720）的 frontend-only 邊界不因另案而改寫。

## Risks / Trade-offs

- [staging 與目前 main 差距較大] → apply 使用 staging 基線；只移入本 change 文件，逐檔限制實作範圍。
- [單題階段間有沒有 active stage 的空窗] → 保留最後事件證實的 phase，不以時間模擬進展；不代表這是逐毫秒的後端 telemetry。
- [上層正在規劃同名 tokens／spinner] → 本 change 建立一份最小來源，後續整站工作擴充它，不重新生成平行 tokens。
- [每題即時階段延後] → batch 始終 roll-up，結果 chip 只敘述已收到的快照；另案不阻擋本次。
- [CSS 動畫與文字 masking 無法由 jsdom 完整驗證] → 使用真實瀏覽器驗證 reduced motion、透明 text fill、masking 祖先與窄版可讀性，單元測試驗證語意與狀態。
- [長 run 中重試或 terminal race 讓指示器殘留] → 對 response／stage end／error／done／reset 與 retry 時序寫針對性測試；不使用新增 animation timer 驅動狀態。

## Migration Plan

1. 實作與測試均在 staging 基礎的獨立工作區執行，保留目前已存在的修改與未追蹤文件。
2. 先落地 tokens、純進度判定與最小元件，再接既有 surfaces；介面 props 變更與所有呼叫端在同一前端變更中完成。
3. 執行本地 frontend 單元／互動測試、lint、production build；真實瀏覽器用受控 SSE fixture 檢視無事件等待、單題、batch、修改、重試、錯誤與 reduced motion，無需真實付費 LLM run。
4. 部署時只有 frontend artifact 變更，無 API version、DB migration 或套件升級；回滾該 frontend revision 即還原視覺與判定。
