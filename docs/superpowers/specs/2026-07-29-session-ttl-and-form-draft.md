# Session 新鮮度保證與表單草稿持久化

**日期**：2026-07-29
**狀態**：共識已達成，待實作
**起點需求**：「要保證 login session 只剩不到 60 minutes 時會強制把人踢出去，所以應該要在開始 input 都要確認是否 TTL > 60 minutes」

---

## 1. 要解決的問題

使用者花 **約 30 分鐘（平均）** 填完 `ParamForm`，按下送出時才發現 session 已過期 → 401 → `logout()` → `AuthGuard` 導回 `/` → **全部填寫內容歸零**。

## 2. 現況（實作前，已查證）

| 事實 | 位置 |
|---|---|
| JWT HS256，`exp = now + JWT_EXPIRE_DAYS`，預設 7 天 | `server/auth/tokens.py:33`、`server/config.py:18` |
| 無 refresh、無 server-side session store、無撤銷機制 | `server/auth/` |
| `/auth/me` 只回 `{id, email, created_at}` | `server/auth/routes.py:160` |
| token 存 localStorage；`isAuthenticated()` 只檢查 `token !== null`，從不解析 `exp` | `web/src/store/authStore.ts:57` |
| 401 → 前端直接 `logout()` | `web/src/api/client.ts:76`、`web/src/hooks/useGenerate.ts:343` |
| `ParamForm.tsx` 2108 行、約 30 個 form state；**只有 `model_plan` / `model_execute` 有持久化** | `web/src/components/ParamForm.tsx:427-543` |
| 既有 prefill 來源：`location.state.prefillParams`（history「再出一次」） | `web/src/pages/GeneratePage.tsx:32` |
| `VerifyPage` 驗證成功後寫死導向 `/generate` | `web/src/pages/VerifyPage.tsx:33` |
| 已有 `limiter` + `jwt_user_key`（依 JWT sub 限流，退回 IP） | `server/rate_limit.py` |

### 兩個推翻原始假設的發現

1. **生成本身不需要 TTL 預算。** `/api/generate` 的 `get_current_user` 只在**開串當下**執行一次（`server/generate/routes.py:124`），開串後 token 過期不影響 SSE 串流；結果落地在 server 端（`server/generate/persistence.py`），不經前端。
2. **匯出 ODT 也不需要。** `web/src/utils/odt.ts` 沒有任何 fetch，是純前端組檔。

→ **TTL 預算要買的只有「填表單」這一段。**

## 3. 最終方案的形狀

原始需求「TTL > 60 分鐘才讓人開始 input」，經討論後演變為：

> **進表單前確保 session 是新鮮的；不新鮮就當場續期；續不了才擋。**

`session_min_ttl_minutes` 的語意從「踢人門檻」變成「**續期觸發點**」：

- TTL < 360 分鐘 → 嘗試 `/auth/refresh`
- refresh 成功 → 靜默換票，使用者無感
- refresh 失敗（token 已過期，或 `iat_origin` 超過 30 天絕對上限）→ **此時才硬踢**

硬踢的觸發條件從「一個任意的時間邊界」變成「這個 session 真的不能再用了」。

---

## 4. 決議清單

