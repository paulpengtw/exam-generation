## Context

動機見 [proposal.md](proposal.md)。本設計承接已確認的 [事件身分](https://github.com/paulpengtw/exam-generation/issues/731#issuecomment-5654415277)、[生命週期／匯出](https://github.com/paulpengtw/exam-generation/issues/732#issuecomment-5658279385)、[相容性／發布](https://github.com/paulpengtw/exam-generation/issues/733#issuecomment-5658547217) 決議；不是重新選擇其中的產品政策。

查核基準為 `staging@bc4932a4c1117b289a6b74046ae468fdb278f72d`。目前可重用的接點及缺口：

| 接點 | 觀察與設計影響 |
|---|---|
| `server/generate/routes.py` | HTTP route 先建立 GenerationLog，再建立 SSE；舊客戶端能讀字串 detail，因此 426 必須在派工前返回該形狀。`_format_sse_event` 也是需要避免影響 modification 的共用邊界。 |
| `service.py`、`marshalling.py` | worker 共用 queue；observer／pipeline／update／trail 各自入列，部分事件直接 yield。result 的 data 同時用於 persistence。需統一生成事件發送順序，但不得把外層存成 question_json。 |
| `src/common/generation_core.py` | 文本 shell 先解析，小題並行；目前用模型序號取配置、結果收齊才發第一個 draft。需以 plan position 固定身分，讓文本 shell 與逐步完成的小題能成為受控快照。 |
| 三科 CLI／corrector／renderer 接點 | 數學單一題不走題組 core；三科都要傳遞身分與版本。社會／自然既有 `_plan_index`、渲染檔名及 correction freeze 不能因移除中間小題而錯位。 |
| `src/llm_client.py`、`ExchangeRecorder` | generate_json 的 JSON 重送與小題重做是不同邊界；recorders 目前按 agent 配對，v2 要按 call_id，legacy 保留原配對路徑。 |
| `web/src/hooks/useGenerate.ts` | 未驗證 result 形狀即追加，final 按到達序編 index，upsert 用 id 或 index；call 文字只比較 purpose，done 能蓋 error。改為解析 adapter 加 evidence reducer。 |
| `QuestionCard`、`GeneratePage`、`utils/odt.ts` | draft 下載被停用，整批只讀 final results，ODT 只嵌 image_base64。FigureRenderer 已能顯示部分無 PNG 的預覽，應擷取相同凍結輸出。 |
| `docker-compose.yml`、`web/nginx.conf.template` | backend port 直接公開；前端代理與後端獨立回滾，沒有全入口 admission pause 或完整 drain telemetry。新增獨立部署控制是實作範圍。 |

現有 `tests/server/test_generate_service_coverage.py` 可替換 subject registry；`web/src/hooks/useGenerate.test.ts` 可注入真實格式 SSE，`odt.test.ts` 可讀回 ZIP XML。這些可形成不依賴付費模型的跨層 fixtures。

## Goals / Non-Goals

**Goals:**

- 在現有三科生成流程外建立可傳遞的不可變脈絡，讓 sender、記錄器及 UI 使用同一身分與版本。
- 將傳輸模式、活動完整性、題目處理、正文接收和匯出工作分開，允許可信內容在降級後繼續使用。
- 提供完整的受理／排空接點，讓發布條件可驗證，而不是只寫「先部署後端」。

**Non-Goals:**

- 不新增重播儲存、durable run、背景續跑、恢復端點或取消 API；不改模型、retry 次數、課綱、resolver 釘選或生成品質政策。
- 不將 v2 強制套到人工審題修正；不新增一整套 AICSS UI 或重做所有 Agent lanes。
- 不為舊歷史回填不存在的 run／revision／terminal；不因匯出而儲存草稿或回寫題目。後續實作可沿用既有歷程欄位的兼容擴充，這份方案不要求新的 durable-job 資料模型。

## Decisions

### 1. 以生成專用 adapter 與單一 sender 承載 v2

新增生成事件契約模組（建議 `server/generate/event_protocol.py`）及可跨 CLI/core 使用的輕量 immutable context（建議 `src/common/generation_events.py`）。以明確參數或綁定 immutable context 的 observer 傳過 registry、executor、子 client、render callback 及 trail；不依賴共享的「目前題目」變數，也不假設 thread 自動繼承 context。

HTTP 先驗證 transport version，再進入既有認證、參數完整性與生成受理流程；錯誤仍不得啟動模型。認證規則保持原有要求，未授權請求不因版本檢查而取得 run。run_id 使用已建立的 log UUID；沒有 log 的直接 seam 另分配 UUID。完整 manifest 在 planner 前生成。

生成專用 publisher 接收帶 immutable context 的業務事件，在同一 event-loop 排送點配置 seq 並入列；started 第一個排入，planner、所有 worker、終止及 done 都經這條路。移除生成路徑直接 yield、worker 私有 seq 或先配 seq 後用另一條入列路徑的競爭。SSE heartbeat comments 不屬業務事件，不消耗 event_seq。

內部 event 保留獨立的 persistence sidecars。保存 result 時明確取 `payload`，既有 verification／figure／reference records 繼續走 sibling 欄位，最後才序列化 `{context,payload}`。modification 仍使用 legacy serializer profile。相比全域替換 marshaller，此作法能避免把既有修改流程一起改壞。

### 2. 固定小題位置，將 operation 與 call 放在真正邊界

在正規化 plan 時用 enumerate 的位置取各小題配置，覆寫模型 `id`／`序號`，公告固定 mapping。成功結果按固定 slot 收納，失敗只留下 missing，不重新編號；解析、corrector、新增內容修補、圖片檔名與卡片 皆使用該 mapping。flat math 使用同一題目脈絡，不產生小題 mapping。

每次文本、小題重做、圖片、驗證、修正工作配置 operation_id。在實際應用層 provider dispatch 配置 call_id，讓 request、thinking、content、response／failure 同源；避免在 generate_json 和其底層 generate 各配一次。JSON 再送維持 operation、換 call；SDK 內部看不到的嘗試不另外發事件。

編碼補充：重做同項工作時，stage start payload 帶 `supersedes_operation_id`；JSON 再送的 request 帶 `retry_of_call_id`。這些是已選重試因果關係的明確序列化，不用 attempt 數字或 seq 猜新舊工作。新 operation 替代舊活動，舊記錄仍保留。不同並行工作不互相 supersede。

`ExchangeRecorder` 對有 context 的事件按 `(run_id, call_id)` 配對；無 context 的 modification/legacy 繼續按原規則，保持現有失敗不阻斷生成的特性。scope 必須覆蓋 batch briefs、HTML/image provider、fact-check 等巢狀呼叫，不只主要子題產生器。

### 3. 以每題 snapshot ledger 固定內容及審題版本

新增每題記憶體 ledger，持有 immutable snapshots、固定 expected slots、明確要求或流程已採用的 required image slots 及目前 revision。所有模型解析結果、文本 shell、小題完成、圖片與修正先經一次原子 snapshot commit，再發 update。複製內容後才入列，不能讓排隊中的事件引用仍在修改的物件。

revision signature 使用實際題目內容及圖像身分：排除 verification／操作性 metadata／匯出標記，保留正文、答案、課綱／題目欄位、chart_spec 及圖像內容；圖像以正規化資產內容計算，不比較 base64 的格式差異。sender 的 seq 與 revision 是不同序列；revision 從 1 開始，question_update／result 的版本固定放在 context.content_revision，不加入題目 payload。相同內容由 draft 升為 final 沿用 revision。

verifier 開始前固定本次輸入 revision，trail 結論帶回該值。corrector 產生不同內容便提交新 revision，舊 verdict 仍在舊版本紀錄。渲染輸出／缺圖狀態屬 ledger 的明確資產事實，renderer 模式本身不新增 required image。

至少在文本 shell 解析後、各小題結果納入後，以及現有 image／corrected／verified callback 提交快照。這讓所有小題失敗時仍保有文本，且已收到草稿可在下一個步驟失敗時匯出。時間點是實作選擇；任何缺欄位草稿仍要保持可識別的題組結構，不能偽造尚無的內容。

### 4. 完成一次執行時封存 terminal，不從 result 反推

worker wrapper 在正常返回、最終例外及實際確認取消的出口完成一份 terminal。`expected`／`delivered`／`missing` 使用固定身分，建議共同 entry 形狀為 `{kind: "subquestion"|"image", question_id, subquestion_id?: string, reason?: string}`；image slot 以題幹或固定小題 id 定位。空陣列表示已知空集合，未知另記 unknown reason，不能混用。

terminal 檢查 `has_final`／final_revision／delivery_status／review revision 的相容關係。有 final 缺必要部分為 partial；無 final 為 none；缺判定證據為 unknown。failed 可以仍有可交付 final；審題未通過也不等於工作失敗。沒有新的取消 UI，只有現有後端邊界實際確認時才能 emit cancelled。

一般路徑提交 final，再排 terminal；接收端仍必須支援反向到達。terminal 封存後禁止該執行再提交新內容。`pipeline.question_end` 可留作日誌，但不參與終止計數。consume loop 不再遇到任何 error 就全批 break；分清 batch fatal 與某題錯誤，所有可繼續 siblings 獨立產出。

保持現有 question persistence 與歷程語意。無新增歷史證據欄位時，歷史檢視使用 legacy/unknown adapter，不承諾重讀就能還原這次 live 狀態。存檔失敗不把另一題的終止改為失敗，亦不阻止正常排送其結果；若自身的實際結果無法建立，明示相應 unknown，而非從 done 補判。

### 5. Frontend 先正規化證據，再衍生顯示

將 `useGenerate` 拆出純粹的 `generationStream` decoder／reducer（建議 `web/src/lib/generationStream.ts`），hook 只處理連線、請求世代及 React 更新。模式為 `awaiting-start`、`v2`、`legacy`、`unsupported`，另有單向的 activity integrity degradation，不以一次混入 raw event 切 parser。

v2 狀態包含 manifest、已見 seq fingerprint、gap buffer、每題 snapshot revisions／final receipt／terminal evidence／conflicts，以及按 operation 和 call 的紀錄。保留已處理 seq 的 compact fingerprint 以發現不同資料重用序號；大量正文不為去重再複製一份。未知 event kinds 在合法 envelope 下占一個已收到 seq，但不產生狀態證據。

第一個缺口啟動單調時計時，累積待處理筆數及 UTF-8 byte 長度；2 秒、256 筆、4 MiB 任一達界即降級。已知同序號重送先去重，不因重送膨脹 pending bytes。正常按序的大 result 可直接驗證處理，不被 pending 上限誤殺。done／EOF 遇缺口立即降級，不等待逾時。

降級後保留 gap 記錄，不宣稱活動已補齊；對可信 manifest 下自足的正文／terminal 單獨驗證，允許較小但未見的 seq 補齊內容。activity／文字流不跨缺口憑空拼成完整輸出，可保留分段與缺口提示。衝突以 question／revision／terminal/review 面向隔離，不採最後到達者；無法定位的活動缺口影響全批 live，但不抹掉獨立可信的 B final。

每題 processing、termination、delivery、review、receipt 分欄。X/Y 由唯一題目集合衍生，不增量計次。`question_terminal` 指定新版本而畫面仍有舊稿時，分開顯示「最終結果待接收」與目前版本；匯出取實際收到版本及對應標記。terminal 爭議從 X 排除；只有 review 爭議不減 X。

legacy adapter 以連線世代＋原始 id 收內容、僅接受明確的 index mapping；unknown index 獨立標示，不用到達序充作原題序。已知無正文的 v2 placeholder 與沒有 manifest 的 legacy 內容清單保持區別。

### 6. 共用 selector 支援三種證據 profile

生成進度列、ProgressLog、QuestionCard 使用同一份 normalized state／selector。生成 v2 的卡片顯示操作集合、原題序與分離結論；Agent 面板以合計及按需展開維持可讀性。無活動回報的 running 不把上一個已結束步驟繼續畫成進行中；缺終止的斷線不保持旋轉動畫。

明確區分 `generate-v2`、`generate-legacy`、`modification` profile，後者不需生成 manifest。保留修改流程原有圈選 field paths、修改指示、資格及結果替換方式。

與 [ai-working-surfaces 的固定版本規格](https://github.com/paulpengtw/exam-generation/blob/7bcb46c0b12b7485612dfbce9ecf1d543db375c7/openspec/changes/ai-working-surfaces/specs/ai-working-surfaces/spec.md) 的衝突處理如下；它不在此 OpenSpec 根的主規格中，因此本次不修改或複製它：

| 既有要求 | 本變更整合規則 |
|---|---|
| final 到達數叫已完成 k/n | v2 改為已結束 X/N＋收到 final Y；legacy 明稱收到的結果／請求總數，不能冒稱已確認終止。 |
| 批次不可 per-card live | 只有已驗證 v2 可顯示；legacy 及受影響降級活動仍保留限制。 |
| draft export 必須 disabled | 由本變更的快照匯出要求明文取代；更新相關測試，不能因共用元件重構又恢復禁用。 |
| gap 間保留最後 phase label | v2 按實際 active set，不能把已結束工作當 active；legacy／modification 沿各自可知證據。 |

若它先合併，重用其 selector／spinner／shimmer；若後合併，保留這些新規格的 profile 邊界。i18n、reduced motion、Sentry masking、既有 navigation／clear／resubmit guards 均維持，這份功能不新增全站動態方案。

### 7. 以匯出 snapshot adapter 保留題目結構

新增 `web/src/utils/exportSnapshot.ts`，統一從 card/batch/history adapter 取得 immutable `ExportSnapshot`。同一 click 只取一次 UTC 時間，複製收到的原題目和狀態，另持有 image sources。JSON 序列化時才加 `_export`；ODT 讀相同 snapshot，不再直接讀會變動的 hook results。原始 ExamQuestion 型別不因匯出而必須包含 `_export`。

`_export` 欄位固定為 format_version、exported_at、is_draft、run_id/index/content_revision、processing_status、termination_reason、delivery_status、review、missing；未知來源 null/unknown。draft／含草稿檔名與 ODT 每題提示由同一 snapshot 決定；只有 shared 文本也保留題組渲染。

預覽用與卡片同源的 `FigureRenderer` 輸出：click 時凍結其渲染結果／所需內嵌樣式與資產，交給 export-only adapter 轉成 PNG bytes，再交給既有 ODT ZIP 封裝。來源優先於後續 live DOM；僅當現成 PNG 與該可見版本相符時直接重用。原生 SVG 以凍結序列化 SVG／canvas rasterization 處理，HTML 型預覽以自含 SVG foreignObject 包覆凍結 DOM 後嘗試 rasterization。這是 export-only 轉換，不觸發 LLM，也不把結果回寫生成圖片。

每個 asset 返回 success 或帶原因的 conversion failure，ODT 在正確固定 slot 位置加入缺圖標記並繼續其他內容。跨來源資產、字型或瀏覽器轉換限制視為真實失敗，不能悄悄略過。整份 ZIP 失敗走獨立錯誤通道。重試保留本次 ExportSnapshot；新點擊另捕捉新版本。此策略不新增套件的預設依賴；瀏覽器實測必須涵蓋現有 table／geometry／scenario preview 類型。

### 8. 獨立 gateway 與每個後端 process 的排空證據

使用獨立於前端和 backend image 發布的生成入口 gateway，保存受控的 paused/open 狀態；deployment scripts 操作這個控制，而不是應用程式 memory flag。其角色只做 admission 和轉送，不儲存、重播或接管生成工作。暫停時新的生成入口回 503 字串 detail，既有 SSE 保持；開放後 S1 本身仍檢查 v2。

在 Compose 提供獨立 gateway service，外部原 API port 指向 gateway，backend 改為私網；frontend 代理指向 gateway。正式環境的公開 API hostname 亦須統一導向此入口，舊 backend public ingress 禁止直接繞過。gateway 的設定／狀態不包含在 frontend/backend 單邊 rollback unit 中。這是已決議全入口控制的具體落點；把前端 nginx 當唯一 gate 會被直接 API 與前端回滾繞過，故不採用。

在後端加入受限制的 internal drain endpoint，回報 instance/process identity、active runs、active workers、open generation streams、queued generation events 及支援協定。使用部署用身份驗證／私網限制，不公開題目內容、prompt 或個人資料。計數從真正受理及工作／排送生命期建立，disconnect 後等待 futures、renderer leases、recorder flush 的部分仍算 active。流程越過例外也必須在 finally 正確釋放計數。

部署控制取得所有待替換 instance/process 的明確 inventory，逐一直接取樣；不能隨機呼叫負載平衡 endpoint 幾次就宣稱涵蓋全部 process。缺失、過期或未知 telemetry 都使 gate 保持關閉。共用 run scopes 在內存即可；此資料不是持久化工作或恢復索引。

先交付 gateway／drain 的相容準備 checkpoint，再進入 v2 切換。初次接管既有未具 telemetry 的環境，必須由部署平台的確實工作盤點或已停止受理且可證明無工作的既有節點建立 quiescence；沒有證據就保持暫停，不以等待若干分鐘取代。文件必須提供這個首次安裝的驗收步驟；正常 v2 發布不得繞過準備 checkpoint。從未啟動過服務的新環境可直接以 closed gate 安裝完整版本。

### 9. 用同一批 fixture 貫穿 sender、UI 與匯出

後端使用 subject registry／fake client／render callbacks，輸出可重現的真實 envelope fixture；前端測試直接重用，而不是另造相似但不相容的資料。故意重排／重送／遺漏只在 test transport adapter 完成。

| 證據集 | 必須核對的結果 |
|---|---|
| C0/S0、C0/S1、C1/S0、C1/S1 同一 A/B 批次 | baseline 限制、426 零派工、legacy 安全收納、新版原位對照。 |
| B 先 final、A retry、舊 operation end 遲到 | 無跨卡覆蓋、無重複 X/Y、call text 不混。 |
| 失敗／partial／skip／文本 only，三科加數學兩種結構 | 正確缺項、無虛構步驟、siblings 繼續。 |
| gap 的三個獨立界線、duplicate/conflict、未知 event、mixed legacy、old run | 有界降級、可信 evidence 保存、矛盾範圍正確。 |
| terminal/final 反向與遺漏、revision mismatch、改圖不改字 | 處理與接收分離、審題不套錯版本。 |
| draft/final batch、可見 preview 無 PNG、轉換途中換圖、單圖／ZIP failure | 不混版、缺圖明示、不回寫生成、不重跑。 |
| 兩後端 drain、direct API、斷線後仍有工作、單邊 rollback | gate 不被繞過、未知不當零、未排空不切換。 |
| modification、歷史、ai-working-surfaces 先後整合 | 保留原資格／field paths／獨立串流及可及性等邊界。 |

## Risks / Trade-offs

- [舊分頁及外部 HTTP client 被 426 擋下] → 字串 detail 明示更新，發布先排空；不把 breaking change 隱藏成 optional 欄位。
- [seq fingerprint 與 LLM trace 的長批次記憶體] → dedup 保存 compact fingerprint，缺口資料有硬上限，正文與 image assets 避免重複複製；不把所有 lanes 預設展開。
- [各科 corrector 或圖片路徑遺漏 context／revision] → subject-matrix fixtures 及 emitter 覆蓋所有事件家族，真正 server→UI seam 驗證；review 綁定實際輸入快照。
- [首次部署沒有可證明的 drain] → 先落實準備 checkpoint；缺證據就是發布門檻不通過，不宣稱已支援安全切換。
- [DOM／SVG 預覽在某瀏覽器不能 rasterize] → 凍結資產、逐圖實測；真正失敗明示缺圖且保留 JSON，禁止靜默省略。
- [同步 main specs 被誤讀成已上線] → tasks 保持未勾選、change 保持 active；新 ADR exception 只在實作及發布驗收後適用。

## Migration Plan

1. 完成四組協定、跨層狀態／匯出與共用 modification 驗收；建立相容準備 checkpoint 與獨立 gateway／drain 控制。保留可回滾版本，確認 backend 不再能從公開路徑繞過 gate。
2. 操作者關閉受理，從舊分頁與直接 API 跨所有入口驗證 503 且零新工作；既有 SSE 繼續接收。新版本驗證只能走受控測試入口，不公開放行混合部署。
3. 逐一確認所有舊 process 的 active work、streams、queue 都排空後才替換。任何未知或活躍項目都阻止下一步，不強制終止來偽造排空。
4. gate 關閉期間切換所有 backend 與 frontend；驗證新 manifest／terminal、舊分頁 426 零派工、沒有 S0 公開路由、文件與測試證據完整，再開放受理。
5. 單邊不相容 rollback 重用 pause→drain；gate 保持關閉直到 C1/S1 與版本門檻恢復。C0 重整仍只有 C0 時不稱服務恢復；S0 不帶 gate 時仍由獨立入口拒受理。
6. 意外中斷按未知／保留內容呈現，不重送、不宣稱取消，也不以故障替代正常排空。背景恢復由獨立地圖承接。
7. 後續交付新 ADR 並在 ADR 0009 留下條件連結、保留 legacy 限制；更新協定／部署文件與 CONTEXT 已決議的教師詞彙。ADR 0016 的歷程分離原則不改。

提案作者負責 artifacts 與來源完整對照；實作者交付可重現測試／瀏覽器證據；技術 reviewer 核對全部跨層門檻；教師核對可見結果含義；發布操作者保存 pause、drain、版本與回滾演練證據。這些責任不由一次前端 build 通過替代。
