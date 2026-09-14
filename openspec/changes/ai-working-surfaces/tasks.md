## 1. 共用動態基礎

- [ ] 1.1 在 staging 基礎的獨立工作區承接本 change，確認 `useModificationRun.ts`、現有 breadcrumb 與 Agent 測試接點均存在；以 `git status`、基準 commit 和限定 diff 驗證沒有引入原型／staging 的其他變更。
- [ ] 1.2 新增 `web/src/motion/tokens.ts` 的 duration、easing、indicator constants 與冪等 root 設定函式，接到 `main.tsx`、`test/setup.ts` 及 `index.css` 的 `@theme inline`；以 token 初始化測試確認首次 render 前 CSS variables 已設定、重複設定結果一致。
- [ ] 1.3 新增 `aicss.css`、app 自有 indicator CSS、`Shimmer`、`Spinner`、`StreamingCaret`，依 design 的固定 commit 保留出處與 `LICENSE-aicss.txt`，設定 light theme；檢查授權全文及元件的可讀 fallback，驗證未新增套件或字型依賴。

## 2. 單一進度判定與事件終止

- [ ] 2.1 將 `GenerationStatusBar` 的階段／breadcrumb／distinct 子題完成數抽到 `web/src/lib/runProgress.ts`；以 table-driven 測試覆蓋無事件、非生成事件、文本→子題、未知 total、submitted total 優先、重複 end、worker 重試、optional steps 與 stage gap。
- [ ] 2.2 在同一判定入口支援 flat math、grouped math、社會／自然及 modification mode；以真實 event shape fixtures 驗證 math 題組顯示 子題、flat math 不顯示，以及 修改→驗證→修正→驗證 的順序與重試。
- [ ] 2.3 為 `useGenerate` 的 Agent 呈現增加 LLM call 活動 pane 描述，根據 request／thinking／content／response／stage end／error 清除或切換；hook 測試驗證 response 已完成而 stage 仍 running 時沒有 active caret，並確認不改 server event shape。
- [ ] 2.4 讓同一 run 的 terminal error 不被後續 `done` 覆蓋，於 reset／下一次 generate 清除；以 `useGenerate.test.ts` 覆蓋 error→done、成功 done、reset、新 run 與殘留 running stage，驗證終止後 indicators 不再活動且保留既有錯誤原因。

## 3. 接上既有介面

- [ ] 3.1 `GeneratePage` 組合共用進度資料並交給 `GenerationStatusBar`、`ProgressLog`，進度列移除 running `◐`、只 shimmer 目前 phase；擴充 `GenerationStatusBar.test.tsx`、`GeneratePage.statusbar.test.tsx` 並新增 ProgressLog 測試，驗證等待與階段切換文字一致，窄版也不會空白。
- [ ] 3.2 以 requestedTotal > 1 的 roll-up 呈現批次，保留 Agent 合計模式與現有 QuestionCard `phase`／`isFinal`；以 interleaved batch fixtures 驗證只 final result 增加完成數、不顯示 batch breadcrumb／每題 live chip，既有 draft lifecycle 測試通過。
- [ ] 3.3 將人工審題修正的現有進度列接上共用判定，等待 admission 時立即顯示「修改中」，保持結果與錯誤附屬原 QuestionCard；擴充 `QuestionCard`／modification hook 的既有互動測試，驗證 admission 等待、修正重試及終止。
- [ ] 3.4 在 single-run `AgentStatusPanel` 的 active `<pre>` 尾端加入唯一游標，保留原文字節點、stage history、錯誤及 100 ms 局部計時；Agent 測試驗證 thinking→response→call end、無文字、terminal、aggregate mode，以及文字與 timer 行為不變。
- [ ] 3.5 將 LoginPage、VerifyPage、ParamForm、CoreQuestionPicker、ProgressLog、AgentStatusPanel 的六處 spinner 改為共用元件；逐處確認原尺寸、loading gate、可存取標籤與 disabled 狀態，相關既有互動測試通過，不順帶調整 `resolverLoading` 操作流程。

## 4. 語言、可及性與遮罩

- [ ] 4.1 在 `messages.ts` 加入所有 live phase 的 zh-TW／EN 文案，變更 zh-TW running 與 審題／改題 nouns，維持 internal step ids 與 EN Verify／Correct；i18n 測試驗證兩種語言沒有缺鍵、切換 locale 不重啟 run，Agent pane labels 不被 run phase 翻譯取代。
- [ ] 4.2 為每個 run 設置單一 polite status announcement，將 timer、原始 streams 和 trace 排除，指示圖示使用裝飾語意；整合測試驗證 phase 改變有 announcement、重複可見狀態不重複宣告、icon-only loading 場景仍有可讀文字。
- [ ] 4.3 將 `sentry-unmask` 限於固定 app labels，保持動畫父 wrapper、既有 masked counters、panes、error reasons 的邊界；擴充原 statusbar masking 測試，檢查敏感文字所有祖先皆無新增 unmask，batch shimmer 仍呈現完整文字。

## 5. 整合驗證

- [ ] 5.1 在 `web/` 執行 `npm test`、`npm run lint`、`npm run build`；保留通過結果，特別確認 statusbar、Agent、QuestionCard lifecycle、發送前確認、resubmit／navigation／clear-results guards 及修改流程的回歸測試，依新共用 spinner 語意更新僅綁定舊 class 的斷言。
- [ ] 5.2 使用真實瀏覽器與受控 API／SSE fixtures 驗證單題等待、grouped／flat math、社會／自然、交错 batch、修改、重試及 terminal failure；在桌面與手機寬度、zh-TW／EN、normal／reduced motion（含執行中切換）逐項檢視，保存短錄影或截圖及結果紀錄，確認沒有假進度、未停止的動畫或空白文字。
- [ ] 5.3 核對最終 diff 僅包含本次前端狀態呈現及測試，確認沒有 backend／SSE schema／DB／依賴升級、原型切換器或批次每題階段實作；以 `openspec validate ai-working-surfaces --strict --no-interactive` 及規格 scenario 對照紀錄完成驗收。