| # | 決議 | 理由 |
|---|---|---|
| D1 | 同時做 **入口 gate + 草稿持久化 + 送出前預檢** | 入口 gate 是時間點快照，無法保證「填到一半去開會再回來」的情境；草稿才是真正的保證 |
| D2 | TTL 不足時採 **硬踢**：`logout()` 清 token + 導回 `/` | 行為一致性、與未來 user-owned history 的資料歸屬一致 |
| D3 | 草稿 key 為 **`paramform_draft:<user_id>`，logout 不清除，7 天後自動失效** | 全域 key 會讓下一個登入者看到前人草稿；logout 清掉則在最需要的那一刻自我抵銷 |
| D4 | `/auth/me` 新增 **`expires_at`（ISO 8601 UTC 絕對時間）**；gate 決策一律重打 `/auth/me`，本地倒數僅供顯示 | 不信任裝置時鐘；`expires_at` 被快取仍然正確，`ttl_seconds` 一旦快取就是錯的 |
| D5 | 門檻放 **後端 config**：`session_min_ttl_minutes`（env `SESSION_MIN_TTL_MINUTES`，預設 **360**），由 `/auth/me` 一併回傳 | 避免 auth 政策一半在 config、一半在 tsx 裡漂移 |
| D6 | **啟動檢查**：`session_min_ttl_minutes <= jwt_expire_days * 1440 * 0.5`，不成立則啟動失敗 | 若有人把 `JWT_EXPIRE_DAYS` 調小，會變成「登入成功但一點出題就被踢回登入頁」，症狀完全無法聯想到此設定 |
| D7 | 加 **`/auth/refresh`**（拿有效 token 換新票）+ **絕對上限 30 天**（JWT 加 `iat_origin`，refresh 時原封帶過） | 純 sliding session 在沒有撤銷機制下等於外洩 token 可永久持有；絕對上限把曝險壓回 ≤30 天 |
| D8 | `/auth/refresh` 掛 **限流**，key 用 `jwt_user_key` | 不限流等於提供免費 token 產生器 |
| D9 | 舊 token 缺 `iat_origin` → **fallback 到 `iat`**，code 標註「7 天後可移除」 | 一律拒絕會讓部署瞬間全員登出，且草稿功能尚未經真實驗證就要上場 |
| D10 | `ensureFreshSession()` 掛在 **兩個點：進入 `/generate/{subject}` + 按送出**；**不做**背景定時檢查 | 背景續期會讓「開著沒人用的分頁」自己續到 30 天上限，正好抵銷 D7 的目的 |
| D11 | 硬踢時記錄 **`localStorage.post_login_redirect`**，`VerifyPage` 驗證成功後導回，**並做路徑白名單校驗** | 不碰 magic link URL，避免 open redirect；白名單只需三行 |
| D12 | 草稿還原採 **明確詢問 + 預覽**，不自動 hydrate | 自動填滿會讓使用者誤送出昨天的設定，燒掉一次完整 LLM 生成，且無法分辨畫面上的值是誰填的 |
| D13 | PR 順序：**草稿 → 後端 → 前端 gate** | 先把降落傘穿好，再啟用會踢人的邏輯 |

### 明確不做

- **不做**背景定時 refresh（D10）
- **不做**後端草稿儲存 —— 留給未來 user-owned history feature 一起設計
- **不做** magic link URL 夾帶 redirect 參數（open redirect 風險）
- **不做** `/api/generate` 的 server 端 TTL 拒絕 —— 開串後串流本來就跑得完，拒絕只會製造傷害

### 已知限制（接受）

magic link 若被 email app 的內建瀏覽器開啟，那是不同的 storage context，讀不到 `paramform_draft:<user_id>`。草稿沒有消失（仍在原瀏覽器），但使用者在 in-app browser 中會看到空表單。**只有後端草稿能真正解決**，記在帳上，留給 user-owned history。

---

## 5. 各數值的依據

| 數值 | 依據 |
|---|---|
| `session_min_ttl_minutes = 360` | 表單填寫平均 30 分鐘，取寬裕餘裕。佔 7 天壽命的 3.6%，實際效果是 session 從 7 天縮成 6.75 天，成本可忽略 |
| 絕對上限 **30 天** | 有 refresh 後，這個數字直接等於活躍使用者的重登頻率。30 天對得上月考／段考節奏，重登會落在「本來就要換一批題目」的時間點 |
| 草稿過期 **7 天** | 與 JWT 同壽命，避免 localStorage 累積殘骸 |
| debounce **1–2 秒** | `passage` 是可貼整篇文章的長文欄位，逐字寫 localStorage 會在低階機器上卡頓 |

---

## 6. 實作計畫

### PR 1 — 表單草稿持久化（零 auth 依賴）

