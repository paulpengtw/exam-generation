# Prototype 720 — 操作回饋 (action feedback) walkthrough

Issue #727 · wayfinder map #720. **Throwaway.** Run against a scripted fake backend — no Python, no LLM, no database credentials required.

---

## One command

```bash
cd web
npm run proto:720 --cache /tmp/claude-1000/npm-cache
```

This sets `PROTO_720=1` and starts Vite dev server at http://localhost:5173.

---

## URLs to open

| Page | URL |
|---|---|
| Login (magic-link bypass) | http://localhost:5173/verify?token=x&email=demo@example.com |
| Generate — 社會領域 (variant A) | http://localhost:5173/generate/social_studies |
| Generate — variant B | http://localhost:5173/generate/social_studies?variant=B |
| History list | http://localhost:5173/history |
| History detail | http://localhost:5173/history (click any row to open a detail page) |

The `/verify` endpoint accepts any `token` and `email` — there is no real auth check.

---

## Prototype switcher bar

A fixed pill labelled **727 · THROWAWAY** appears in the bottom-right corner (above the 生成進度列). Controls:

| Control | Effect |
|---|---|
| ← / → buttons (or `ArrowLeft` / `ArrowRight` keys) | Cycle variant A ↔ B |
| **減少動態** checkbox | Sets `?motion=reduced` → `data-motion="reduced"` on `<html>` → Motion `reducedMotion="always"` |
| **強制失敗** checkbox | Appends `?fail=…` to backend calls so resolve / download / SSE stream / history fail with a 500 |
| **批次 3 題** checkbox | Sets `?batch=3`; the form does NOT auto-fill count — manually enter `3` in the 題數 field; the fake backend then interleaves three question SSE streams |
| **慢速 4×** checkbox | Sets `?slow=4`; all motion tokens are multiplied by 4 at runtime |

---

## Numbered walkthrough script

**Step 0 — Login**

Open http://localhost:5173/verify?token=x&email=demo@example.com. The app redirects to the subject-select page.

**Step 1 — Confirmation view and 確定發送 hand-off**

1. Navigate to http://localhost:5173/generate/social_studies.
2. Click **產生** (the resolve button). Wait ~600 ms for the confirmation view to slide in.
3. Press **確定發送**. Watch the button enter 處理中 (spinner + label swap). After the first SSE event the button hand-off fires: the confirmation section exits downward (quick / 150 ms), the form section enters (standard / 320 ms), and the 生成進度列 at the bottom pulses and shows its running indicator.
4. Watch the breadcrumb walk: 產生中 → 文本生成中 → 子題生成中 1/3 → 子題生成中 2/3 → 子題生成中 3/3 → 圖片生成中 → 審題中 → 改題中 → done. Each live step shimmers; done steps turn green; pending steps are grey.
5. After the run completes, the results list enters with a staggered entrance (each card fades in 8 px upward at 40 ms intervals, capped at 400 ms total).

**Step 2 — Export 已完成 treatment (variant A vs B)**

1. In results, click **下載全部 ODT** (variant A).  
   - The button label swaps to 已下載 with a green tint and a ✓ icon. It persists until the next pointerdown/keydown anywhere or a route change.  
   - Click anywhere to dismiss; click the button again to start a fresh 下載.
2. Press `→` to switch to variant B, then click **下載全部 ODT** again.  
   - Only the icon slot morphs (spinner → ✓); the label text stays. A one-line inline confirmation appears below the button naming the produced file (e.g. `已下載 exam_2026-09-14.odt`).

**Step 3 — Forced failure (下載全部 ODT)**

1. Enable **強制失敗** in the switcher.
2. Click **下載全部 ODT**.  
   - The button enters 處理中, then 失敗. An `InlineFailureNotice` (`role="alert"`) appears directly below the button row, full width, with the error reason and a 重試 button. Dismiss with ×.
3. Click 重試 — same cycle.

**Step 4 — 重抽 row**

1. In the confirmation view (press 產生 again from the main form), find any drawn row in 已抽取值 (e.g. 情境).
2. Click **重抽** on that row. The row value dims and the button disables while the resolve request is in flight (~600 ms). On return the row flashes once.
3. On odd-numbered redraws the value changes. On even-numbered redraws the value is identical and a small hint reads 「重抽結果與原值相同」.

**Step 5 — 強制失敗 on 重抽**

1. Enable **強制失敗** in the switcher.
2. Press **重抽** on any drawn row.  
   - The button shows 失敗; the existing resolver banner also shows the error. An inline notice appears below the row with a retry.

**Step 6 — History paging**

1. Open http://localhost:5173/history.  
   - Two pages of items are pre-seeded (12 items per page; 24 total). The history list fades in.
2. Click the next-page button. The pager buttons enter 處理中 (spinner), stale rows dim with `aria-busy="true"`. After ~600 ms the new page renders. Layout stays stable (no shift).
3. Enable **強制失敗** and click next — a 失敗 inline notice appears below the pager with a retry.

**Step 7 — History download**

1. Open a history detail page (click any row in the history list).
2. Click **下載 JSON**. The button enters 處理中 then 已下載 (variant A) or icon-only (variant B) after ~600 ms.
3. Enable **強制失敗** and retry — inline failure notice.

