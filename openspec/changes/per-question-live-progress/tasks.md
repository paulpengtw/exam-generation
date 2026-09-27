## 1. 契約型別與固定身分

- [ ] 1.1 在 `src/common/generation_events.py` 與 `server/generate/event_protocol.py` 建立 immutable context、manifest、versioned snapshot、terminal 及各事件家族的型別／驗證器；以有效／缺欄位／身分矛盾範例驗證 `context.content_revision` 和 terminal 欄位相容關係，確認題目 payload 不含 envelope。
- [ ] 1.2 在 `server/generate/routes.py` 加入生成專用 `stream_version=2` 受理檢查與 426 字串 detail／code／supported versions；用 route 測試確認缺少與不支援版本均零派工、零模型呼叫、無 started，且原認證、完整參數門檻及 modification 介面保持有效。
- [ ] 1.3 在 service 的 planner／worker 啟動前建立 run UUID 與整批固定 manifest，並傳入三科生成入口；以同科同秒重送、無 GenerationLog 的直接 seam 和草稿前失敗測試驗證身分唯一、原 index 固定及舊檔案不更名。
- [ ] 1.4 將 shared generation core 的 plan/config 路由改為固定位置，覆寫模型小題 id／序號，保留 correction、image filenames 與 `_plan_index` 對應；用任意模型序號、中間 slot 失敗及重試測試驗證留下 1、3 而非重編成 1、2，flat math 不建立小題。

## 2. 統一發送與工作／呼叫脈絡

- [ ] 2.1 在 service／marshalling 建立單一 generation publisher，於同一排送點配置 run-wide event_seq 並入列，涵蓋原本直接 yield 的事件；用並行 barrier 測試確認 started 為 seq 1 且先於 planner、所有家族使用 envelope、seq 與發送順序一致。
- [ ] 2.2 在 shared core 的文本、小題、整個 slot 重試與 batch planner 建立 operation scope，跨 executor 明確傳遞 immutable context 與 supersedes 關係；以 A/B 同角色並行及舊 operation 遲到測試驗證無跨題／跨工作配對。
- [ ] 2.3 在 `src/llm_client.py` 的實際應用層 dispatch 配置 call_id，傳遞 request、thinking、content、response、可觀測 failure 及 retry_of_call_id；使用 fake provider 驗證 JSON 重送換 call 不換 operation、整個 slot 重做換 operation，且不為 SDK 隱藏 retry 虛構呼叫。
- [ ] 2.4 將三科 verify／correct／reverify、HTML／image provider、fact-check 及各 trail callback 接上所屬 scope；用各科 fake client／renderer 覆蓋表驗證所有嵌套事件都有適用身分，無圖片／skip-verify 路徑不產生虛構工作。
- [ ] 2.5 讓 `ExchangeRecorder` 對有 context 的事件按 run/call 配對，並保留 legacy/modification 路徑及記錄失敗隔離；以交錯同 agent 呼叫和持久化失敗測試驗證 exchanges 不串題、生成不受記錄失敗阻斷。
- [ ] 2.6 分離 transport envelope 與 result persistence sidecars，更新序列化接點但保留 verification／figure／reference records 的既有儲存方式；讀回 GenerationRecord 與 history detail，驗證只有完整題目進入 question JSON、既有歷程欄位未遺失。

## 3. 內容快照與審題版本

- [ ] 3.1 實作每題原子 snapshot ledger，從 revision 1 記錄不可變內容及明確／已採用的必要圖片位置；用並行提交、同版重送及 queued object mutation 測試驗證同版同內容，transport encoding／review／export 不換版，實際圖像變動會換版。
- [ ] 3.2 在文本 shell、各固定小題完成及現有圖片／修正 callback 提交完整快照，再發出帶 context.content_revision 的 question_update；以所有小題失敗和部分小題成功測試確認文本仍為可用題組、已收到的草稿不因下一步失敗消失。
- [ ] 3.3 將 verifier 實際輸入綁定 revision，讓 review／correction trail 明示目標版本並由 ledger 管理修正後的新內容；以改圖不改字、修正後再驗證、明確 skip 測試驗證不沿用舊版結論，未變內容升 final 不增版。

## 4. 權威終止與批次收尾

- [ ] 4.1 在每題正常返回、最終失敗及實際確認取消出口封存唯一 question_terminal，建立 fixed-slot expected／delivered／missing、final 與 review 的一致性檢查；用 complete、partial、none、unknown、文本 only、缺圖及 failed-review 範例驗證原因與版本正確，renderer 模式不自行要求圖片。
- [ ] 4.2 拒絕 terminal 封存後的新工作／新 revision，允許同份摘要及已宣告 final 重送；以 terminal 前後交錯、no-final 卻宣稱 complete、無匹配 final 的 draft review 測試驗證摘要不可改寫且不偽造結論。
- [ ] 4.3 修正 consumer 遇任意 error 即全批 break 的路徑，分開可重試、逐題及 batch fatal 錯誤，settled workers 的事件排完才送 done；用 A 失敗而 B 持續成功及草稿前 batch failure 測試驗證 siblings 內容與 terminal 都可送達。
- [ ] 4.4 保留 disconnect／abort 的實際清理語意並停止把它推定為取消成功；使用現有 cancellation／service 測試注入斷線與清理例外，驗證 futures、renderer／recorder 收尾與可知 terminal 事實，不新增恢復或自動重送。