- 以 `paramform_draft:<user_id>` 存 `ParamForm` **完整當下狀態**（含被 prefill 帶入的值 —— `location.state` 硬踢後不存在）
- 寫入時機：欄位變動後 debounce 1–2 秒
- **空草稿不存、不提示**：與預設值 diff，至少一個實質欄位不同才存。否則提示會被訓練成無腦點掉
- 清除時機：SSE 收到 `started` event 即清（**不**等生成完成 —— 生成中途關分頁不該讓草稿復活成已送出過的東西）
- 過期：寫入時記 timestamp，讀取時超過 7 天視同不存在
- **還原 modal**：預設顯示辨識性摘要，底下 `<details>` 展開全部設定
  - 摘要欄位：儲存時間（相對，如「3 小時前」）、`topic` / `coreQuestion`、`grade` + `subjectFilter`、`count` + `subQuestionCount`、`qType` / `context`、`passage` 前 50 字（**必須截斷**）
  - 選項：還原 / 從空白開始；若同時有 `prefillParams` 則為三選一
- 測試：`web/src/components/ParamForm.*.test.tsx` 既有 pattern

### PR 2 — 後端能力（行為不變，純新增）

- `server/config.py`：新增 `session_min_ttl_minutes`（env `SESSION_MIN_TTL_MINUTES`，預設 360）
- `ServerConfig.from_env()`：啟動檢查 `session_min_ttl_minutes <= jwt_expire_days * 1440 * 0.5`，不成立則 raise
- `server/auth/tokens.py`：`create_jwt` 加 `iat_origin`；`decode_jwt` 消費端缺欄位時 fallback 到 `iat`
- `server/auth/routes.py`：
  - `UserResponse` 加 `expires_at`（ISO 8601 UTC）與 `session_min_ttl_minutes`
  - 新增 `POST /auth/refresh`：`Depends(get_current_user)` → 檢查 `now - iat_origin < 30 天` → 簽發新 token（帶原 `iat_origin`）；超過上限回 401
  - `/auth/refresh` 掛 `limiter` + `jwt_user_key`
- 測試：`tests/server/test_auth_routes.py` 既有 pattern；涵蓋 refresh 成功、超過絕對上限、缺 `iat_origin` fallback、啟動檢查失敗

### PR 3 — 前端 gate（唯一改變行為的 PR）

- `ensureFreshSession()`：打 `/auth/me` → 若 TTL < `session_min_ttl_minutes` 則打 `/auth/refresh` → 失敗則 `logout()` + 寫 `post_login_redirect` + 導回 `/`
- 掛載點：進入 `/generate/{subject}`、按送出（**僅此兩點**）
- `VerifyPage`：驗證成功後讀 `post_login_redirect`，**白名單校驗**（`/generate`、`/generate/math`、`/generate/social_studies`、`/generate/natural_sciences`、`/history`），用完即刪；不合法或不存在則維持現行 `/generate`
- i18n：`web/src/i18n/messages.ts` 補 zh / en 兩份字串
- 測試：`GeneratePage.test.tsx`、`VerifyPage` 相關測試

---

## 7. 驗收條件

1. 打開表單時 token 剩 2 小時 → 靜默 refresh，使用者無任何中斷，`expires_at` 變回 7 天後
2. 打開表單時 token 已過期 → 立刻硬踢，此時尚未輸入任何內容，零損失
3. 填 30 分鐘 → 離開 3 小時 → 回來送出 → 送出時 refresh → 正常開串
4. `iat_origin` 超過 30 天 → refresh 回 401 → 硬踢 → **重登後草稿完整還原**，且導回原本的科目表單頁
5. 只點進表單看一眼就離開 → 下次進入**不出現**還原提示
6. 成功開串後重新進入表單 → **不出現**還原提示（草稿已於 `started` 清除）
7. 使用者 A 被踢後，使用者 B 在同一台機器登入 → 表單乾淨，看不到 A 的草稿
8. `JWT_EXPIRE_DAYS=1` 配 `SESSION_MIN_TTL_MINUTES=360` → **啟動失敗**並顯示明確訊息