**Step 8 — 減少動態**

1. Enable **減少動態** in the switcher.
2. Repeat any of the above steps. All entrance/exit animations collapse to an instant opacity change (1 ms). The shimmer and spinner keep running but as an opacity pulse with no translation or rotation. The hand-off and breadcrumb transitions are instant.
3. Disable **減少動態** to compare.

**Step 9 — 慢速 4×**

1. Enable **慢速 4×**.
2. Press **產生** and then **確定發送**. Each motion token is multiplied by 4: the hand-off takes ~2.4 s total, breadcrumb transitions are visible frame by frame. Useful for inspecting easing curves.

**Step 10 — 批次 3 題**

1. Enable **批次 3 題**, set the form's 題數 field to `3`, then press **產生** and **確定發送**.
2. Three question SSE streams are interleaved. The 生成進度列 shows 「產生中 · 已完成 k / 3」 as each question finishes. Each in-flight QuestionCard carries a phase chip (spinner + phase label) beside its result chips. All three cards enter the results list with stagger on completion.

---

## Timing table

| Moment | Token | ms | Easing |
|---|---|---|---|
| Confirmation view exits (↓ hand-off beat 1) | quick | 150 | exit `cubic-bezier(0.64, 0, 0.78, 0)` |
| Form section re-enters (hand-off beat 2) | standard | 320 | signature `cubic-bezier(0.22, 1, 0.36, 1)` |
| 生成進度列 background pulse (hand-off beat 3, starts 100 ms after beat 1) | standard | 320 | signature |
| QuestionCard entrance (opacity + 8 px up) | standard | 320 | signature |
| QuestionCard list stagger interval | — | 40 ms per card (max 400 ms total) | — |
| DestructiveConfirm open (fade + 8 px up) | standard | 320 | signature |
| DestructiveConfirm close | quick | 150 | exit |
| Backdrop fade | standard | 320 | signature |
| Disclosure section expand (Motion height + opacity) | standard | 320 | signature |
| Route cross-fade (viewTransition) | slow | 560 | signature |
| Control state swap (label/icon change, `tw-animate-css animate-in`) | standard | 320 | signature |
| 生成進度列 shimmer sweep period | loop | 2250 | loop `cubic-bezier(0.25, 0.1, 0.25, 1)` |
| Spinner rotation period | loop | 2250 | loop |

---

## What is faked

| Fake item | Notes |
|---|---|
| Auth | `/auth/verify` accepts any `token` + `email`; no password or magic-link email sent |
| `/api/schemas` | Only 社會領域 served; `math` and `natural_sciences` return HTTP 422 with a hint message |
| `/api/generate/resolve` | Pure in-process JS resolver; ~600 ms artificial delay; odd-counter redraws differ, even-counter redraws are identical (so the same-value flash can be felt) |
| `/api/generate` SSE stream | Scripted 32-step timeline; ~2 s per phase; no real LLM calls |
| `/api/history` | 24 pre-seeded in-memory records (2 pages); cleared on server restart |
| `/api/history/:id/download` | Returns the stored question JSON; ~600 ms artificial delay |
| ODT export (下載全部 ODT / 下載 ODT) | JSZip build runs in the browser with real question data, then offers a `.zip` download; no Python docx rendering |
| Forced batch ODT failure | When **強制失敗** is on, the JSZip build rejects for 題組 #2 with a client-side reason string; ONE inline notice names the failed 題組 and no file is produced |
| Modification stream | Scripted 3-step stream (修改 → 審題 → 改題); source record must already exist in the in-memory history |
| Image | A real PNG (`community-budget.png`) is returned base64-encoded for every question |

## What is rough / known gaps

- **Math and natural sciences subjects**: the generate page for those routes will load but the schema endpoint returns 422, so the form cannot be filled. Open `/generate/social_studies` directly.
- **批次 3 題 switcher toggle**: the form's 題數 field is NOT auto-filled; the reviewer must manually enter `3`.
- **ODT per-card download**: uses the same JSZip path as the batch; file is a `.zip` containing a single `.odt` stub (not a real word processor document).
- **Per-card 下載 JSON / 下載 PNG**: not instrumented with `ActionButton` (brief scope exclusion).
- **DestructiveConfirm CSS transitions**: `@starting-style` and `transition-behavior: allow-discrete` are used for the backdrop and dialog; browser support requires Chrome 117+ / Firefox 129+ / Safari 17.4+; older browsers fall back to an instant open/close.
- **viewTransition cross-fade**: feature-detected; falls back silently to an instant navigation on unsupported browsers.
- **In-memory history**: all history records are lost on Vite dev server restart.
- **Spinner in AgentStatusPanel / GenerationStatusBar**: two test files remain failing because the shared `Spinner` component replaced the hand-rolled `animate-spin` class (`AgentStatusPanel.test.tsx`, 2 tests) and because breadcrumb labels were renamed and ◐ removed (`GenerationStatusBar.test.tsx`, 7 tests). These are acceptable per brief (decided label renames and removed glyph).