## 5. 前端 decoder 與證據 reducer

- [x] 5.1 抽出 `web/src/lib/generationStream.ts` 的 awaiting-start／v2／legacy／unsupported decoder，讓 useGenerate 請求帶 v2 並隔離連線世代；以完整／缺失／重複 manifest、426、未知版本及舊 callback 測試驗證只有有效 started 可建立卡位，未知版本停止接收且無 resubmit。
- [ ] 5.2 建立按 run/question/revision 收納的內容、final receipt、terminal 與 review 狀態，分別衍生 processing／termination／delivery／review；測試 B 先 final、舊 revision 晚到、terminal 先到／缺 final、final 缺 terminal，確認無跨卡覆蓋或錯版審題。
- [ ] 5.3 以 operation 集合與 call/channel 紀錄衍生活動和文字，不把 snapshot phase 當活動證據；用並行子題／圖片、同 purpose 不同 call、superseded end 遲到與空 active set 測試驗證工作不誤結束、文字不混接。
- [x] 5.4 實作 seq fingerprint 去重及從首個 gap 起算的有界 buffer；用 fake clock 分別命中 2 秒、256 筆、4 MiB，並測試界內補齊、重送不膨脹、按序大正文、未知種類占序號與 EOF 缺口，驗證活動只依可靠證據推進。
- [x] 5.5 實作永久活動降級後的獨立正文／terminal 驗證與衝突隔離；測試較小未見 seq、同 seq 不同資料、同版不同內容、矛盾 terminal／review、mixed raw event，驗證保留正文、明示原因、只降級受影響結論且不自動恢復完整活動。
- [x] 5.6 建立 legacy adapter，按連線與 opaque id 收納，只接受一致的明確 index 對照；用 A 有 index 草稿、B 無 index final、重複 final 與後到 mapping 測試驗證原題序未知標示、無憑空 manifest、無 v2 終止推論及無自動重送。

## 6. 教師介面與共用元件

- [ ] 6.1 將 GeneratePage、ProgressLog、QuestionCard 接到同一 normalized selectors，顯示固定卡位與獨立結論／缺項／待收 final；以 A complete、B partial、C failed draft、D final 無 terminal 的元件整合測試驗證「已結束 3/4 題」及「收到最終結果 3 題」，重送不重算，terminal 爭議才減 X。
- [ ] 6.2 以實際 operation 集合呈現生成步驟合計與按需展開，加入 legacy／資訊不完整／原題序未知提示；用多工作並行及百題 fixtures 驗證不強制展開所有 lanes、不顯示未發生步驟，斷線停止無證據動畫且保留內容。
- [x] 6.3 將 generate-v2、generate-legacy、modification profile 在共用 statusbar／card 分開，保留修改資格、圈選 field paths、指示與結果／錯誤歸屬；更新既有 hook/card/statusbar 測試驗證修改流程不需 generation manifest，並核對 ai-working-surfaces 前後整合的規則對照。
- [x] 6.4 為新增狀態及下載文字提供既有語系、可及性與 masking 處理，沿用 reduced-motion、navigation／clear／resubmit guards；以鍵盤操作、減少動態模式、語系切換及遮罩檢查紀錄驗證狀態可讀且題目內容不意外進入遙測。

## 7. JSON 與 ODT 快照匯出

- [x] 7.1 建立 `web/src/utils/exportSnapshot.ts`，同一次點擊原子擷取內容、狀態、revision、時間及可見圖像來源，供單題／整批／既有可下載歷史使用；以匯出期間收到新版測試驗證快照固定、bodyless placeholder 排除、原題序與 legacy 未知順序標記保留。
- [x] 7.2 在 JSON 下載副本附加固定 `_export` 欄位，統一草稿／含草稿檔名；用單題、混合批次與 legacy history 測試驗證物件／陣列形狀、原 id、共同 UTC timestamp、null/unknown 及去除 `_export` 後等於捕捉的原題目，live／stored data 未修改。
- [x] 7.3 讓 ODT 消費同一 snapshot，保留每題草稿標示、處理／完整性／審題區別、原小題序號與缺項；讀回 ZIP XML 驗證只有文本的題組、跳號小題和無 terminal 的 final 均保持正確結構與狀態。
- [x] 7.4 從 FigureRenderer 同源輸出凍結 SVG／HTML 預覽及其樣式／資產，實作 export-only rasterization；用真實瀏覽器測試 table、geometry、scenario 的無 PNG 預覽，驗證 ODT 對應位置含捕捉圖像、期間換圖不混版且無 LLM／image-provider 呼叫。
- [x] 7.5 將逐圖 conversion failure 與整份 ZIP failure 分開，保留同 snapshot 重試及 JSON 下載；注入單圖失敗和 ZIP 失敗，驗證前者正確位置顯示「匯出缺圖／預覽轉換失敗」、後者不提供壞檔、兩者都不改生成完整性且不重跑生成。
- [x] 7.6 開啟已收到 draft 的單題及整批 JSON／ODT actions，既有實際 PNG 使用正確草稿檔名；更新 QuestionCard／GeneratePage 的下載測試，驗證 legacy draft 也可下載、preview 不偽裝成已生成 PNG、下載不擴大人工審題修正資格。

## 8. 發布受理與排空控制

- [ ] 8.1 新增獨立於 frontend/backend rollback unit 的 admission gateway 與受控 paused/open 狀態，調整 Compose 和 nginx 使公開 API 及舊分頁都經此入口、backend 僅私網可達；以部署路由測試驗證 pause 回可讀 503、零新工作、既有 SSE 可繼續，單邊回滾不移除 gate。
- [ ] 8.2 加入受限制的每 instance/process drain telemetry，覆蓋 active runs/workers、open streams、queued events 及 disconnect 後 futures／renderer／recorder 清理；以工作 barrier 與例外測試驗證收尾前不回報零、finally 不洩漏計數，且 endpoint 不暴露題目或 prompt。
- [ ] 8.3 建立列舉全部 process 並逐一驗證的 pause/drain/compatibility/reopen 控制腳本，未知、過期、無法連線或非零證據皆維持關閉；以兩後端加多 process 演練驗證不把隨機 LB 探測當全覆蓋、不以 timeout／pipeline_end／空瀏覽器替代排空。
- [ ] 8.4 為首次接管未具 telemetry 的環境建立相容準備 checkpoint 與可執行的正面 quiescence 驗收流程；交付既有環境／全新 closed-gate 環境兩份演練紀錄，驗證沒有平台工作盤點證據時阻止切換、不靠強制中斷偽造排空。
- [ ] 8.5 實作前端單邊、後端單邊不相容 rollback 的控制步驟與檢查；在隔離環境驗證 gate 保持關閉至相容組合恢復、C0 重整仍為 C0 不算恢復、已開 C1 不被強制清空，意外舊串流依 legacy 降級。

## 9. 條件式 ADR 與操作文件

- [x] 9.1 交付新的條件式取代 ADR，於 ADR 0009 保留 legacy／不可歸屬限制並加入連結，保留 ADR 0016 的題目與完整歷程分離；以文件對照確認只有契約與發布驗收通過才適用例外，OpenSpec sync 本身不等於生效。
- [x] 9.2 更新事件契約文件、FLOW／相關執行說明及 DEPLOYMENT runbook，記錄四組相容矩陣、HTTP 426、buffer 界線、snapshot／terminal schema、`_export` 額外欄位相容說明、全入口 inventory 與 pause/drain/rollback 指令；用本 change 的 requirements 清單逐項核對並驗證範例可由契約型別解析。
- [x] 9.3 在 CONTEXT.md 實際補入草稿、處理狀態、終止原因、交付完整性、審題結果等已決議教師術語，技術欄位留在協定文件；核對既有詞彙及 #731／#732／#733 的決議，交付可見詞條而非沿用「先前已改」的假設。

## 10. 跨層驗收與交接

- [x] 10.1 從真實 server publisher 搭配 fake subject/provider 輸出可重現 fixtures，供前端與匯出測試直接重用；以數學單一題／題組、社會、自然、retry／partial／文本 only 執行驗證 envelope、卡位、revision、terminal、缺項與下載一致，無付費模型依賴。
- [x] 10.2 用同一 A/B 交錯案例完成 C0/S0、C0/S1、C1/S0、C1/S1 相容驗收，另以測試 transport 注入重送、缺口、衝突及 terminal/final 反向到達；保存斷言與 UI 證據，明列 C0/S0 原有缺陷、C0/S1 零派工及 C1 的可信內容保留。
- [x] 10.3 執行變更涵蓋的 backend tests、全量預抽 guards、web tests、lint 與 build，遵守最多 2–3 個記憶體較重測試 lane 及可用時的 `choom -n 500 --`；交付命令與結果紀錄，失敗或跳過的必要驗收有明確處理，不以單一 build 取代跨層驗證。
- [ ] 10.4 完成教師可見狀態／草稿 ODT／預覽圖片的瀏覽器驗收，以及兩後端 pause→drain→switch→verify→reopen 和兩種 rollback 演練；由實作者整理證據、技術 reviewer 核對門檻、教師確認狀態含義、發布操作者記錄入口與版本／排空證據，形成可審閱的發布交接包。
